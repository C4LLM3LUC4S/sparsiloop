"""Bounded HTTP reuse of the exact local frozen-policy protocol."""

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
from event_control_lab.policy import checkpoint
from event_control_lab.planned_study import PlannedSpec
from event_control_lab import planned_context as context, planned_policy
import test_server


class WebPlannedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_server.ServerTests.setUpClass.__func__(cls)
        spec = ControllerLabSpec()
        spec = replace(spec, config=replace(spec.config, duration=0.2, budget=10),
                       training_seeds=(101, 102), evaluation_seeds=(1001,))
        cls.policy = checkpoint(controller_lab(spec, 'rl'))
        cls.spec = PlannedSpec(config=replace(spec.config, initial_position=0.75, budget=5),
            absolute_thresholds=(2,), relative_thresholds=(), selection_seeds=(3001,),
            test_seeds=(4001,), previously_used_seeds=(7001,), rmse_limit=100)

    tearDownClass = classmethod(test_server.ServerTests.tearDownClass.__func__)
    request = test_server.ServerTests.request

    def post(self, route, value, expected=200):
        status, _, data = self.request('POST', route, json.dumps(value))
        self.assertEqual(status, expected, data[:300])
        return json.loads(data)

    def test_select_and_test_match_local_records_without_training_or_mutating_originals(self):
        original = deepcopy(self.policy)
        with patch.object(QTable, 'update', side_effect=AssertionError('web must not train')):
            chosen = self.post('/api/planned/select', {'spec':asdict(self.spec), 'policy_checkpoint':self.policy})
            self.assertEqual(chosen['record'], json.loads(json.dumps(context.select_with_context(self.spec, policy_checkpoint=self.policy)['result'])))
            bundle = {'format':context.BUNDLE_FORMAT, 'result':chosen['record'], 'context':chosen['context']}
            saved = deepcopy(bundle)
            tested = self.post('/api/planned/test', {'selection':bundle})
            self.assertEqual(tested['record'], json.loads(json.dumps(context.test_with_context(bundle)['result'])))
        self.assertEqual(bundle, saved)
        self.assertEqual(self.policy, original)
        self.assertEqual(tested['context']['selection'], chosen['context']['selection'])
        self.assertEqual(tested['record']['selected_id'], chosen['record']['selected_id'])

    def test_zip_retains_complete_history_checkpoint_and_original_choice_bundle(self):
        choice = self.post('/api/planned/select', {'spec':asdict(self.spec), 'policy_checkpoint':self.policy})
        tested = self.post('/api/planned/test', {'selection':choice['record']})
        for response in (choice, tested):
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(response['archive_base64']))) as archive:
                self.assertIsNone(archive.testzip())
                history = json.loads(archive.read('policy-history.json'))
                self.assertEqual(history, response['record']['policy_after'])
                self.assertEqual(json.loads(archive.read('policy-checkpoint.json')), history['checkpoint'])
                self.assertEqual(history['declared_development_seeds'], [7001])
                phases = [row['phase'] for row in history['planned_history']]
                self.assertEqual(phases, ['selection'] if response is choice else ['selection','test'])
                self.assertEqual(json.loads(archive.read('selection-bundle.json'))['result'], choice['record'])

    def test_history_reuse_is_refused_and_fresh_plan_recovers(self):
        first = self.post('/api/planned/select', {'spec':asdict(self.spec), 'policy_checkpoint':self.policy})
        tested = self.post('/api/planned/test', {'selection':first['record']})
        history = tested['record']['policy_after']
        with patch.object(planned_policy, 'simulate', side_effect=AssertionError('old seed must reject first')):
            for seed in (101,1001,3001,4001,7001):
                spec = replace(self.spec, selection_seeds=(seed,), test_seeds=(6001,), previously_used_seeds=())
                value = self.post('/api/planned/select', {'spec':asdict(spec), 'policy_checkpoint':history}, 400)
                self.assertIn('编号', value['error'])
        spec = replace(self.spec, selection_seeds=(5001,), test_seeds=(6001,))
        recovered = self.post('/api/planned/select', {'spec':asdict(spec), 'policy_checkpoint':history})
        self.assertEqual(len(recovered['record']['policy_after']['planned_history']), 3)
        self.assertEqual(recovered['record']['policy_before'], history)

    def test_missing_damaged_oversized_and_different_clock_reject_before_simulation(self):
        values = [None, {}, self.policy['table'], {'padding':'x'*(2*1024*1024)}]
        damaged = deepcopy(self.policy)
        damaged['table_sha256'] = 'wrong'
        values.append(damaged)
        with patch.object(planned_policy, 'simulate', side_effect=AssertionError('invalid policy ran')):
            for value in values:
                self.post('/api/planned/select', {'spec':asdict(self.spec), 'policy_checkpoint':value}, 400)
            spec = replace(self.spec, config=replace(self.spec.config, duration=0.4))
            self.post('/api/planned/select', {'spec':asdict(spec), 'policy_checkpoint':self.policy}, 400)
            self.post('/api/planned/select', {'spec':asdict(self.spec), 'policy_checkpoint':self.policy, 'python':'code'}, 400)
            self.post('/api/planned/test', {'selection':{}, 'policy_checkpoint':self.policy}, 400)

    def test_no_eligible_choice_does_not_consume_tests_or_invent_environment(self):
        spec = replace(self.spec, config=replace(self.spec.config, budget=0, initial_position=1, state_limit=1))
        chosen = self.post('/api/planned/select', {'spec':asdict(spec), 'policy_checkpoint':self.policy})
        with patch.object(planned_policy, 'simulate', side_effect=AssertionError('ineligible choice tested')):
            tested = self.post('/api/planned/test', {'selection':chosen['record']})
        self.assertEqual(tested['record']['test_runs'], [])
        self.assertEqual(tested['context']['test'], {'state':'not_run','runtime':None})
        self.assertEqual(tested['record']['policy_after'], chosen['record']['policy_after'])

    def test_web_resources_expose_explicit_mode_history_reuse_and_persistent_locks(self):
        for route, required in [('/', ['controller_kind','planned-policy-history','planned-use-controller-policy']),
                                ('/planned.js', ['policy_checkpoint','policy-history.json','dataset.locked']),
                                ('/controllers.js', ['sparsiloop-policy-saved']),
                                ('/app.js', ['dataset.locked'])]:
            status, _, content = self.request('GET',route)
            self.assertEqual(status,200)
            for text in required:
                self.assertIn(text,content.decode('utf-8'))
