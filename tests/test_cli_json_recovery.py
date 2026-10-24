"""Reject unreadable JSON before any experiment and explain how to recover."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import __main__ as cli, planned_cli, policy_journal_cli
from event_control_lab.engine import Config


COMPUTE = ("event_control_lab.controllers.QTable.update", "event_control_lab.policy.compare",
           "event_control_lab.engine.simulate", "event_control_lab.planned_study.simulate",
           "event_control_lab.planned_policy.simulate", "event_control_lab.planned_models.simulate")


class JsonInputRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        path = root / "original deeply nested.json"
        path.write_text("[" * 10000 + "0" + "]" * 10000 + "\n", encoding="utf-8")
        return path

    def invoke(self, function, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["sparsiloop", *arguments]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                status = function()
            except SystemExit as exc:
                status = exc.code
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_guidance(self, error):
        self.assertIn("保留原文件", error)
        self.assertIn("重新导出", error)
        self.assertIn("完整", error)
        self.assertIn("Keep the original", error)
        self.assertIn("re-export", error)
        self.assertIn("Original error: RecursionError:", error)
        self.assertNotIn("Traceback", error)

    def test_standalone_rejects_real_deep_json_before_training_or_simulation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.fixture(root)
            before = original.read_bytes()
            previous = root / "earlier report.json"
            previous.write_bytes(b'{"status":"old","unknown":null}\n')
            target = root / "new output"
            with ExitStack() as stack:
                computes = [stack.enter_context(patch(name)) for name in COMPUTE]
                status, _, error = self.invoke(cli.main, ["evaluate-policy", str(original),
                    "--seeds", "9001", "--out", str(target)])
            self.assertEqual(status, 2, error)
            self.assert_guidance(error)
            self.assertIn(str(original), error)
            self.assertFalse(target.exists())
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(previous.read_bytes(), b'{"status":"old","unknown":null}\n')
            for compute in computes:
                compute.assert_not_called()

    def test_planned_and_history_reject_same_file_with_matching_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.fixture(root)
            before = original.read_bytes()
            for name, function in (("planned", planned_cli.main), ("history", policy_journal_cli.main)):
                with self.subTest(entry=name), ExitStack() as stack:
                    computes = [stack.enter_context(patch(target)) for target in COMPUTE]
                    target = root / name
                    status, _, error = self.invoke(function, ["render", str(original), "--out", str(target)])
                    self.assertEqual(status, 2, error)
                    self.assert_guidance(error)
                    self.assertIn(str(original), error)
                    self.assertFalse(target.exists())
                    self.assertEqual(original.read_bytes(), before)
                    for compute in computes:
                        compute.assert_not_called()

    def test_separate_process_returns_two_without_traceback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.fixture(root)
            target = root / "new report"
            # Use the package that this test actually imported, also for an installed-wheel check.
            command = [sys.executable, "-X", "utf8", "-I", "-c",
                "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
                "runpy.run_module('event_control_lab',run_name='__main__')",
                str(Path(cli.__file__).resolve().parents[1]), "evaluate-policy", str(original),
                "--seeds", "9001", "--out", str(target)]
            result = subprocess.run(command, cwd=root, capture_output=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assert_guidance(result.stderr)
            self.assertIn(str(original), result.stderr)
            self.assertFalse(target.exists())

    def test_compute_recursion_after_valid_input_does_not_blame_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = asdict(Config(duration=0.2, budget=5, delay_steps=0, heartbeat=0.04))
            cases = (("compare", cli.main, cli, "compare", config, ["compare", "--config"]),
                     ("planned", planned_cli.main, planned_cli, "select_with_context",
                      {"config": config, "absolute_thresholds": [], "relative_thresholds": [],
                       "selection_seeds": [3001], "test_seeds": [4001], "rmse_limit": 0.3},
                      ["select", "--spec"]))
            for name, function, module, computation, value, prefix in cases:
                with self.subTest(entry=name):
                    original = root / (name + " valid.json")
                    original.write_text(json.dumps(value), encoding="utf-8")
                    before = original.read_bytes()
                    target = root / name
                    with patch.object(module, computation, side_effect=RecursionError("controlled compute failure")) as run:
                        status, _, error = self.invoke(function, [*prefix, str(original), "--out", str(target)])
                    self.assertEqual(status, 2, error)
                    run.assert_called_once()
                    self.assertIn("controlled compute failure", error)
                    self.assertNotIn("JSON", error)
                    self.assertNotIn("重新导出", error)
                    self.assertNotIn("re-export", error)
                    self.assertNotIn("Traceback", error)
                    self.assertFalse(target.exists())
                    self.assertEqual(original.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
