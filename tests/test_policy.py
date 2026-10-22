from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab, export_controller_lab
from event_control_lab.controllers import QController, QTable
from event_control_lab.policy import checkpoint, checkpoint_digest, evaluate_policy, export_evaluation, load_checkpoint


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = ControllerLabSpec()
        cls.spec = replace(spec, config=replace(spec.config, duration=0.2, budget=10),
                           training_seeds=(101, 102), evaluation_seeds=(1001,))
        cls.result = controller_lab(cls.spec, "rl")
        cls.saved = checkpoint(cls.result)

    def test_same_step_count_with_different_clock_is_rejected(self):
        config = replace(self.spec.config, duration=0.4, dt=0.04)
        self.assertEqual(config.steps, self.spec.config.steps)
        # The low-level table alone has no physical-clock metadata.
        QController(config, QTable.from_snapshot(self.saved["table"]))
        with self.assertRaisesRegex(ValueError, "trained dt"):
            evaluate_policy(self.saved, [2001], config)

    def test_fresh_evaluation_is_frozen_and_matches_direct_inference(self):
        before = deepcopy(self.saved)
        with patch("event_control_lab.controllers.QTable.update", side_effect=AssertionError("must not train")):
            result = evaluate_policy(self.saved, [2001, 2002])
        self.assertEqual(self.saved, before)
        self.assertEqual(result["frozen_before_sha256"], result["frozen_after_sha256"])
        self.assertEqual(result["evaluation_seeds"], [2001, 2002])
        for case in result["cases"]:
            config = case["policy"]["config"]
            self.assertEqual(case["policy"]["exogenous_trace_sha256"], case["linear_feedback"]["exogenous_trace_sha256"])
            self.assertEqual(config, case["linear_feedback"]["config"])
            self.assertEqual(len(case["policy"]["runs"]), 3)

    def test_training_old_test_duplicate_and_invalid_seeds_rejected(self):
        for seeds in ([101], [1001], [2001, 2001], [True], [], [-1]):
            with self.subTest(seeds=seeds), self.assertRaises(ValueError):
                evaluate_policy(self.saved, seeds)

    def test_damage_missing_metadata_or_source_drift_rejected(self):
        for field, value in (("table_sha256", "wrong"), ("source_sha256", {}),
                             ("training_statuses", [{}]), ("selection", float("nan"))):
            bad = deepcopy(self.saved)
            bad[field] = value
            if field != "selection":
                bad["checkpoint_sha256"] = checkpoint_digest(bad)
            with self.subTest(field=field), self.assertRaises(ValueError):
                load_checkpoint(bad)
        with self.assertRaisesRegex(ValueError, "policy-checkpoint.json"):
            load_checkpoint(self.saved["table"])

    def test_report_only_change_does_not_change_policy_context(self):
        result = deepcopy(self.result)
        result["source_sha256"]["controller_lab"] = "different report layout"
        saved = checkpoint(result)
        load_checkpoint(saved)
        with patch("event_control_lab.policy.source_identity", return_value={}):
            with self.assertRaisesRegex(ValueError, "source differs"):
                load_checkpoint(saved)

    def test_browser_json_integer_spelling_keeps_numeric_identity(self):
        def browser_numbers(value):
            if isinstance(value, dict):
                return {key: browser_numbers(item) for key, item in value.items()}
            if isinstance(value, list):
                return [browser_numbers(item) for item in value]
            return int(value) if type(value) is float and value.is_integer() else value
        value = browser_numbers(self.saved)
        table, _, _ = load_checkpoint(value)
        self.assertEqual(table.fingerprint(), self.saved["table_sha256"])
        self.assertEqual(checkpoint_digest(value), self.saved["checkpoint_sha256"])
        changed = deepcopy(value)
        changed["training_config"]["dt"] = 0.04
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_checkpoint(changed)

    def test_input_limit_and_work_budget_are_checked_before_running(self):
        with self.assertRaisesRegex(ValueError, "input_limit"):
            evaluate_policy(self.saved, [2001], replace(self.spec.config, input_limit=2))
        large = deepcopy(self.saved)
        c = replace(self.spec.config, duration=2, dt=0.002, budget=1000)
        large["training_config"] = large["evaluation_config"] = c.__dict__
        table = QTable(c.steps, c.input_limit)
        large["table"], large["table_sha256"] = table.snapshot(), table.fingerprint()
        large["checkpoint_sha256"] = checkpoint_digest(large)
        with patch("event_control_lab.policy.compare", side_effect=AssertionError("too late")):
            with self.assertRaisesRegex(ValueError, "100000"):
                evaluate_policy(large, list(range(2001, 2020)))

    def test_export_and_new_process_cli_preserve_checkpoint_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            training = root / "training"
            export_controller_lab(self.result, training)
            source = training / "policy-checkpoint.json"
            original = source.read_bytes()
            out = root / "new 评测"
            command = [sys.executable, "-m", "event_control_lab", "evaluate-policy", str(source),
                       "--seeds", "2001,2002", "--out", str(out)]
            environment = dict(os.environ, PYTHONIOENCODING="ascii")
            process = subprocess.run(command, capture_output=True, timeout=30, env=environment)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn(str((out / "report.html").resolve()), process.stdout.decode("utf-8"))
            result = json.loads((out / "evaluation.json").read_text(encoding="utf-8"))
            self.assertEqual(result["checkpoint_file_sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(source.read_bytes(), original)
            page = (out / "report.html").read_text(encoding="utf-8")
            self.assertIn("这次没有重新训练", page)
            self.assertNotIn("训练过程</td>", page)
            self.assertNotIn("未训练的策略</td>", page)
            continued = json.loads((out / "policy-checkpoint.json").read_text(encoding="utf-8"))
            load_checkpoint(continued)
            self.assertEqual(continued["previous_evaluation_seeds"], [1001, 2001, 2002])
            with self.assertRaisesRegex(ValueError, "new seeds"):
                evaluate_policy(continued, [2001])
            previous = (out / "evaluation.json").read_bytes()
            refused = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(refused.returncode, 2)
            self.assertEqual((out / "evaluation.json").read_bytes(), previous)

    def test_failures_keep_null_metrics_and_do_not_become_zero(self):
        base = replace(self.spec.config, budget=0, state_limit=1)
        result = evaluate_policy(self.saved, [2006, 2018], base)
        self.assertTrue(any(run["metrics"]["position_rmse"] is None
                            for case in result["cases"] for run in case["policy"]["runs"]))
        with tempfile.TemporaryDirectory() as tmp:
            export_evaluation(result, Path(tmp) / "out")


if __name__ == "__main__":
    unittest.main()
