"""Reject an occupied output before spending work on a new experiment."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import __main__ as cli
from event_control_lab.engine import Config


class OutputPreflightTests(unittest.TestCase):
    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["sparsiloop", *arguments]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                cli.main()
                status = 0
            except SystemExit as exc:
                status = exc.code
        return status, stdout.getvalue(), stderr.getvalue()

    def inputs(self, root):
        config = asdict(Config(duration=0.2, budget=5, delay_steps=0, heartbeat=0.04,
                               loss_probability=0, measurement_noise=0, process_noise=0))
        files = {"compare": ("config", config),
                 "study": ("spec", {"config": config, "thresholds": [0.1], "seeds": [601]}),
                 "grid-check": ("spec", {"config": config, "time_steps": [0.02, 0.01]})}
        commands = []
        for command, (option, value) in files.items():
            path = root / (command + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            commands.append((command, [command, "--" + option, str(path)]))
        return commands

    def test_existing_outputs_are_preserved_without_starting_compute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for command, arguments in self.inputs(root):
                for kind in ("directory", "file"):
                    with self.subTest(command=command, kind=kind):
                        destination = root / (command + " occupied " + kind)
                        if kind == "directory":
                            destination.mkdir()
                            original = destination / "original report.json"
                        else:
                            original = destination
                        original.write_bytes(b'original results, including unknown: null\n')
                        before = original.read_bytes()
                        compute_name = {"grid-check": "grid_check"}.get(command, command)
                        with patch.object(cli, compute_name, wraps=getattr(cli, compute_name)) as compute:
                            status, _, error = self.invoke([*arguments, "--out", str(destination)])
                        self.assertEqual(status, 2, error)
                        self.assertEqual(original.read_bytes(), before)
                        compute.assert_not_called()
                        self.assertIn("choose a new --out", error)

    def test_new_output_still_exports_the_original_numerical_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for command, arguments in self.inputs(root):
                with self.subTest(command=command):
                    destination = root / (command + " new output")
                    compute_name = {"grid-check": "grid_check"}.get(command, command)
                    with patch.object(cli, compute_name, wraps=getattr(cli, compute_name)) as compute:
                        status, _, error = self.invoke([*arguments, "--out", str(destination)])
                    self.assertEqual(status, 0, error)
                    self.assertEqual(compute.call_count, 1)
                    result_file = {"compare": "result.json", "study": "study.json",
                                   "grid-check": "grid.json"}[command]
                    saved = json.loads((destination / result_file).read_text(encoding="utf-8"))
                    expected = getattr(cli, compute_name)(*compute.call_args.args, **compute.call_args.kwargs)
                    self.assertEqual(saved, json.loads(json.dumps(expected)))


if __name__ == "__main__":
    unittest.main()
