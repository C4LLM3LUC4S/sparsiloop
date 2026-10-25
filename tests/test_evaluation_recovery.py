"""Local recovery of an original saved alpha3 teaching evaluation; no new runs."""

import base64
from contextlib import contextmanager, ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from event_control_lab import evaluation_report as report, export_recovery, policy, web_recipes
from event_control_lab.engine import Config, simulate


# Original developer teaching result retained from public alpha3 task acceptance.
# Compression keeps this complete fixture self-contained; it includes no private data.
ORIGINAL_SHA256 = "fffd8268217bb8ff60d057b00f41a1a4b333f340d6369225b14c8b9943d500a0"
A3_EVALUATION = (
    "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"
)
NO_COMPUTE = ("event_control_lab.policy.evaluate_policy", "event_control_lab.policy.compare",
              "event_control_lab.engine.simulate", "event_control_lab.planned_study.simulate",
              "event_control_lab.planned_policy.simulate", "event_control_lab.planned_models.simulate",
              "event_control_lab.controllers.QTable.update")


class EvaluationRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = zlib.decompress(base64.b64decode(A3_EVALUATION))
        assert hashlib.sha256(cls.original).hexdigest() == ORIGINAL_SHA256
        cls.saved = json.loads(cls.original)

    @contextmanager
    def no_compute(self):
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError("Recovery must not run a policy")))
                     for name in NO_COMPUTE]
            yield
            for mock in mocks:
                mock.assert_not_called()

    def late_failure(self, value, target, exception):
        actual = Path.write_text
        failure_target = (target / "policy-checkpoint.json").resolve()
        hits = []

        def fail(path, *args, **kwargs):
            if path.resolve() == failure_target:
                hits.append(path)
                raise exception
            return actual(path, *args, **kwargs)

        with patch.object(Path, "write_text", fail), self.no_compute():
            with self.assertRaises(export_recovery.ExportRecoveryError) as failed:
                report.export_evaluation(value, target)
        self.assertEqual(len(hits), 1, "The intended late write must be hit exactly once")
        return failed.exception

    def assert_outputs(self, value, output):
        self.assertEqual(json.loads((output / "evaluation.json").read_text(encoding="utf-8")), value)
        saved = json.loads((output / "policy-checkpoint.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["table"], value["checkpoint"]["table"])
        self.assertEqual(saved["training_seeds"], value["checkpoint"]["training_seeds"])
        self.assertEqual(saved["previous_evaluation_seeds"],
                         value["checkpoint"]["previous_evaluation_seeds"] + value["evaluation_seeds"])
        policy.load_checkpoint(saved)
        for name in ("report.html", "summary.csv", "trajectories.csv", "controllers.json", "policy.json"):
            self.assertTrue((output / name).is_file(), name)

    def test_old_full_record_roundtrip_uses_its_own_reader_without_old_byte_caps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = root / "original evaluation.json"
            original.write_bytes(self.original)
            with self.no_compute(), \
                    patch("event_control_lab.policy.read_checkpoint", side_effect=AssertionError("Wrong reader")), \
                    patch("event_control_lab.planned_study.read_json", side_effect=AssertionError("Wrong cap")):
                self.assertEqual(report.read_evaluation(original), self.saved)
                report.export_evaluation(self.saved, root / "redrawn")
                report.export_policy_evaluation(self.saved, root / "legacy")
            self.assert_outputs(self.saved, root / "redrawn")
            page = (root / "redrawn/report.html").read_text(encoding="utf-8")
            self.assertIn('id="saved-result-next-steps"', page)
            self.assertIn('evaluation_report render "PATH/evaluation.json"', page)
            self.assertIn('href="policy-checkpoint.json"', page)
            self.assertNotIn("当前 MFAC、ILC 要求", page)
            for source in (root / "legacy").iterdir():
                if source.name != "report.html":
                    self.assertEqual(source.read_bytes(), (root / "redrawn" / source.name).read_bytes())
            self.assertEqual(original.read_bytes(), self.original)
            self.assertEqual(list(root.glob("sparsiloop-recovery-*.json")), [])

    def test_final_report_guidance_write_failure_keeps_complete_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "partial"
            original_write = Path.write_text
            writes = []

            def fail_last_page(path, *args, **kwargs):
                if path == target / "report.html":
                    writes.append(path)
                    if len(writes) == 2:
                        raise OSError("injected final report guidance failure")
                return original_write(path, *args, **kwargs)

            with self.no_compute(), patch.object(Path, "write_text", new=fail_last_page):
                with self.assertRaises(export_recovery.ExportRecoveryError) as failed:
                    report.export_evaluation(self.saved, target)
            self.assertEqual(len(writes), 2)
            self.assertEqual(report.read_evaluation(failed.exception.record_path), self.saved)
            self.assertEqual(json.loads((target / "evaluation.json").read_text(encoding="utf-8")), self.saved)
            with self.no_compute():
                report.export_evaluation(self.saved, root / "recovered")
            self.assert_outputs(self.saved, root / "recovered")

    def test_late_failure_retains_complete_result_and_redraw_preserves_failed_nulls(self):
        value = deepcopy(self.saved)
        # A deliberate failure-state fixture tests preservation, not a new simulated outcome.
        run = value["cases"][0]["policy"]["runs"][0]
        run.update(status="state_limit", error="test-only retained failure state")
        run["metrics"].update(position_rmse=None, quadratic_cost=None)
        value["checkpoint_file_sha256"] = "a" * 64
        before = deepcopy(value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = root / "original evaluation.json"
            original.write_text(json.dumps(value), encoding="utf-8")
            original_bytes = original.read_bytes()
            old = root / "earlier report.html"
            old.write_bytes(b"Retain the earlier completed report\n")
            error = self.late_failure(value, root / "partial", OSError("injected late checkpoint write"))
            self.assertEqual(report.read_evaluation(error.record_path), before)
            self.assertIn(str(error.record_path), str(error))
            self.assertEqual(error.module, "event_control_lab.evaluation_report")
            self.assertTrue((root / "partial/report.html").exists())
            self.assertFalse((root / "partial/evaluation.json").exists())
            with self.no_compute(), redirect_stdout(io.StringIO()):
                self.assertEqual(report.main(["render", str(error.record_path), "--out", str(root / "recovered")]), 0)
            self.assert_outputs(before, root / "recovered")
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(old.read_bytes(), b"Retain the earlier completed report\n")
            self.assertEqual(value, before)
            self.assertEqual(json.loads(error.record_path.read_text(encoding="utf-8")), before)

    def test_printed_same_interpreter_command_handles_spaces_and_apostrophe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "user's reports with spaces"
            root.mkdir()
            root = root.resolve()
            error = self.late_failure(self.saved, root / "partial", OSError("injected checkpoint fault"))
            self.assertIn(sys.executable.replace("'", "''") if os.name == "nt" else sys.executable, error.command)
            self.assertEqual(" -I " in error.command, bool(sys.flags.isolated))
            if os.name == "nt":
                shell = shutil.which("powershell.exe")
                if shell is None:
                    self.skipTest("PowerShell is not available to execute its printed syntax")
                command = [shell, "-NoProfile", "-NonInteractive", "-Command", error.command]
            else:
                command = ["/bin/sh", "-c", error.command]
            # The literal printed command is exercised separately from the guarded in-process redraw.
            process = subprocess.run(command, cwd=Path(report.__file__).resolve().parents[1],
                                     capture_output=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assert_outputs(self.saved, error.redraw_output)
            self.assertEqual(report.read_evaluation(error.record_path), self.saved)

    def test_initial_copy_or_readback_failure_never_claims_a_retained_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            cases = (("write", "event_control_lab.export_recovery.os.fsync"),
                     ("readback", "event_control_lab.evaluation_report.read_evaluation"))
            for name, target in cases:
                with self.subTest(stage=name), self.no_compute(), \
                        patch(target, side_effect=OSError("injected initial " + name)), \
                        redirect_stderr(io.StringIO()) as error:
                    with self.assertRaises(OSError) as failed:
                        report.export_evaluation(self.saved, root / name)
                    self.assertNotIsInstance(failed.exception, export_recovery.ExportRecoveryError)
                    self.assertNotIn("Full record retained", error.getvalue())
                    self.assertFalse((root / name).exists())
                    self.assertEqual(list(root.glob("sparsiloop-recovery-*.json")), [])

    def test_interrupted_render_returns_130_with_actual_complete_recovery_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original = root / "evaluation.json"
            original.write_bytes(self.original)
            actual = Path.write_text

            def interrupt(path, *args, **kwargs):
                if path.name == "policy-checkpoint.json":
                    raise KeyboardInterrupt()
                return actual(path, *args, **kwargs)

            with patch.object(Path, "write_text", interrupt), self.no_compute(), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
                status = report.main(["render", str(original), "--out", str(root / "interrupted")])
            self.assertEqual(status, 130)
            self.assertNotIn("Traceback", error.getvalue())
            recovery = next(root.glob("sparsiloop-recovery-*.json"))
            retained_line = next(line for line in error.getvalue().splitlines() if "完整计算记录已保留：" in line)
            reported = Path(retained_line.partition("完整计算记录已保留：")[2])
            self.assertTrue(reported.is_file())
            self.assertEqual(reported.resolve(), recovery.resolve())
            self.assertEqual(report.read_evaluation(recovery), self.saved)
            self.assertEqual(original.read_bytes(), self.original)

    def test_complete_report_stays_successful_if_cache_cleanup_is_locked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            actual = Path.unlink

            def locked(path, *args, **kwargs):
                if path.name.startswith("sparsiloop-recovery-"):
                    raise PermissionError("injected cleanup lock")
                return actual(path, *args, **kwargs)

            with patch.object(Path, "unlink", locked), self.no_compute(), redirect_stderr(io.StringIO()) as error:
                report.export_evaluation(self.saved, root / "complete")
            self.assert_outputs(self.saved, root / "complete")
            retained = next(root.glob("sparsiloop-recovery-*.json"))
            retained_line = next(line for line in error.getvalue().splitlines() if "备用记录也保留在 " in line)
            reported = Path(retained_line.partition("备用记录也保留在 ")[2].partition("。 /")[0])
            self.assertTrue(reported.is_file())
            self.assertEqual(reported.resolve(), retained.resolve())
            self.assertEqual(report.read_evaluation(retained), self.saved)

    def test_incomplete_comparison_or_mismatched_source_rejects_before_output(self):
        variants = []
        missing = deepcopy(self.saved)
        del missing["cases"][0]["policy"]["exogenous_trace"]
        variants.append(("missing trace", missing))
        drift = deepcopy(self.saved)
        drift["cases"][0]["policy"]["engine_source_sha256"] = "0" * 64
        variants.append(("comparison source", drift))
        invalid = deepcopy(self.saved)
        invalid["cases"][0]["policy"]["runs"][0]["metrics"]["position_rmse"] = None
        variants.append(("complete with unknown score", invalid))
        shortened = deepcopy(self.saved)
        shortened["cases"][0]["policy"]["runs"][0]["duration_completed"] = 0.1
        variants.append(("complete with shortened horizon", shortened))
        missing_middle = deepcopy(self.saved)
        middle_rows = missing_middle["cases"][0]["policy"]["runs"][0]["trajectory"]
        del middle_rows[len(middle_rows) // 2]
        variants.append(("missing middle grid row", missing_middle))
        missing_end = deepcopy(self.saved)
        missing_end["cases"][0]["policy"]["runs"][0]["trajectory"].pop()
        variants.append(("missing final grid row", missing_end))
        complete_error = deepcopy(self.saved)
        complete_error["cases"][0]["policy"]["runs"][0]["error"] = "test-only unexpected terminal error"
        variants.append(("complete with error", complete_error))
        checkpoint = deepcopy(self.saved)
        checkpoint["checkpoint"]["source_sha256"]["engine"] = "0" * 64
        checkpoint["checkpoint"]["checkpoint_sha256"] = policy.checkpoint_digest(checkpoint["checkpoint"])
        variants.append(("checkpoint source", checkpoint))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for name, value in variants:
                with self.subTest(case=name), self.no_compute(), \
                        patch.object(report, "export_policy_evaluation") as export:
                    with self.assertRaises(ValueError):
                        report.export_evaluation(value, root / name)
                    export.assert_not_called()
                    self.assertFalse((root / name).exists())
                    self.assertEqual(list(root.glob("sparsiloop-recovery-*.json")), [])

    def test_legacy_web_failure_does_not_create_or_advertise_local_recovery(self):
        actual = Path.write_text

        def fail(path, *args, **kwargs):
            if path.name == "policy-checkpoint.json":
                raise OSError("injected temporary web write failure")
            return actual(path, *args, **kwargs)

        with self.no_compute(), patch.object(Path, "write_text", fail), \
                patch.object(export_recovery.tempfile, "mkstemp", wraps=export_recovery.tempfile.mkstemp) as cache:
            with self.assertRaises(OSError) as failed:
                web_recipes.pack(self.saved, evaluation_only=True)
        self.assertNotIsInstance(failed.exception, export_recovery.ExportRecoveryError)
        cache.assert_not_called()

    def test_native_grid_endpoint_keeps_a_valid_three_step_run(self):
        # A separate three-step structural positive control, not a policy training case.
        config = Config(duration=0.3, dt=0.1, budget=3, delay_steps=0, heartbeat=0.1,
                        loss_probability=0, measurement_noise=0, process_noise=0)
        with patch("event_control_lab.controllers.QTable.update") as training:
            run = simulate(config, "periodic")
        training.assert_not_called()
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["duration_completed"], config.steps * config.dt)
        self.assertGreater(run["duration_completed"], config.duration)
        report._run(run, "periodic", config)


if __name__ == "__main__":
    unittest.main()
