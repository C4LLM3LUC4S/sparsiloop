"""Recover a planned history at the standalone boundary without losing known seeds."""

import base64
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.controllers import initial_position
from event_control_lab import planned_context, policy
from event_control_lab.planned_study import PlannedSpec
from event_control_lab.policy_files import load_standalone_checkpoint
from event_control_lab.web_recipes import test_saved_policy as web_test
import test_server


class PolicyFileRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lab = ControllerLabSpec()
        config = replace(lab.config, duration=0.2, budget=10)
        trained = controller_lab(replace(lab, config=config, training_seeds=(101, 102),
                                         evaluation_seeds=(1001,)), "rl")
        spec = PlannedSpec(config=replace(config, initial_position=0.75, budget=5),
                           absolute_thresholds=(2,), relative_thresholds=(), rmse_limit=100,
                           selection_seeds=(3001,), test_seeds=(4001,), previously_used_seeds=(7001,))
        cls.choice = planned_context.select_with_context(spec, policy_checkpoint=policy.checkpoint(trained))
        cls.tested = planned_context.test_with_context(cls.choice)
        cls.history = cls.tested["result"]["policy_after"]
        cls.saved = cls.history["checkpoint"]

    def test_history_is_identified_before_any_standalone_evaluation(self):
        original = deepcopy(self.history)
        with patch("event_control_lab.web_recipes.evaluate_policy") as evaluation:
            with self.assertRaisesRegex(ValueError, "完整报告 ZIP") as refused:
                web_test({"checkpoint": self.history, "seeds": [9001]})
        evaluation.assert_not_called()
        self.assertIn("policy-history.json", str(refused.exception))
        self.assertIn("初态", str(refused.exception))
        self.assertEqual(self.history, original)
        damaged = deepcopy(self.history)
        damaged["planned_history"] = []
        with self.assertRaisesRegex(ValueError, "摘要"):
            load_standalone_checkpoint(damaged)

    def test_compatible_checkpoint_keeps_all_known_seed_categories(self):
        original = deepcopy(self.history)
        with patch("event_control_lab.policy.compare") as simulate:
            for seed in (101, 1001, 7001, 3001, 4001):
                with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, "new seeds"):
                    web_test({"checkpoint": self.saved, "seeds": [seed]})
        simulate.assert_not_called()
        self.assertEqual(self.history, original)
        self.assertEqual(self.saved["table_sha256"], self.history["checkpoint"]["table_sha256"])

    def test_cli_refusal_then_new_file_recovery_preserves_originals_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "policy-history.json"
            compatible = root / "policy-checkpoint.json"
            history.write_text(json.dumps(self.history), encoding="utf-8")
            compatible.write_text(json.dumps(self.saved), encoding="utf-8")
            originals = [history.read_bytes(), compatible.read_bytes()]
            output = root / "new test"
            command = [sys.executable, "-m", "event_control_lab", "evaluate-policy", str(history),
                       "--seeds", "9001", "--out", str(output)]
            refused = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(refused.returncode, 2)
            self.assertIn("policy-checkpoint.json", refused.stderr.decode("utf-8"))
            self.assertFalse(output.exists())
            command[4] = str(compatible)
            recovered = subprocess.run(command, capture_output=True, timeout=30)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            result = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
            expected = policy.evaluate_policy(self.saved, [9001])
            self.assertEqual(result["cases"], json.loads(json.dumps(expected["cases"])))
            self.assertEqual(result["cases"][0]["policy"]["config"]["initial_position"], initial_position(9001))
            self.assertEqual(len(result["cases"][0]["policy"]["runs"]), 3)
            continued = json.loads((output / "policy-checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(continued["previous_evaluation_seeds"], self.saved["previous_evaluation_seeds"] + [9001])
            self.assertEqual(continued["table"], self.saved["table"])
            self.assertEqual([history.read_bytes(), compatible.read_bytes()], originals)


class PolicyFileHTTPRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_server.ServerTests.setUpClass.__func__(cls)
        PolicyFileRecoveryTests.setUpClass()
        cls.history = PolicyFileRecoveryTests.history

    tearDownClass = classmethod(test_server.ServerTests.tearDownClass.__func__)
    request = test_server.ServerTests.request

    def test_http_refusal_and_recovery_match_the_existing_evaluator(self):
        before = deepcopy(self.history)
        with patch("event_control_lab.web_recipes.evaluate_policy") as evaluation:
            status, _, body = self.request("POST", "/api/evaluate-policy",
                json.dumps({"checkpoint": self.history, "seeds": [9001]}))
        self.assertEqual(status, 400)
        self.assertIn("完整报告 ZIP", json.loads(body)["error"])
        evaluation.assert_not_called()
        with patch("event_control_lab.controllers.QTable.update", side_effect=AssertionError("must not train")):
            status, _, body = self.request("POST", "/api/evaluate-policy",
                json.dumps({"checkpoint": self.history["checkpoint"], "seeds": [9001]}))
        self.assertEqual(status, 200, body[:300])
        response = json.loads(body)
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(response["archive_base64"]))) as archive:
            self.assertIsNone(archive.testzip())
            result = json.loads(archive.read("evaluation.json"))
            self.assertEqual(result, json.loads(json.dumps(policy.evaluate_policy(self.history["checkpoint"], [9001]))))
            self.assertEqual(json.loads(archive.read("policy-checkpoint.json")), response["checkpoint"])
        self.assertEqual(len(response["rows"]), 6)
        self.assertEqual(response["checkpoint"]["previous_evaluation_seeds"],
                         self.history["checkpoint"]["previous_evaluation_seeds"] + [9001])
        self.assertEqual(self.history, before)


if __name__ == "__main__":
    unittest.main()
