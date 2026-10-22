import csv
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import tempfile
import unittest

from event_control_lab import Config, StudySpec, simulate, study
from event_control_lab.engine import LinearFeedback, make_trace
from event_control_lab.study import comparison_rows, export_study


class StudyTests(unittest.TestCase):
    def config(self, **changes):
        value = Config(duration=1, budget=50, delay_steps=0, loss_probability=0,
                       measurement_noise=0, process_noise=0, heartbeat=1)
        return replace(value, **changes)

    def test_reference_uses_actual_event_attempts_rather_than_shared_cap(self):
        result = study(StudySpec(self.config(), (0.2,), (8,)))
        for pair in result["pairs"]:
            event = result["runs"][pair["event_run"]]
            reference = result["runs"][pair["reference_run"]]
            actual = event["result"]["packets"]["attempted"]
            self.assertGreater(actual, 1)
            self.assertLess(actual, event["config"]["budget"])
            self.assertEqual(reference["config"], dict(event["config"], budget=actual))
            self.assertEqual(reference["result"]["packets"]["attempted"], actual)
            self.assertTrue(pair["eligible"])
            expected = simulate(Config.from_dict(reference["config"]), "periodic")
            self.assertEqual(reference["result"], expected)

    def test_full_rate_positive_control_has_zero_paired_difference(self):
        config = self.config(relative_threshold=0, delay_steps=3, loss_probability=0.2,
                             measurement_noise=0.02, process_noise=0.03)
        for plant in ("scalar", "double_integrator"):
            result = study(StudySpec(replace(config, plant=plant), (0,), (11, 12)))
            for pair in result["pairs"]:
                self.assertTrue(pair["eligible"])
                self.assertEqual(pair["rmse_delta_event_minus_periodic"], 0)
                self.assertEqual(result["runs"][pair["event_run"]]["result"]["trajectory"],
                                 result["runs"][pair["reference_run"]]["result"]["trajectory"])

    def test_random_paths_shared_within_seed_and_distinct_across_seeds(self):
        spec = StudySpec(self.config(loss_probability=0.4), (0.05, 0.2), (71, 72))
        result = study(spec)
        hashes = {}
        self.assertEqual(len(result["pairs"]), 8)
        for pair in result["pairs"]:
            event = result["runs"][pair["event_run"]]["result"]
            reference = result["runs"][pair["reference_run"]]["result"]
            self.assertEqual(event["trace_sha256"], reference["trace_sha256"])
            hashes.setdefault(pair["seed"], set()).add(event["trace_sha256"])
        self.assertTrue(all(len(value) == 1 for value in hashes.values()))
        self.assertNotEqual(hashes[71], hashes[72])
        for seed in spec.seeds:
            self.assertEqual(result["exogenous_traces"][str(seed)], make_trace(replace(spec.config, seed=seed))[0])

    def test_failed_event_stays_in_requested_cohort_with_null_full_horizon_metric(self):
        config = self.config(duration=4, budget=0, state_limit=2)
        result = study(StudySpec(config, (0.1, 0.2), (3, 4)))
        self.assertEqual(len(result["pairs"]), 8)
        self.assertEqual(len(result["runs"]), 16)
        for pair in result["pairs"]:
            self.assertTrue(pair["traffic_matched"])
            self.assertFalse(pair["eligible"])
            self.assertIn("event_failed", pair["unavailable_reasons"])
            self.assertIsNone(pair["rmse_delta_event_minus_periodic"])
        for summary in result["summaries"]:
            self.assertEqual(summary["requested_pairs"], 2)
            self.assertEqual(summary["eligible_pairs"], 0)
            self.assertIsNone(summary["all_seed_mean_rmse_delta"])
            self.assertIsNone(summary["eligible_subset_mean_rmse_delta"])

    def test_reference_failure_and_unmatched_traffic_are_not_hidden(self):
        config = self.config()
        calls = 0

        def factory(current):
            nonlocal calls
            calls += 1
            if calls % 2 == 0:
                return lambda observation: float("nan")
            return LinearFeedback(current)

        result = study(StudySpec(config, (0.2,), (4,)), factory)
        for pair in result["pairs"]:
            self.assertEqual(pair["unavailable_reasons"], ["reference_failed", "attempted_count_mismatch"])
            self.assertFalse(pair["traffic_matched"])
            self.assertIsNone(pair["rmse_delta_event_minus_periodic"])
            reference = result["runs"][pair["reference_run"]]["result"]
            self.assertEqual(reference["status"], "controller_error")
            self.assertIsNone(reference["metrics"]["position_rmse"])

    def test_partial_seed_coverage_does_not_become_all_seed_average(self):
        def factory(config):
            return LinearFeedback(config) if config.seed == 1 else lambda observation: float("nan")

        result = study(StudySpec(self.config(), (0.2,), (1, 2)), factory)
        for summary in result["summaries"]:
            self.assertEqual(summary["requested_pairs"], 2)
            self.assertEqual(summary["eligible_pairs"], 1)
            self.assertEqual(summary["eligible_seeds"], [1])
            self.assertIsNone(summary["all_seed_mean_rmse_delta"])
            self.assertTrue(math.isfinite(summary["eligible_subset_mean_rmse_delta"]))

    def test_all_requested_thresholds_and_seeds_retained_without_best_selection(self):
        spec = StudySpec(self.config(), (0.4, 0.01), (83, 19))
        first = study(spec)
        self.assertEqual(first, study(spec))
        self.assertEqual(first["spec"]["thresholds"], spec.thresholds)
        self.assertEqual({(pair["seed"], pair["threshold"], pair["policy"]) for pair in first["pairs"]},
                         {(seed, threshold, policy) for seed in spec.seeds for threshold in spec.thresholds
                          for policy in ("absolute", "relative")})
        for summary in first["summaries"]:
            values = [pair["rmse_delta_event_minus_periodic"] for pair in first["pairs"]
                      if pair["policy"] == summary["policy"] and pair["threshold"] == summary["threshold"]]
            self.assertAlmostEqual(summary["all_seed_mean_rmse_delta"], math.fsum(values) / len(values))

    def test_controller_factory_is_reset_for_every_raw_run(self):
        controllers = []
        configurations = []

        def factory(config):
            controller = LinearFeedback(config)
            controllers.append(controller)
            configurations.append(config)
            return controller

        result = study(StudySpec(self.config(), (0.1, 0.2), (2, 3)), factory)
        self.assertEqual(len(controllers), len(result["runs"]))
        self.assertEqual(len({id(controller) for controller in controllers}), len(controllers))
        for index in range(0, len(configurations), 2):
            self.assertEqual(configurations[index], configurations[index + 1])
        for pair in result["pairs"]:
            self.assertEqual(result["runs"][pair["event_run"]]["controller_factory_config"],
                             result["runs"][pair["reference_run"]]["controller_factory_config"])
        self.assertEqual(result["controller"], "custom_local_factory")

    def test_invalid_specs_and_excess_work_are_rejected(self):
        for arguments in ({"thresholds": []}, {"thresholds": [True]}, {"thresholds": [float("nan")]},
                          {"thresholds": [10**500]}, {"thresholds": [0.1, 0.1]}, {"thresholds": "0.1"},
                          {"seeds": []}, {"seeds": [1, 1]}, {"seeds": [True]}, {"seeds": [1.5]},
                          {"seeds": [2**32]}, {"seeds": list(range(6))}, {"config": {}},
                          {"config": self.config(duration=10, dt=0.002),
                           "thresholds": [0, 0.1, 0.2, 0.3], "seeds": [1, 2]}):
            with self.subTest(arguments=str(arguments)):
                with self.assertRaises(ValueError):
                    StudySpec(**arguments)
        for value in ([], None, {"best_threshold": True}, {"controller_code": "print(1)"}):
            with self.assertRaises(ValueError):
                StudySpec.from_dict(value)
        self.assertEqual(StudySpec(config=self.config(seed=123)).seeds, (123,))

    def test_exports_keep_raw_trajectories_failures_and_existing_files(self):
        result = study(StudySpec(self.config(), (0.2,), (5,)))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "with spaces"
            export_study(result, folder)
            restored = json.loads((folder / "study.json").read_text(encoding="utf-8"))
            self.assertEqual(restored["runs"], result["runs"])
            self.assertEqual(restored["pairs"], result["pairs"])
            with (folder / "comparisons.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            expected_rows = list(comparison_rows(result))
            self.assertEqual([row["id"] for row in rows], [row["id"] for row in expected_rows])
            self.assertEqual([int(row["event_attempted"]) for row in rows],
                             [row["event_attempted"] for row in expected_rows])
            with (folder / "trajectories.csv").open(encoding="utf-8", newline="") as handle:
                trajectories = list(csv.DictReader(handle))
            self.assertEqual(len(trajectories), sum(len(item["result"]["trajectory"]) for item in result["runs"].values()))
            before = {path.name: path.read_bytes() for path in folder.iterdir()}
            with self.assertRaises(FileExistsError):
                export_study(result, folder)
            self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)
        failed = study(StudySpec(self.config(budget=0, duration=4, state_limit=2), (0.2,), (5,)))
        self.assertTrue(all(row["event_rmse"] is None and row["reference_rmse"] is None
                            for row in comparison_rows(failed)))

    def test_spec_from_json_and_direct_api_agree(self):
        value = {"config": asdict(self.config()), "thresholds": [0.1], "seeds": [10, 11]}
        self.assertEqual(study(StudySpec.from_dict(value)), study(StudySpec(self.config(), (0.1,), (10, 11))))


if __name__ == "__main__":
    unittest.main()
