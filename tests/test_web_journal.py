"""Complete chronological policy tasks through the existing bounded HTTP routes."""

import base64
from copy import deepcopy
from dataclasses import asdict, replace
import io
import json
import unittest
from unittest.mock import patch
import zipfile

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.controllers import QTable
from event_control_lab import policy, policy_journal as journal, web_journal
from event_control_lab.planned_study import PlannedSpec
import test_server


class WebJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_server.ServerTests.setUpClass.__func__(cls)
        lab=ControllerLabSpec()
        cls.config=replace(lab.config,duration=0.2,budget=10)
        trained=controller_lab(replace(lab,config=cls.config,training_seeds=(101,102),evaluation_seeds=(1001,)),"rl")
        cls.saved=policy.checkpoint(trained)
        cls.spec=PlannedSpec(config=replace(cls.config,initial_position=0.75,budget=5),
                            absolute_thresholds=(2,),relative_thresholds=(),rmse_limit=100,
                            selection_seeds=(5001,),test_seeds=(6001,),previously_used_seeds=(7001,))

    tearDownClass=classmethod(test_server.ServerTests.tearDownClass.__func__)
    request=test_server.ServerTests.request

    def post(self,path,payload,status=200):
        actual,_,body=self.request('POST',path,json.dumps(payload))
        self.assertEqual(actual,status,body[:400])
        return json.loads(body)

    def evaluate(self,value=None,seeds=None,status=200):
        return self.post('/api/evaluate-policy',{'checkpoint':self.saved if value is None else value,
            'seeds':[9001] if seeds is None else seeds,'keep_history':True},status)

    def select(self,value,spec=None,status=200):
        return self.post('/api/planned/select',{'spec':asdict(self.spec if spec is None else spec),
            'policy_checkpoint':value,'keep_history':True},status)

    def run_test(self,value,status=200):
        return self.post('/api/planned/test',{'selection':value,'keep_history':True},status)

    def test_complete_http_task_matches_local_numerics_and_preserves_chronology(self):
        original=deepcopy(self.saved)
        with patch.object(QTable,'update',side_effect=AssertionError('no training')):
            evaluated=self.evaluate()
            choice=self.select(evaluated['policy_history'])
            tested=self.run_test(choice['workflow'])
            later=self.evaluate(tested['policy_history'],[9002])
        self.assertEqual(evaluated['workflow']['data'],json.loads(json.dumps(policy.evaluate_policy(self.saved,[9001]))))
        direct=journal.select_plan(self.spec,evaluated['policy_history'])
        self.assertEqual(choice['record'],json.loads(json.dumps(direct['data']['result'])))
        self.assertEqual(tested['record'],json.loads(json.dumps(journal.test_plan(direct)['data']['result'])))
        self.assertEqual([event['phase'] for event in later['policy_history']['events']],
                         ['evaluation','declared_development','selection','test','evaluation'])
        self.assertEqual(later['checkpoint']['previous_evaluation_seeds'],[1001,9001,7001,5001,6001,9002])
        self.assertEqual(later['checkpoint']['table'],original['table'])
        self.assertEqual(self.saved,original)
        self.assertEqual(len(later['rows']),6)
        self.assertTrue(all(row['stage']!='training' for row in later['rows']))

    def test_zip_keeps_full_choice_workflow_history_and_unmodified_raw_record(self):
        evaluated=self.evaluate()
        choice=self.select(evaluated['policy_history'])
        original=deepcopy(choice['workflow'])
        tested=self.run_test(choice['workflow'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(tested['archive_base64']))) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(json.loads(archive.read('selection-workflow.json')),original)
            self.assertEqual(json.loads(archive.read('policy-workflow.json')),tested['workflow'])
            self.assertEqual(json.loads(archive.read('policy-history.json')),tested['policy_history'])
            self.assertEqual(json.loads(archive.read('test.json')),tested['record'])
        self.assertEqual(choice['workflow'],original)
        self.assertEqual(tested['selection_workflow'],original)

    def test_pending_and_reused_numbers_refuse_before_any_inference(self):
        evaluated=self.evaluate()
        choice=self.select(evaluated['policy_history'])
        with patch('event_control_lab.policy.compare') as inference:
            error=self.evaluate(choice['policy_history'],[9002],400)
            self.assertIn('待复核',error['error'])
        inference.assert_not_called()
        tested=self.run_test(choice['workflow'])
        original=deepcopy(tested['policy_history'])
        with patch('event_control_lab.policy.compare') as inference, \
                patch('event_control_lab.planned_policy.simulate') as simulation:
            for seed in (101,1001,9001,7001,5001,6001):
                self.evaluate(tested['policy_history'],[seed],400)
            self.select(tested['policy_history'],replace(self.spec,selection_seeds=(9001,),test_seeds=(6002,)),400)
        inference.assert_not_called()
        simulation.assert_not_called()
        self.assertEqual(tested['policy_history'],original)
        self.assertEqual(self.evaluate(tested['policy_history'],[9002])['policy_history']['events'][-1]['seeds'],[9002])

    def test_completed_outputs_and_history_survive_a_continuation_size_limit(self):
        evaluated=journal.evaluate_saved(self.saved,[9001])
        chosen=journal.select_plan(self.spec,evaluated['history_after'])
        with patch.object(web_journal,'REQUEST_LIMIT',1):
            response=web_journal.pack(chosen)
        self.assertFalse(response['web_testable'])
        self.assertEqual(response['workflow'],chosen)
        self.assertEqual(response['policy_history']['events'][-1]['phase'],'selection')
        self.assertTrue(response['continuation_note'])
        self.assertTrue(response['archive_base64'])
        with patch.object(web_journal,'POLICY_LIMIT',1):
            response=web_journal.pack(evaluated)
        self.assertFalse(response['web_reusable'])
        self.assertEqual(response['policy_history'],evaluated['history_after'])

    def test_size_clock_and_flag_errors_are_rejected_before_execution(self):
        evaluated=self.evaluate()
        choice=self.select(evaluated['policy_history'])
        with patch('event_control_lab.policy.compare') as inference, \
                patch('event_control_lab.planned_policy.simulate') as simulation:
            with patch.object(web_journal,'POLICY_LIMIT',1):
                self.evaluate(status=400)
            with patch.object(web_journal,'REQUEST_LIMIT',1):
                self.run_test(choice['workflow'],400)
            self.post('/api/evaluate-policy',{'checkpoint':self.saved,'seeds':[9002],'keep_history':'yes'},400)
            self.post('/api/planned/select',{'spec':asdict(self.spec),'policy_checkpoint':self.saved,'keep_history':1},400)
            self.post('/api/planned/test',{'selection':choice['workflow'],'keep_history':None},400)
            self.post('/api/evaluate-policy',{'checkpoint':self.saved,'seeds':[9002],'keep_history':True,
                'config':asdict(replace(self.config,dt=0.04,duration=0.4))},400)
        inference.assert_not_called()
        simulation.assert_not_called()

    def test_old_clients_without_flag_keep_old_response_and_recovery_contract(self):
        legacy=self.post('/api/evaluate-policy',{'checkpoint':self.saved,'seeds':[9001]})
        self.assertNotIn('workflow',legacy)
        self.assertNotIn('policy_history',legacy)
        self.assertEqual(len(legacy['rows']),6)
        current=self.evaluate()
        with patch('event_control_lab.policy.compare') as inference:
            error=self.post('/api/evaluate-policy',{'checkpoint':current['policy_history'],'seeds':[9002]},400)
        self.assertIn('policy_journal',error['error'])
        inference.assert_not_called()

    def test_unrun_tests_and_failed_evaluations_keep_unknown_metrics_and_actual_history(self):
        evaluated=self.evaluate()
        choice=self.select(evaluated['policy_history'],replace(self.spec,rmse_limit=1e-12))
        with patch('event_control_lab.planned_policy.simulate') as simulation:
            tested=self.run_test(choice['workflow'])
        simulation.assert_not_called()
        self.assertEqual(tested['policy_history'],choice['policy_history'])
        self.assertEqual(tested['context']['test']['state'],'not_run')
        self.assertIsNone(tested['workflow']['execution_runtime'])
        failed=self.post('/api/evaluate-policy',{'checkpoint':self.saved,'seeds':[2006,2018],
            'keep_history':True,'config':asdict(replace(self.config,budget=0,state_limit=1))})
        self.assertTrue(any(row['position_rmse'] is None for row in failed['rows']))
        self.assertEqual(failed['policy_history']['events'][-1]['seeds'],[2006,2018])


if __name__=='__main__':
    unittest.main()
