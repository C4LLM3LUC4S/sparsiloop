from dataclasses import replace
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from event_control_lab import Config, GridSpec, grid_check
from event_control_lab.grid import _position_square_integral, export_grid_check


class GridTests(unittest.TestCase):
    def clean(self, **changes):
        return Config(**{"duration": 0.8, "budget": 4, "heartbeat": 0.2,
                         "measurement_noise": 0, "process_noise": 0, "loss_probability": 0,
                         **changes})

    def test_interval_integrals_match_independent_analytic_examples(self):
        cases = (("scalar", (1,), -1, 1, 1),
                 ("scalar", (1,), 0, 1, math.expm1(2) / 2),
                 ("double_integrator", (0, 0), 2, 1, 1 / 5),
                 ("double_integrator", (1, 2), 3, 1, 437 / 60))
        for plant, state, command, duration, expected in cases:
            with self.subTest(plant=plant, state=state, command=command):
                self.assertAlmostEqual(float(_position_square_integral(
                    plant, state, command, duration)), expected, places=13)

    def test_physical_delay_and_periodic_trajectory_match_on_common_times(self):
        for plant in ("scalar", "double_integrator"):
            with self.subTest(plant=plant):
                result = grid_check(GridSpec(self.clean(plant=plant)))
                self.assertAlmostEqual(result["physical_delay_seconds"], 0.04)
                self.assertEqual([item["comparison"]["config"]["delay_steps"]
                                  for item in result["runs"]], [2, 4, 8])
                finest = result["runs"][-1]["comparison"]["runs"][0]
                expected_ticks = [i for i, row in enumerate(finest["trajectory"]) if row["sent"]]
                for item, stride in zip(result["runs"][:-1], (4, 2)):
                    periodic = item["comparison"]["runs"][0]
                    actual_ticks = [i * stride for i, row in enumerate(periodic["trajectory"])
                                    if row["sent"]]
                    self.assertEqual(actual_ticks, expected_ticks)
                for change in result["changes_from_finest"]:
                    self.assertTrue(change["both_complete"])
                    if change["policy"] == "periodic":
                        self.assertLess(change["max_state_difference_at_common_times"], 1e-10)
                        self.assertEqual(change["attempted_packets_minus_finest"], 0)

    def test_open_loop_reference_matches_whole_interval_and_quadrature_refines(self):
        config = self.clean(duration=1, budget=0, kp=0, delay_steps=0, state_limit=100)
        result = grid_check(GridSpec(config))
        expected = math.sqrt(math.expm1(2) / 2)
        errors = []
        for summary in result["summaries"]:
            self.assertAlmostEqual(summary["held_input_reference_rmse"], expected, places=11)
            if summary["policy"] == "periodic":
                errors.append(abs(summary["rmse_quadrature_error"]))
        self.assertGreater(errors[0], errors[1])
        self.assertGreater(errors[1], errors[2])

    def test_failed_runs_retain_raw_data_but_no_full_horizon_differences(self):
        result = grid_check(GridSpec(self.clean(duration=1, budget=0, kp=0, state_limit=1.1)))
        for summary in result["summaries"]:
            self.assertEqual(summary["status"], "state_limit")
            self.assertIsNone(summary["reported_position_rmse"])
            self.assertIsNone(summary["held_input_reference_rmse"])
            self.assertIsNone(summary["rmse_quadrature_error"])
        for change in result["changes_from_finest"]:
            self.assertFalse(change["both_complete"])
            self.assertIsNone(change["max_state_difference_at_common_times"])
            self.assertIsNone(change["reported_rmse_minus_finest"])
            self.assertEqual(change["unavailable_reasons"], ["at_least_one_run_incomplete"])
        self.assertTrue(all(run["trajectory"] for item in result["runs"]
                            for run in item["comparison"]["runs"]))

    def test_stochastic_inputs_are_rejected_instead_of_silently_zeroed(self):
        for key in ("loss_probability", "measurement_noise", "process_noise"):
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, "zero loss"):
                GridSpec(replace(self.clean(), **{key: 0.1}))

    def test_misaligned_time_or_periodic_schedules_are_rejected(self):
        for spec in (lambda: GridSpec(self.clean(), (0.02, 0.0125)),
                     lambda: GridSpec(self.clean(dt=0.01, delay_steps=3)),
                     lambda: GridSpec(self.clean(heartbeat=0.21)),
                     lambda: GridSpec(self.clean(duration=0.81)),
                     lambda: GridSpec(self.clean(budget=3))):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                spec()

    def test_invalid_grid_spec_is_rejected(self):
        for steps in ((0.02,), (0.02, 0.02), (0.005, 0.01), (0.02, True),
                      (0.02, float("nan")), (0.02, 0.001), "0.02,0.01"):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                GridSpec(self.clean(), steps)
        with self.assertRaises(ValueError):
            GridSpec.from_dict({"unknown": 1})
        self.assertEqual(GridSpec.from_dict({}).config.loss_probability, 0)

    def test_export_matches_json_csv_and_refuses_existing_output(self):
        result = grid_check(GridSpec(self.clean()))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "new result"
            export_grid_check(result, destination)
            before = {path.name: path.read_bytes() for path in destination.iterdir()}
            self.assertEqual(json.loads(before["grid.json"]), json.loads(json.dumps(result)))
            with (destination / "summary.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), len(result["summaries"]))
            for row, summary in zip(rows, result["summaries"]):
                self.assertEqual(row["policy"], summary["policy"])
                self.assertAlmostEqual(float(row["reported_position_rmse"]),
                                       summary["reported_position_rmse"])
            with self.assertRaises(FileExistsError):
                export_grid_check(result, destination)
            self.assertEqual({path.name: path.read_bytes() for path in destination.iterdir()}, before)

    def test_cli_reads_spec_and_exports_three_inspectable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            specification = Path(directory) / "spec.json"
            specification.write_text(json.dumps({"config": vars(self.clean())}), encoding="utf-8-sig")
            destination = Path(directory) / "result"
            command = [sys.executable, "-m", "event_control_lab", "grid-check",
                       "--spec", str(specification), "--out", str(destination)]
            process = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)["analysis"], "deterministic-nested-grid-check-v1")
            self.assertEqual({path.name for path in destination.iterdir()},
                             {"grid.json", "summary.csv", "changes.csv"})


if __name__ == "__main__":
    unittest.main()
