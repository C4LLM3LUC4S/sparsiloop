from dataclasses import replace
from fractions import Fraction
import json
import math
from pathlib import Path
import tempfile
import unittest

from event_control_lab import Config, PlantAdapter, StudySpec, compare, simulate, study
from event_control_lab.controller_lab import ControllerLabSpec, controller_lab, export_controller_lab, records
from event_control_lab.engine import advance
from examples.own_model_case import actuator_model


def clean(**changes):
    return Config(**{"duration": 0.2, "heartbeat": 0.1, "budget": 10, "delay_steps": 0,
                     "loss_probability": 0, "measurement_noise": 0, "process_noise": 0, **changes})


class ModelTests(unittest.TestCase):
    def test_actuator_matches_independent_whole_interval_solution(self):
        c = clean(duration=1.0, budget=50)
        run = simulate(c, "periodic", lambda _: 0.3, plant=actuator_model())
        expected = math.exp(-0.4) + 1.2 * 0.3 / 0.4 * (1 - math.exp(-0.4))
        self.assertEqual(run["status"], "complete")
        self.assertAlmostEqual(run["trajectory"][-1]["state"][0], expected, places=12)
        self.assertEqual(run["plant"]["parameters"]["decay_per_second"], 0.4)
        self.assertEqual(len(run["plant"]["source_sha256"]), 64)

    def test_adapter_positive_control_keeps_builtin_dynamics_and_network(self):
        for layout in ("scalar", "double_integrator"):
            c = clean(plant=layout, delay_steps=2, loss_probability=0.3,
                      measurement_noise=0.02, process_noise=0.03)
            adapter = PlantAdapter("builtin control", layout,
                                   lambda config: lambda state, u, dt: advance(config.plant, state, u, dt),
                                   state_units=("position",) if layout == "scalar" else ("position", "velocity"))
            ordinary, adapted = compare(c), compare(c, plant=adapter)
            for left, right in zip(ordinary["runs"], adapted["runs"]):
                for key in ("status", "trajectory", "metrics", "packets", "trace_sha256"):
                    self.assertEqual(left[key], right[key])

    def test_each_policy_and_study_reference_reset_the_model(self):
        initialized, calls = [], []

        def factory(config):
            initialized.append(config)
            history = []
            calls.append(history)

            def step(state, u, dt):
                history.append(state)
                return state
            return step

        model = PlantAdapter("reset counter", "scalar", factory)
        c = clean()
        compare(c, plant=model)
        self.assertEqual(len(calls), 3)
        self.assertEqual([len(values) for values in calls], [c.steps] * 3)
        self.assertEqual(len({id(values) for values in calls}), 3)
        initialized.clear()
        result = study(StudySpec(c, thresholds=(1.0,), seeds=(7,)), plant=model)
        self.assertEqual([config.budget for config in initialized], [10] * 4)
        for pair in result["pairs"]:
            reference = result["runs"][pair["reference_run"]]
            self.assertLess(reference["config"]["budget"], c.budget)
            self.assertEqual(reference["result"]["plant_initialization_config"]["budget"], c.budget)
            self.assertTrue(pair["eligible"])

    def test_plant_truth_stays_on_model_side_controller_sees_delivered_sample(self):
        observations, truth = [], []

        def controller(obs):
            self.assertEqual(set(vars(obs)), {"values", "sample_time", "arrival_time"})
            observations.append(obs)
            return 0

        def step(state, held_input, dt):
            truth.append(state)
            return (state[0] + 1,)

        c = clean(budget=1, delay_steps=2)
        run = simulate(c, "periodic", controller, plant=PlantAdapter("counter", "scalar", lambda _: step))
        self.assertEqual(run["status"], "complete")
        self.assertEqual(observations[0].values, (1,))
        self.assertEqual(observations[0].arrival_time, 0.04)
        self.assertEqual(truth[2], (3,))

    def test_bad_return_values_keep_failure_without_full_horizon_score(self):
        for value in ((), (1, 2), (True,), (math.nan,), (math.inf,), (1e200,), "1", {"x": 1}, 1):
            with self.subTest(value=value):
                model = PlantAdapter("bad step", "scalar", lambda _: lambda state, u, dt: value)
                run = simulate(clean(delay_steps=1), "periodic", plant=model)
                self.assertEqual(run["status"], "plant_error")
                self.assertEqual(run["duration_completed"], 0)
                self.assertEqual(run["trajectory"][-1]["state"], [1])
                self.assertIsNone(run["metrics"]["position_rmse"])
                self.assertIsNone(run["metrics"]["quadratic_cost"])
                self.assertEqual(run["packets"], {"attempted": 1, "dropped": 0, "delivered": 0, "in_flight": 1})
                json.dumps(run, allow_nan=False)

    def test_factory_error_is_a_zero_duration_failed_record(self):
        def broken(config):
            raise RuntimeError("cannot initialize model")
        for factory in (broken, lambda _: None):
            run = simulate(clean(), plant=PlantAdapter("broken", "scalar", factory))
            self.assertEqual(run["status"], "plant_error")
            self.assertEqual(run["metrics"]["sensor_samples"], 0)
            self.assertEqual(run["packets"]["attempted"], 0)
            self.assertIsNone(run["metrics"]["position_rmse"])
            self.assertIn("plant initialization:", run["error"])

    def test_later_model_error_preserves_only_the_completed_prefix(self):
        def factory(config):
            count = 0

            def step(state, u, dt):
                nonlocal count
                count += 1
                if count == 3:
                    raise ArithmeticError("declared failure")
                return state
            return step
        result = study(StudySpec(clean(), thresholds=(0.06,), seeds=(1,)),
                       plant=PlantAdapter("failing model", "scalar", factory))
        for item in result["runs"].values():
            run = item["result"]
            self.assertEqual(run["status"], "plant_error")
            self.assertEqual(run["duration_completed"], 0.04)
            self.assertAlmostEqual(run["metrics"]["partial_position_integral"], 0.04)
        self.assertTrue(all(not pair["eligible"] for pair in result["pairs"]))
        self.assertTrue(all(row["all_seed_mean_rmse_delta"] is None for row in result["summaries"]))

    def test_finite_state_limit_still_records_the_reached_state(self):
        model = PlantAdapter("unstable", "scalar", lambda _: lambda state, u, dt: (30,))
        run = simulate(clean(), plant=model)
        self.assertEqual(run["status"], "state_limit")
        self.assertEqual(run["duration_completed"], 0.02)
        self.assertEqual(run["trajectory"][-1]["state"], [30])
        self.assertIsNone(run["metrics"]["quadratic_cost"])

    def test_regular_real_scalars_are_normalized_to_json_floats(self):
        model = PlantAdapter("fraction", "scalar", lambda _: lambda state, u, dt: [Fraction(1, 2)])
        run = simulate(clean(), plant=model)
        self.assertEqual(run["trajectory"][-1]["state"], [0.5])
        json.dumps(run, allow_nan=False)

    def test_model_step_receives_the_actuator_input_with_declared_disturbance(self):
        received = []
        c = clean(input_limit=1, process_noise=0.3)

        def step(state, u, dt):
            received.append((u, dt))
            return state
        result = compare(c, lambda _: lambda obs: 100,
                         plant=PlantAdapter("held input", "scalar", lambda _: step))
        noise = result["exogenous_trace"]["input_disturbance_standard_normal"]
        self.assertEqual(received[:c.steps], [(1 + 0.3 * z, c.dt) for z in noise])

    def test_metadata_is_a_snapshot_and_invalid_declarations_are_rejected(self):
        parameters = {"a": [1]}
        model = PlantAdapter("declared", "scalar", lambda _: lambda state, u, dt: state, parameters=parameters)
        parameters["a"].append(2)
        snapshot = model.metadata()
        snapshot["parameters"]["a"].append(3)
        self.assertEqual(model.metadata()["parameters"], {"a": [1]})
        for values in ({"state_layout": []}, {"factory": None}, {"name": ""},
                       {"state_units": ("x", "v")}, {"parameters": {"x": math.nan}},
                       {"parameters": {1: 2}}, {"source_sha256": "unverified"}):
            args = {"name": "x", "state_layout": "scalar", "factory": lambda _: None, **values}
            with self.assertRaises(ValueError):
                PlantAdapter(**args)
        with self.assertRaises(ValueError):
            compare(clean(plant="double_integrator"), plant=model)
        with self.assertRaises(ValueError):
            simulate(clean(), plant=model, plant_config=clean(seed=7))

    def test_classic_recipes_all_use_custom_dynamics_and_fresh_models(self):
        initializations = []

        def factory(config):
            initializations.append(config)
            return lambda state, u, dt: (0.5,)

        model = PlantAdapter("constant diagnostic model", "scalar", factory)
        spec = replace(ControllerLabSpec(), config=clean(), ilc_trials=2,
                       training_seeds=(101, 102), evaluation_seeds=(2001,))
        result = controller_lab(spec, plant=model)
        rows = list(records(result))
        self.assertEqual(len(rows), 1 + 2 + 2 + 9)
        self.assertEqual(len(initializations), len(rows))
        for method, stage, label, config, run in rows:
            self.assertEqual(run["trajectory"][1]["state"], [0.5])
            self.assertEqual(run["plant"], result["plant"])
        q = result["cases"]["rl"]
        self.assertEqual(q["frozen_sha256"], q["frozen_after_evaluation_sha256"])
        self.assertTrue(all(trial["run"]["trajectory"][0]["state"] == [1]
                            for trial in result["cases"]["ilc"]["trials"]))

    def test_ilc_does_not_learn_after_a_model_error_and_report_names_the_failure(self):
        model = PlantAdapter("<model>", "scalar", lambda _: lambda state, u, dt: (math.nan,))
        spec = replace(ControllerLabSpec(), config=clean(), ilc_trials=2)
        result = controller_lab(spec, method="ilc", plant=model)
        self.assertTrue(all(not row["learning_applied"] for row in result["cases"]["ilc"]["trials"]))
        with tempfile.TemporaryDirectory() as temporary:
            export_controller_lab(result, Path(temporary) / "report")
            page = (Path(temporary) / "report/report.html").read_text(encoding="utf-8")
            self.assertIn("模型错误", page)
            self.assertIn("&lt;model&gt;", page)
            self.assertNotIn("<model>", page)
            self.assertIn("不可用 / N/A", page)


if __name__ == "__main__":
    unittest.main()
