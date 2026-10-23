"""A complete local task across evaluation, selection, testing and saved history."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.controllers import QTable, initial_position
from event_control_lab import planned_context as context, policy, policy_journal as journal
from event_control_lab.planned_study import PlannedSpec
from event_control_lab.policy_journal_report import export_workflow


class PolicyJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lab = ControllerLabSpec()
        cls.config = replace(lab.config, duration=0.2, budget=10)
        trained = controller_lab(replace(lab, config=cls.config, training_seeds=(101, 102),
                                         evaluation_seeds=(1001,)), "rl")
        cls.checkpoint = policy.checkpoint(trained)
        cls.original_spec = PlannedSpec(config=replace(cls.config, initial_position=0.75, budget=5),
            absolute_thresholds=(2,), relative_thresholds=(), rmse_limit=100,
            selection_seeds=(3001,), test_seeds=(4001,), previously_used_seeds=(7001,))
        cls.original_choice = context.select_with_context(cls.original_spec, policy_checkpoint=cls.checkpoint)
        cls.original_test = context.test_with_context(cls.original_choice)
        cls.origin = cls.original_test["result"]["policy_after"]

    def spec(self, **changes):
        return replace(self.original_spec, selection_seeds=(5001,), test_seeds=(6001,),
                       previously_used_seeds=(8001,), **changes)

    def chain(self):
        evaluation = journal.evaluate_saved(self.origin, [9001])
        choice = journal.select_plan(self.spec(), evaluation["history_after"])
        testing = journal.test_plan(choice)
        return evaluation, choice, testing

    def test_complete_chronological_chain_keeps_origin_and_frozen_table(self):
        original = deepcopy(self.origin)
        with patch.object(QTable, "update", side_effect=AssertionError("must not train")):
            evaluation, choice, testing = self.chain()
            later = journal.evaluate_saved(testing["history_after"], [9002])
        history = later["history_after"]
        self.assertEqual(history["origin"], original)
        self.assertEqual(self.origin, original)
        self.assertEqual([event["phase"] for event in history["events"]],
                         ["evaluation", "declared_development", "selection", "test", "evaluation"])
        self.assertEqual([event["seeds"] for event in history["events"]],
                         [[9001], [8001], [5001], [6001], [9002]])
        self.assertEqual(history["checkpoint"]["previous_evaluation_seeds"],
                         self.origin["checkpoint"]["previous_evaluation_seeds"] + [9001, 8001, 5001, 6001, 9002])
        self.assertEqual(history["checkpoint"]["table"], self.checkpoint["table"])
        for item in (evaluation, choice, testing, later):
            self.assertEqual(journal.load_workflow(json.loads(json.dumps(item))), json.loads(json.dumps(item)))

    def test_initial_state_and_reference_protocols_remain_different(self):
        evaluation, _, testing = self.chain()
        case = evaluation["data"]["cases"][0]
        self.assertEqual(case["policy"]["config"]["initial_position"], initial_position(9001))
        self.assertEqual(len(case["policy"]["runs"]), 3)
        self.assertEqual(len(case["linear_feedback"]["runs"]), 3)
        self.assertEqual(testing["data"]["result"]["selection"]["spec"]["config"]["initial_position"], 0.75)
        self.assertTrue(all(row["config"]["initial_position"] == 0.75
                            for row in testing["data"]["result"]["test_runs"]))
        self.assertEqual(evaluation["data"], policy.evaluate_policy(self.origin["checkpoint"], [9001]))

    def test_all_known_used_seed_categories_are_rejected_before_execution(self):
        _, _, testing = self.chain()
        history = testing["history_after"]
        with patch("event_control_lab.policy.compare") as inference, \
                patch("event_control_lab.planned_policy.simulate") as simulation:
            for seed in (101, 1001, 7001, 3001, 4001, 9001, 8001, 5001, 6001):
                with self.subTest(seed=seed), self.assertRaises(ValueError):
                    journal.evaluate_saved(history, [seed])
            with self.assertRaises(ValueError):
                journal.select_plan(replace(self.spec(), selection_seeds=(9001,), test_seeds=(9501,)), history)
        inference.assert_not_called()
        simulation.assert_not_called()

    def test_pending_plan_requires_original_test_before_any_new_task(self):
        choice = journal.select_plan(self.spec(), self.origin)
        with patch("event_control_lab.policy.compare") as inference, \
                patch("event_control_lab.planned_policy.simulate") as simulation:
            for seeds in ([6001], [9003]):
                with self.assertRaisesRegex(ValueError, "待复核"):
                    journal.evaluate_saved(choice["history_after"], seeds)
            with self.assertRaisesRegex(ValueError, "待复核"):
                journal.select_plan(replace(self.spec(), selection_seeds=(5002,), test_seeds=(6002,)),
                                    choice["history_after"])
        inference.assert_not_called()
        simulation.assert_not_called()

    def test_incomplete_legacy_history_needs_complete_original_test_record(self):
        partial = self.original_choice["result"]["policy_after"]
        with patch("event_control_lab.policy.compare") as inference:
            with self.assertRaisesRegex(ValueError, "test-bundle.json"):
                journal.evaluate_saved(partial, [9001])
        inference.assert_not_called()
        result = journal.evaluate_saved(self.original_test, [9001])
        self.assertEqual(result["history_after"]["origin"], self.original_test)

    def test_no_eligible_choice_does_not_consume_reserved_test_or_fake_environment(self):
        choice = journal.select_plan(self.spec(rmse_limit=1e-12), self.origin)
        self.assertIsNone(choice["data"]["result"]["selected_id"])
        with patch("event_control_lab.planned_policy.simulate") as simulation:
            testing = journal.test_plan(choice)
        simulation.assert_not_called()
        self.assertEqual(testing["history_after"], choice["history_after"])
        self.assertIsNone(testing["execution_runtime"])
        self.assertEqual(testing["data"]["context"]["test"]["state"], "not_run")
        self.assertNotIn(6001, testing["history_after"]["checkpoint"]["previous_evaluation_seeds"])
        journal.evaluate_saved(testing["history_after"], [6001])

    def test_legacy_unrun_test_bundle_can_resolve_the_unknown_reservation(self):
        spec = replace(self.original_spec, rmse_limit=1e-12)
        selected = context.select_with_context(spec, policy_checkpoint=self.checkpoint)
        result = context.test_with_context(selected)
        self.assertFalse(result["result"]["test_runs"])
        continued = journal.evaluate_saved(result, [4001])
        self.assertEqual(continued["history_after"]["origin"], result)

    def test_clock_source_table_and_corrupt_history_reject_before_inference(self):
        evaluation = journal.evaluate_saved(self.origin, [9001])
        variants = []
        for field, replacement in (("table_sha256", "0"*64), ("source_sha256", {}),
                                    ("training_config", dict(self.checkpoint["training_config"], dt=0.04))):
            bad = deepcopy(evaluation["history_after"])
            bad["checkpoint"][field] = replacement
            journal.signed(bad["checkpoint"], "checkpoint_sha256")
            journal.signed(bad, "history_sha256")
            variants.append(bad)
        wrong_order = deepcopy(evaluation["history_after"])
        wrong_order["events"][0]["seeds"] = [True]
        journal.signed(wrong_order, "history_sha256")
        variants.append(wrong_order)
        with patch("event_control_lab.policy.compare") as inference:
            for bad in variants:
                with self.subTest(bad=bad["checkpoint"]["table_sha256"]), self.assertRaises(ValueError):
                    journal.evaluate_saved(bad, [9002])
            with self.assertRaises(ValueError):
                journal.evaluate_saved(self.origin, [9002], replace(self.config, dt=0.04, duration=0.4))
        inference.assert_not_called()

    def test_legacy_test_record_must_match_the_saved_test_numbers(self):
        wrong = deepcopy(self.original_test)
        wrong["result"]["test_runs"][0]["seed"] = 4999
        wrong["context"] = context.context_for(wrong["result"], selection=wrong["context"]["selection"],
                                             testing=wrong["context"]["test"])
        with patch("event_control_lab.policy.compare") as inference:
            with self.assertRaisesRegex(ValueError, "复核运行"):
                journal.evaluate_saved(wrong, [9001])
        inference.assert_not_called()

    def test_new_formats_have_explicit_web_recovery_without_execution(self):
        from event_control_lab.web_recipes import test_saved_policy
        from event_control_lab.web_planned import select_from_web, test_from_web

        evaluation, choice, _ = self.chain()
        with patch("event_control_lab.web_recipes.evaluate_policy") as inference, \
                patch("event_control_lab.web_planned.select_with_context") as selection, \
                patch("event_control_lab.web_planned.test_with_context") as testing:
            for function, payload in (
                    (test_saved_policy, {"checkpoint":evaluation["history_after"], "seeds":[9002]}),
                    (select_from_web, {"spec":asdict(self.spec()), "policy_checkpoint":evaluation["history_after"]}),
                    (test_from_web, {"selection":choice})):
                with self.assertRaisesRegex(ValueError, "policy_journal"):
                    function(payload)
        inference.assert_not_called()
        selection.assert_not_called()
        testing.assert_not_called()

    def test_workflow_binding_rejects_wrong_origin_phase_case_and_source(self):
        evaluation, choice, testing = self.chain()
        variants = []
        for value, field, replacement in ((choice, "history_before", testing["history_after"]),
                                           (evaluation, "source_sha256", {}),
                                           (testing, "phase", "selection")):
            bad = deepcopy(value)
            bad[field] = replacement
            journal.signed(bad, "record_sha256")
            variants.append(bad)
        bad = deepcopy(evaluation)
        bad["data"]["cases"][0]["seed"] = 9002
        journal.signed(bad, "record_sha256")
        variants.append(bad)
        with patch("event_control_lab.policy.compare") as inference, \
                patch("event_control_lab.planned_policy.simulate") as simulation:
            for value in variants:
                with self.assertRaises(ValueError):
                    journal.load_workflow(value)
        inference.assert_not_called()
        simulation.assert_not_called()

    def test_failed_runs_keep_nulls_and_consume_actual_used_seeds(self):
        result = journal.evaluate_saved(self.origin, [2006, 2018], replace(self.config, budget=0, state_limit=1))
        runs = [run for case in result["data"]["cases"] for run in case["policy"]["runs"]]
        self.assertTrue(any(run["metrics"]["position_rmse"] is None for run in runs))
        self.assertEqual(result["history_after"]["events"][-1]["seeds"], [2006, 2018])
        with tempfile.TemporaryDirectory() as temporary:
            export_workflow(result, Path(temporary)/"failure")
            self.assertEqual(json.loads((Path(temporary)/"failure/evaluation.json").read_text(encoding="utf-8")),
                             json.loads(json.dumps(result["data"])))

    def test_report_redraw_preserves_raw_history_and_execution_environment_without_simulation(self):
        _, _, result = self.chain()
        with tempfile.TemporaryDirectory() as temporary:
            first, redraw = Path(temporary)/"first", Path(temporary)/"redraw"
            export_workflow(result, first)
            with patch("event_control_lab.policy.compare") as inference, \
                    patch("event_control_lab.planned_policy.simulate") as simulation:
                export_workflow(json.loads((first/"policy-workflow.json").read_text(encoding="utf-8")), redraw)
            inference.assert_not_called()
            simulation.assert_not_called()
            for name in ("test.json", "runs.csv", "trajectories.csv", "policy-history.json", "policy-workflow.json",
                         "policy-checkpoint.json", "numeric-policy-history-v1.json", "test-bundle.json"):
                self.assertEqual((first/name).read_bytes(), (redraw/name).read_bytes(), name)
            for folder in (first, redraw):
                page = (folder/"history.html").read_text(encoding="utf-8")
                self.assertLess(page.index("单独评测</td>"), page.index("选择发送方案</td>"))
                self.assertIn("policy-workflow.json", page)
                context.validate_runtime(json.loads((folder/"journal-environment.json").read_text(encoding="utf-8"))["report_rendering"])
            previous = (first/"policy-workflow.json").read_bytes()
            with self.assertRaises(ValueError):
                export_workflow(result, first)
            self.assertEqual((first/"policy-workflow.json").read_bytes(), previous)

    def test_cli_separate_processes_continue_one_file_and_keep_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"路径 with spaces"
            root.mkdir()
            origin = root/"original.json"
            origin.write_text(json.dumps(self.origin), encoding="utf-8")
            original_hash = hashlib.sha256(origin.read_bytes()).hexdigest()
            spec = root/"plan.json"
            spec.write_text(json.dumps(asdict(self.spec())), encoding="utf-8")
            outputs = [root/name for name in ("evaluation", "choice", "test", "redraw")]
            commands = [
                ["evaluate", "--policy", str(origin), "--seeds", "9001"],
                ["select", "--policy", str(outputs[0]/"policy-history.json"), "--spec", str(spec)],
                ["test", str(outputs[1]/"policy-workflow.json")],
                ["render", str(outputs[2]/"policy-workflow.json")],
            ]
            for command, output in zip(commands, outputs):
                result = subprocess.run([sys.executable, "-m", "event_control_lab.policy_journal", *command,
                                         "--out", str(output)], capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertTrue((output/"history.html").is_file())
            self.assertEqual(hashlib.sha256(origin.read_bytes()).hexdigest(), original_hash)
            saved = journal.history_for(json.loads((outputs[2]/"policy-history.json").read_text(encoding="utf-8")))
            self.assertEqual([item["phase"] for item in saved["events"]],
                             ["evaluation", "declared_development", "selection", "test"])
            self.assertEqual((outputs[2]/"policy-workflow.json").read_bytes(),
                             (outputs[3]/"policy-workflow.json").read_bytes())
            refused = subprocess.run([sys.executable, "-m", "event_control_lab.policy_journal", "evaluate",
                "--policy", str(outputs[2]/"policy-history.json"), "--seeds", "9001", "--out", str(root/"refused")],
                capture_output=True, timeout=30)
            self.assertEqual(refused.returncode, 2)
            self.assertFalse((root/"refused").exists())


if __name__ == "__main__":
    unittest.main()
