"""Independent physical-coordinate and saved-task checks; no learned-controller work."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config, compare
from event_control_lab import constant_target as target
from event_control_lab.constant_target_cli import main
from event_control_lab.constant_target_report import export_task, render_html
from event_control_lab.export_recovery import ExportRecoveryError


def config(**changes):
    return Config(**{"plant": "double_integrator", "duration": 0.2, "dt": 0.1, "budget": 2,
                     "heartbeat": 0.2, "delay_steps": 0, "loss_probability": 0,
                     "measurement_noise": 0, "process_noise": 0, "initial_position": 0,
                     **changes})


def seal(value):
    value["record_sha256"] = target.digest({k: v for k, v in value.items() if k != "record_sha256"})
    return value


class ConstantTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = target.run_task(target.TargetSpec(1, config(initial_velocity=0.25)))

    def test_physical_motion_matches_independent_held_input_solution(self):
        c = config(initial_velocity=0.25)
        rows = list(target.physical_rows(self.record))
        for policy in ("periodic", "absolute", "relative"):
            trajectory = [row for row in rows if row["policy"] == policy]
            for first, second in zip(trajectory, trajectory[1:]):
                # Constant acceleration solution in physical coordinates, not the error-coordinate update.
                p, v, u, dt = first["position"], first["velocity"], first["effective_interval_input"], c.dt
                self.assertAlmostEqual(second["position"], p + v * dt + u * dt * dt / 2)
                self.assertAlmostEqual(second["velocity"], v + u * dt)
                self.assertAlmostEqual(first["position_error"], first["position"] - 1)
            self.assertIsNone(trajectory[-1]["effective_interval_input"])

    def test_joint_position_target_shift_preserves_error_comparison(self):
        first = target.run_task(target.TargetSpec(1, config(initial_position=0)))
        shifted = target.run_task(target.TargetSpec(3, config(initial_position=2)))
        self.assertEqual(first["comparison"], shifted["comparison"])
        for a, b in zip(target.physical_rows(first), target.physical_rows(shifted)):
            self.assertEqual(b["position"], a["position"] + 2)
            self.assertEqual(a["position_error"], b["position_error"])

    def test_zero_target_matches_unchanged_legacy_compare(self):
        c = config(initial_position=1)
        record = target.run_task(target.TargetSpec(0, c))
        self.assertEqual(record["comparison"], compare(c))
        self.assertEqual(target.load_record(record), record)

    def test_at_target_equilibrium_and_no_measurement_hold(self):
        for c in (config(initial_position=1), config(initial_position=1, budget=0)):
            record = target.run_task(target.TargetSpec(1, c))
            for run in record["comparison"]["runs"]:
                self.assertEqual(run["metrics"]["position_rmse"], 0)
                self.assertTrue(all(row["state"] == [0, 0] and row["input"] == 0 for row in run["trajectory"]))

    def test_delayed_received_information_and_packet_ledger(self):
        c = config(duration=0.4, budget=4, delay_steps=2, initial_velocity=0.25)
        record = target.run_task(target.TargetSpec(1, c))
        for run in record["comparison"]["runs"]:
            for row in run["trajectory"][:2]:
                self.assertIsNone(row["controller_values"])
                self.assertEqual(row["input"], 0)
            first = run["trajectory"][2]
            self.assertEqual(first["controller_values"], [-1, 0.25])
            self.assertNotEqual(first["controller_values"], first["state"])
            ledger = run["packets"]
            self.assertEqual(ledger["attempted"], ledger["delivered"] + ledger["dropped"] + ledger["in_flight"])
        lost = target.run_task(target.TargetSpec(1, replace(c, loss_probability=1)))
        self.assertTrue(all(row["controller_values"] is None and row["input"] == 0
                            for run in lost["comparison"]["runs"] for row in run["trajectory"]))

    def test_saturation_disturbance_and_failed_full_metric_null(self):
        saturated = target.run_task(target.TargetSpec(1, config(input_limit=0.1, process_noise=0.2)))
        data = list(target.physical_rows(saturated))
        self.assertTrue(any(abs(row["clipped_command"]) == 0.1 for row in data))
        self.assertTrue(any(row["effective_interval_input"] is not None
                            and row["effective_interval_input"] != row["clipped_command"] for row in data))
        failed = target.run_task(target.TargetSpec(0, config(initial_position=1, initial_velocity=0.5,
                                                            state_limit=1.2, budget=0)))
        self.assertTrue(all(run["status"] == "state_limit" for run in failed["comparison"]["runs"]))
        for run in failed["comparison"]["runs"]:
            self.assertIsNone(run["metrics"]["position_rmse"])
            self.assertIsNone(run["metrics"]["quadratic_cost"])
        self.assertEqual(target.load_record(failed), failed)

    def test_reject_wrong_object_nonfinite_and_invalid_initial_error(self):
        for r in (True, math.nan, math.inf, 6, 10**1000):
            with self.subTest(target=r), self.assertRaises(ValueError):
                target.TargetSpec(r, config())
        with self.assertRaises(ValueError):
            target.TargetSpec(1, Config())
        with self.assertRaisesRegex(ValueError, "初始位置减目标"):
            target.TargetSpec(-5, config(initial_position=5))

    def test_changed_declarations_sources_or_results_reject_without_simulation(self):
        variants = []
        for change in (lambda v: v["spec"].update(target=2),
                       lambda v: v["spec"].update(target=10**1000),
                       lambda v: v["spec"]["config"].pop("initial_position"),
                       lambda v: v["error_config"].update(initial_position=0),
                       lambda v: v["comparison"].update(controller="custom_local_factory"),
                       lambda v: v["comparison"].update(python_version="0.0.0"),
                       lambda v: v["source_sha256"].update({"engine.py": "0" * 64}),
                       lambda v: v["comparison"]["exogenous_trace"]["loss_uniform"].__setitem__(0, 0.5),
                       lambda v: v["comparison"]["runs"][0]["packets"].update(attempted=99),
                       lambda v: v["comparison"]["runs"][0]["trajectory"][0].update(state=[0, 0])):
            value = deepcopy(self.record)
            change(value)
            variants.append(seal(value))
        with patch.object(target, "compare", side_effect=AssertionError("No simulation")) as computation:
            for value in variants:
                with self.subTest(), self.assertRaises(ValueError):
                    target.load_record(value)
            computation.assert_not_called()

    def test_terminal_events_reject_even_when_packet_totals_are_rewritten(self):
        value = target.run_task(target.TargetSpec(1, config(threshold=2, relative_threshold=2)))
        run = value["comparison"]["runs"][1]
        self.assertLess(run["packets"]["attempted"], value["spec"]["config"]["budget"])
        run["trajectory"][-1]["sent"] = True
        run["trajectory"][-1]["dropped"] = True
        run["packets"]["attempted"] += 1
        run["packets"]["dropped"] += 1
        with self.assertRaisesRegex(ValueError, "末行"):
            target.load_record(seal(value))

    def test_export_and_readonly_redraw_preserve_original_unknown_environment(self):
        value = deepcopy(self.record)
        value["execution"] = {"state": "not_recorded", "runtime": None}
        seal(value)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            export_task(value, folder / "first")
            original = (folder / "first/target-task.json").read_bytes()
            with patch.object(target, "compare", side_effect=AssertionError("No computation")), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["render", str(folder / "first/target-task.json"), "--out", str(folder / "new")]), 0)
            self.assertEqual((folder / "new/target-task.json").read_bytes(), original)
            environment = json.loads((folder / "new/environment.json").read_text(encoding="utf-8"))
            self.assertEqual(environment["execution"], value["execution"])
            self.assertIn("captured_at_utc", environment["report_rendering"])
            page = render_html(value)
            for word in ("实际初始位置", "误差", "相对触发", "限幅", "原执行环境未知"):
                self.assertIn(word, page)

    def test_output_preflight_precedes_input_and_compute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocker = root / "keep"
            blocker.write_bytes(b"original")
            with patch.object(Path, "read_bytes", side_effect=AssertionError("No input read")), \
                    patch("event_control_lab.constant_target_cli.run_task", side_effect=AssertionError("No simulation")), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(main(["run", "--spec", "missing.json", "--out", str(blocker / "result")]), 2)
            self.assertEqual(blocker.read_bytes(), b"original")

    def test_huge_target_cli_rejects_without_traceback_or_compute(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            spec = folder / "huge target.json"
            spec.write_text(json.dumps({"target": 10**1000, "config": {"plant": "double_integrator"}}), encoding="utf-8")
            error = io.StringIO()
            with patch("event_control_lab.constant_target_cli.run_task", side_effect=AssertionError("No simulation")), \
                    redirect_stderr(error):
                self.assertEqual(main(["run", "--spec", str(spec), "--out", str(folder / "new")]), 2)
            self.assertIn("有限数值", error.getvalue())
            self.assertNotIn("Traceback", error.getvalue())
            self.assertFalse((folder / "new").exists())

    def test_late_failure_retains_real_complete_file_and_actual_render_command(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch("event_control_lab.constant_target_report.render_html", side_effect=OSError("blocked HTML")):
                with self.assertRaises(ExportRecoveryError) as failed:
                    export_task(self.record, folder / "failed")
            error = failed.exception
            self.assertEqual(target.read_record(error.record_path), self.record)
            self.assertIn("event_control_lab.constant_target render", error.command)
            command = (["powershell", "-NoProfile", "-NonInteractive", "-Command", error.command]
                       if sys.platform == "win32" else ["sh", "-c", error.command])
            result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                    encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_record(error.redraw_output / "target-task.json"), self.record)


if __name__ == "__main__":
    unittest.main()
