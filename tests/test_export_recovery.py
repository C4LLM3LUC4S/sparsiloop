"""Keep complete local records when report generation fails after computation."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import planned_context as context, policy, policy_journal as journal
from event_control_lab import planned_cli, policy_journal_cli
from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.planned_study import PlannedSpec
from event_control_lab.policy_journal_report import export_workflow


class ExportRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lab = ControllerLabSpec()
        config = replace(lab.config, duration=0.2, budget=10)
        trained = controller_lab(replace(lab, config=config, training_seeds=(101, 102),
                                         evaluation_seeds=(1001,)), "rl")
        spec = PlannedSpec(config=replace(config, initial_position=0.75, budget=5),
            absolute_thresholds=(2,), relative_thresholds=(), rmse_limit=100,
            selection_seeds=(3001,), test_seeds=(4001,), previously_used_seeds=(7001,))
        cls.choice = context.select_with_context(spec, policy_checkpoint=policy.checkpoint(trained))
        tested = context.test_with_context(cls.choice)
        cls.workflow = journal.evaluate_saved(tested["result"]["policy_after"], [9001])
        cls.nested = journal.select_plan(replace(spec, selection_seeds=(5001,), test_seeds=(6001,),
                                                previously_used_seeds=(8001,)), cls.workflow["history_after"])

    def test_late_workflow_failure_keeps_complete_record_for_zero_run_redraw(self):
        original = deepcopy(self.workflow)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "failed report"
            actual = Path.write_text

            def fail(path, *args, **kwargs):
                if path.name == "history.html":
                    raise OSError("injected late history write failure")
                return actual(path, *args, **kwargs)

            with patch.object(Path, "write_text", fail):
                with self.assertRaises(OSError) as error:
                    export_workflow(self.workflow, target)
            self.assertTrue(hasattr(error.exception, "record_path"), "No complete recovery record was reported")
            record = error.exception.record_path
            self.assertTrue(record.is_file())
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")), json.loads(json.dumps(original)))
            self.assertFalse(target.exists())
            output = root / "recovered report"
            with patch("event_control_lab.policy.compare") as evaluation, \
                    patch("event_control_lab.planned_study.simulate") as simulation, \
                    patch("event_control_lab.planned_policy.simulate") as frozen, \
                    patch("event_control_lab.planned_models.simulate") as custom, \
                    patch("event_control_lab.controllers.QTable.update") as training, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = policy_journal_cli.main(["render", str(record), "--out", str(output)])
            self.assertEqual(status, 0)
            evaluation.assert_not_called()
            simulation.assert_not_called()
            frozen.assert_not_called()
            custom.assert_not_called()
            training.assert_not_called()
            self.assertEqual(json.loads((output / "policy-workflow.json").read_text(encoding="utf-8")), original)
            self.assertEqual(self.workflow, original)
            self.assertEqual(list(root.glob("sparsiloop-recovery-*.json")), [record])

    def test_late_planned_failure_keeps_policy_context_and_reserved_seeds(self):
        original = deepcopy(self.choice)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "failed selection"
            from event_control_lab import planned_report
            actual = planned_report.write_json

            def fail(path, value):
                if path.name == "environment.json":
                    raise OSError("injected final environment write failure")
                return actual(path, value)

            with patch.object(planned_report, "write_json", fail):
                with self.assertRaises(OSError) as error:
                    context.export_bundle(self.choice, target)
            self.assertTrue(hasattr(error.exception, "record_path"), "No complete recovery record was reported")
            record = error.exception.record_path
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")), json.loads(json.dumps(original)))
            output = root / "recovered selection"
            with patch("event_control_lab.policy.compare") as evaluation, \
                    patch("event_control_lab.planned_study.simulate") as simulation, \
                    patch("event_control_lab.planned_policy.simulate") as frozen, \
                    patch("event_control_lab.planned_models.simulate") as custom, \
                    patch("event_control_lab.controllers.QTable.update") as training, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = planned_cli.main(["render", str(record), "--out", str(output)])
            self.assertEqual(status, 0)
            evaluation.assert_not_called()
            simulation.assert_not_called()
            frozen.assert_not_called()
            custom.assert_not_called()
            training.assert_not_called()
            self.assertEqual(json.loads((output / "selection-bundle.json").read_text(encoding="utf-8")), json.loads(json.dumps(original)))
            self.assertEqual(self.choice, original)

    def test_interrupted_cli_retains_a_complete_record_and_returns_130(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "original.json"
            source.write_text(json.dumps(self.workflow), encoding="utf-8")
            original = source.read_bytes()
            actual = Path.write_text

            def interrupt(path, *args, **kwargs):
                if path.name == "history.html":
                    raise KeyboardInterrupt()
                return actual(path, *args, **kwargs)

            error = io.StringIO()
            with patch.object(Path, "write_text", interrupt), redirect_stderr(error), \
                    redirect_stdout(io.StringIO()):
                status = policy_journal_cli.main(["render", str(source), "--out", str(root / "failed")])
            self.assertEqual(status, 130)
            self.assertNotIn("Traceback", error.getvalue())
            record = next(root.glob("sparsiloop-recovery-*.json"))
            self.assertIn(str(record), error.getvalue())
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")), self.workflow)
            self.assertEqual(source.read_bytes(), original)

    def test_failed_initial_record_write_does_not_claim_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "original.json"
            source.write_text(json.dumps(self.workflow), encoding="utf-8")
            original = source.read_bytes()
            error = io.StringIO()
            with patch("event_control_lab.export_recovery.os.fsync", side_effect=OSError("injected full disk")), \
                    redirect_stderr(error), redirect_stdout(io.StringIO()):
                status = policy_journal_cli.main(["render", str(source), "--out", str(root / "failed")])
            self.assertEqual(status, 2)
            self.assertNotIn("Full record retained", error.getvalue())
            self.assertEqual(list(root.glob("sparsiloop-recovery-*.json")), [])
            self.assertFalse((root / "failed").exists())
            self.assertEqual(source.read_bytes(), original)

    def test_successful_report_stays_successful_when_cache_cleanup_is_locked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = Path.unlink

            def fail(path, *args, **kwargs):
                if path.name.startswith("sparsiloop-recovery-"):
                    raise PermissionError("injected cleanup lock")
                return actual(path, *args, **kwargs)

            error = io.StringIO()
            with patch.object(Path, "unlink", fail), redirect_stderr(error):
                export_workflow(self.workflow, root / "complete")
            self.assertTrue((root / "complete/history.html").is_file())
            record = next(root.glob("sparsiloop-recovery-*.json"))
            self.assertIn(str(record), error.getvalue())
            self.assertEqual(json.loads(record.read_text(encoding="utf-8")), self.workflow)

    def test_nested_bundle_failure_keeps_the_full_workflow_not_a_temporary_inner_path(self):
        from event_control_lab import planned_report
        actual = planned_report.write_json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def fail(path, value):
                if path.name == "environment.json":
                    raise OSError("injected inner bundle write failure")
                return actual(path, value)

            with patch.object(planned_report, "write_json", fail):
                with self.assertRaises(OSError) as error:
                    export_workflow(self.nested, root / "failed")
            self.assertEqual(error.exception.record_path.parent, root)
            self.assertEqual(json.loads(error.exception.record_path.read_text(encoding="utf-8")), json.loads(json.dumps(self.nested)))
            self.assertEqual(error.exception.module, "event_control_lab.policy_journal")
            self.assertFalse((root / "failed").exists())

    def test_cleanup_advisory_cannot_turn_a_complete_report_into_failure(self):
        class BrokenErrorStream:
            def write(self, text):
                raise OSError("injected unavailable diagnostic stream")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = Path.unlink

            def fail(path, *args, **kwargs):
                if path.name.startswith("sparsiloop-recovery-"):
                    raise PermissionError("injected cleanup lock")
                return actual(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail), redirect_stderr(BrokenErrorStream()):
                export_workflow(self.workflow, root / "complete")
            self.assertTrue((root / "complete/history.html").is_file())
            self.assertEqual(json.loads(next(root.glob("sparsiloop-recovery-*.json")).read_text(encoding="utf-8")), self.workflow)

    def test_web_temporary_export_does_not_advertise_a_local_recovery_file(self):
        from event_control_lab import export_recovery, web_journal
        actual = Path.write_text

        def fail(path, *args, **kwargs):
            if path.name == "history.html":
                raise OSError("injected temporary web export failure")
            return actual(path, *args, **kwargs)

        with patch.object(Path, "write_text", fail), \
                patch.object(export_recovery.tempfile, "mkstemp", wraps=export_recovery.tempfile.mkstemp) as cache:
            with self.assertRaises(OSError) as error:
                web_journal.pack(self.workflow)
        self.assertFalse(hasattr(error.exception, "record_path"))
        cache.assert_not_called()

    def test_printed_command_uses_current_python_and_handles_quoted_paths(self):
        actual = Path.write_text
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "user's reports with spaces"
            root.mkdir()

            def fail(path, *args, **kwargs):
                if path.name == "history.html":
                    raise OSError("injected final write failure")
                return actual(path, *args, **kwargs)

            with patch.object(Path, "write_text", fail):
                with self.assertRaises(OSError) as error:
                    export_workflow(self.workflow, root / "failed")
            recovered = error.exception
            if os.name == "nt":
                shell = shutil.which("powershell.exe")
                if shell is None:
                    self.skipTest("PowerShell is unavailable for the printed-command check")
                command = [shell, "-NoProfile", "-NonInteractive", "-Command", recovered.command]
            else:
                command = ["/bin/sh", "-c", recovered.command]
            process = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads((recovered.redraw_output / "policy-workflow.json").read_text(encoding="utf-8")), self.workflow)


if __name__ == "__main__":
    unittest.main()
