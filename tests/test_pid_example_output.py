"""The optional PID source command must reject unusable outputs before work."""

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

from event_control_lab import Config
from examples import simple_pid_case as example


class PIDExampleOutputTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["simple_pid_case", *arguments]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                example.main()
            except SystemExit as exc:
                status = exc.code
            else:
                status = 0
        return status, stdout.getvalue(), stderr.getvalue()

    def test_bad_outputs_reject_before_config_or_pid_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            blocker = root / "keep this file"
            blocker.write_bytes(b"Original file\n")
            occupied = root / "old report"
            occupied.mkdir()
            report = occupied / "report.html"
            report.write_bytes(b"Original report\n")
            outputs = (occupied, blocker, blocker / "new", blocker / "nested" / "new",
                       blocker / ".." / "normalized-result")
            for output in outputs:
                with self.subTest(output=str(output)), ExitStack() as stack:
                    read = stack.enter_context(patch.object(Path, "read_text",
                                               side_effect=AssertionError("No input read")))
                    run = stack.enter_context(patch.object(example, "run_case",
                                              side_effect=AssertionError("No PID comparison")))
                    status, stdout, stderr = self.invoke(
                        ["--config", str(root / "missing.json"), "--out", str(output)])
                    self.assertEqual(status, 2)
                    self.assertEqual(stdout, "")
                    self.assertIn("这次没有开始计算", stderr)
                    read.assert_not_called()
                    run.assert_not_called()
            self.assertEqual(blocker.read_bytes(), b"Original file\n")
            self.assertEqual(report.read_bytes(), b"Original report\n")
            self.assertFalse((root / "normalized-result").exists())

    def test_valid_retry_passes_original_config_gains_and_output(self):
        config = Config(duration=0.2, dt=0.1, budget=2, heartbeat=0.2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = root / "original config.json"
            original.write_text(json.dumps(asdict(config)), encoding="utf-8")
            before = original.read_bytes()
            destination = root / "new report"
            with patch.object(example, "run_case", return_value=({"runs": []}, {"version": "2.0.1"})) as run, \
                    patch.object(example, "load_pid", side_effect=AssertionError("No optional install")) as load:
                status, stdout, stderr = self.invoke(
                    ["--config", str(original), "--out", str(destination), "--ki", "0.2", "--kd", "0.04"])
                self.assertEqual(status, 0, stderr)
                run.assert_called_once_with(config, destination, 0.2, 0.04)
                load.assert_not_called()
            self.assertEqual(json.loads(stdout)["output"], str(destination))
            self.assertEqual(original.read_bytes(), before)
            self.assertFalse(destination.exists())

    def test_documented_command_reports_bad_parent_before_missing_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            blocker = root / "original file"
            blocker.write_bytes(b"Keep original\n")
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-m", "examples.simple_pid_case",
                 "--config", str(root / "missing.json"), "--out", str(blocker / "result")],
                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn("不是文件夹", result.stderr)
            self.assertNotIn("missing.json", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(blocker.read_bytes(), b"Keep original\n")

    def test_missing_optional_library_keeps_the_pinned_install_route(self):
        with patch.object(example.metadata, "version",
                          side_effect=example.metadata.PackageNotFoundError("simple-pid")):
            with self.assertRaisesRegex(ValueError, "python -m pip install -r examples/requirements-simple-pid.txt"):
                example.load_pid()
        requirements = Path(example.__file__).with_name("requirements-simple-pid.txt").read_text(encoding="utf-8")
        self.assertIn("simple-pid==2.0.1", requirements)
        self.assertIn("--hash=sha256:", requirements)


if __name__ == "__main__":
    unittest.main()
