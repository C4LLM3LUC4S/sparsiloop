"""Model example output failures must precede input and model work."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config
from event_control_lab.planned_study import PlannedSpec
from examples import planned_model_case as example


class PlannedModelOutputTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = example.main(arguments)
        return result, stdout.getvalue(), stderr.getvalue()

    def commands(self, input_path, output):
        for stage, arguments in (
                ("select", ["select", "--spec", str(input_path)]),
                ("test", ["test", str(input_path), "--decay", "0.4", "--gain", "1.2"])):
            yield stage, arguments + ["--out", str(output)]

    def test_invalid_outputs_reject_before_reading_or_constructing_a_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            blocker = root / "keep this file"
            blocker.write_bytes(b"Original file remains unchanged\n")
            occupied = root / "old report"
            occupied.mkdir()
            original = occupied / "report.html"
            original.write_bytes(b"Original report\n")
            paths = (occupied, blocker / "new", blocker / "nested" / "new",
                     blocker / ".." / "normalized-result")
            for output in paths:
                for stage, args in self.commands(root / "missing input.json", output):
                    with self.subTest(stage=stage, output=str(output)), ExitStack() as stack:
                        calls = [stack.enter_context(patch.object(example, name,
                                 side_effect=AssertionError("Rejected before " + name)))
                                 for name in ("read_json", "actuator_model", "select_with_context",
                                              "test_with_context", "export_bundle")]
                        status, stdout, stderr = self.invoke(args)
                        self.assertEqual(status, 2)
                        self.assertEqual(stdout, "")
                        self.assertIn("这次没有开始计算", stderr)
                        for call in calls:
                            call.assert_not_called()
            self.assertEqual(blocker.read_bytes(), b"Original file remains unchanged\n")
            self.assertEqual(original.read_bytes(), b"Original report\n")
            self.assertFalse((root / "normalized-result").exists())

    def test_valid_retry_preserves_stage_input_model_parameters_and_export(self):
        spec = PlannedSpec(Config(duration=0.2, budget=2, heartbeat=0.2),
                           absolute_thresholds=(0.1,), relative_thresholds=(0.1,),
                           selection_seeds=(7101,), test_seeds=(7201,), rmse_limit=1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for stage, arguments in self.commands(root / "original record.json", root / "new report"):
                value = asdict(spec) if stage == "select" else {"original": "complete-record-placeholder"}
                saved = {"result": {"status": "met_declared_tests"}}
                with self.subTest(stage=stage), \
                        patch.object(example, "read_json", return_value=(value, "original-file-digest")) as read, \
                        patch.object(example, "select_with_context", return_value=saved) as select, \
                        patch.object(example, "test_with_context", return_value=saved) as test, \
                        patch.object(example, "export_bundle") as export:
                    status, _, stderr = self.invoke(arguments)
                    self.assertEqual(status, 0, stderr)
                    read.assert_called_once_with(str(root / "original record.json"))
                    operation, inactive = (select, test) if stage == "select" else (test, select)
                    inactive.assert_not_called()
                    self.assertEqual(operation.call_args.args, (spec if stage == "select" else value,))
                    self.assertEqual(operation.call_args.kwargs["plant"].parameters["input_gain_per_second"], 1.2)
                    export.assert_called_once_with(saved, root / "new report", "original-file-digest")
                    self.assertFalse((root / "new report").exists())

    def test_documented_commands_report_bad_parent_before_missing_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            blocker = root / "blocker"
            blocker.write_bytes(b"Keep original\n")
            for stage, arguments in self.commands(root / "not-there.json", blocker / "result"):
                with self.subTest(stage=stage):
                    result = subprocess.run([sys.executable, "-X", "utf8", "-m", "examples.planned_model_case", *arguments],
                                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                            encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("不是文件夹", result.stderr)
                    self.assertNotIn("not-there.json", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stdout, "")
            self.assertEqual(blocker.read_bytes(), b"Keep original\n")


if __name__ == "__main__":
    unittest.main()
