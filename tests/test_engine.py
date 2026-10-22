from dataclasses import replace
import json
import math
import tempfile
from pathlib import Path
import unittest

from event_control_lab import Config, Observation, compare, simulate
from event_control_lab.__main__ import export
from event_control_lab.engine import advance


class EngineTests(unittest.TestCase):
    def clean(self, **values):
        return Config(**{"duration": 1.0, "measurement_noise": 0.0, "process_noise": 0.0,
                         "loss_probability": 0.0, "delay_steps": 0, "budget": 20, **values})

    def test_scalar_held_input_matches_whole_interval_closed_form(self):
        x = (0.7,)
        for _ in range(50):
            x = advance("scalar", x, -0.3, 0.02)
        self.assertAlmostEqual(x[0], (0.7 - 0.3) * math.e + 0.3, places=12)

    def test_double_integrator_matches_constant_acceleration(self):
        x = (0.4, -0.6)
        for _ in range(100):
            x = advance("double_integrator", x, 1.5, 0.01)
        self.assertAlmostEqual(x[0], 0.4 - 0.6 + 0.75, places=12)
        self.assertAlmostEqual(x[1], -0.6 + 1.5, places=12)

    def test_constant_trajectory_has_known_time_integrated_metrics(self):
        config = self.clean(plant="double_integrator", budget=0)
        for run in compare(config)["runs"]:
            self.assertEqual(run["status"], "complete")
            self.assertAlmostEqual(run["metrics"]["position_rmse"], 1.0)
            self.assertAlmostEqual(run["metrics"]["quadratic_cost"], 1.0)
            self.assertIsNone(run["metrics"]["mean_observation_age"])
            self.assertEqual(run["metrics"]["unobserved_steps"], config.steps)
            self.assertEqual(run["metrics"]["controller_evaluations"], 0)
            self.assertEqual(run["metrics"]["sensor_samples"], config.steps)

    def test_zero_delay_bootstrap_is_counted_and_applied_before_dynamics(self):
        config = self.clean()
        run = simulate(config, "periodic")
        first, second = run["trajectory"][:2]
        self.assertTrue(first["sent"])
        self.assertEqual(first["delivered"], 1)
        self.assertEqual(first["input"], -2.0)
        self.assertAlmostEqual(second["state"][0], 2 - math.exp(config.dt))
        self.assertEqual(run["packets"]["attempted"], config.budget)

    def test_delayed_controller_sees_sampled_value_not_current_truth(self):
        observed = []

        def controller(observation):
            self.assertIsInstance(observation, Observation)
            self.assertEqual(set(vars(observation)), {"values", "sample_time", "arrival_time"})
            observed.append(observation)
            return 0.0

        config = self.clean(delay_steps=3, budget=1)
        run = simulate(config, "periodic", controller)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0].values, (1.0,))
        self.assertEqual(observed[0].sample_time, 0.0)
        self.assertAlmostEqual(observed[0].arrival_time, 0.06)
        self.assertGreater(run["trajectory"][3]["state"][0], 1.0)
        self.assertTrue(all(row["controller_values"] is None for row in run["trajectory"][:3]))

    def test_final_boundary_packets_remain_in_flight(self):
        config = self.clean(budget=1, delay_steps=50)
        run = simulate(config, "periodic")
        self.assertEqual(run["packets"], {"attempted": 1, "dropped": 0, "delivered": 0, "in_flight": 1})
        self.assertEqual(run["metrics"]["controller_evaluations"], 0)
        self.assertIsNone(run["metrics"]["mean_observation_age"])
        self.assertEqual(len(run["trajectory"]), config.steps + 1)

    def test_loss_and_budget_are_not_free_messages(self):
        config = self.clean(loss_probability=1.0, budget=5)
        for run in compare(config)["runs"]:
            packets = run["packets"]
            self.assertLessEqual(packets["attempted"], 5)
            self.assertEqual(packets["attempted"], packets["dropped"])
            self.assertEqual(packets["delivered"], 0)
            self.assertEqual(run["metrics"]["controller_evaluations"], 0)

    def test_periodic_schedule_spreads_budget_instead_of_burning_it_at_start(self):
        config = self.clean(budget=5)
        run = simulate(config, "periodic")
        sent = [row["t"] for row in run["trajectory"] if row["sent"]]
        self.assertEqual(sent, [0.0, 0.2, 0.4, 0.6, 0.8])

    def test_decimal_heartbeat_on_grid_does_not_wait_one_extra_step(self):
        for policy in ("absolute", "relative"):
            for loss in (0.0, 1.0):
                with self.subTest(policy=policy, loss=loss):
                    config = self.clean(duration=0.56, heartbeat=0.14, budget=28,
                                        threshold=2, initial_position=0, kp=0,
                                        loss_probability=loss)
                    run = simulate(config, policy)
                    ticks = [i for i, row in enumerate(run["trajectory"]) if row["sent"]]
                    self.assertEqual(ticks, [0, 7, 14, 21])
                    self.assertEqual(run["timing"]["effective_heartbeat_steps"], 7)
                    self.assertAlmostEqual(run["timing"]["effective_heartbeat_seconds"], 0.14)
                    self.assertEqual(run["packets"]["dropped"], 4 if loss else 0)

    def test_off_grid_heartbeat_still_waits_for_the_next_sample(self):
        for interval, spacing in ((0.139999, 7), (0.140001, 8), (0.14 + 1e-12, 8)):
            for policy in ("absolute", "relative"):
                with self.subTest(interval=interval, policy=policy):
                    config = self.clean(duration=0.56, heartbeat=interval, budget=28,
                                        threshold=2, initial_position=0, kp=0)
                    run = simulate(config, policy)
                    ticks = [i for i, row in enumerate(run["trajectory"]) if row["sent"]]
                    self.assertEqual(ticks, list(range(0, 28, spacing)))
                    self.assertEqual(run["timing"]["effective_heartbeat_steps"], spacing)

    def test_full_rate_zero_threshold_policies_reduce_to_the_same_system(self):
        for plant in ("scalar", "double_integrator"):
            config = self.clean(plant=plant, budget=50, threshold=0, relative_threshold=0,
                                loss_probability=0.2, delay_steps=3,
                                measurement_noise=0.02, process_noise=0.03)
            runs = compare(config)["runs"]
            for run in runs[1:]:
                self.assertEqual(run["trajectory"], runs[0]["trajectory"])
                self.assertEqual(run["packets"], runs[0]["packets"])
                self.assertEqual(run["metrics"]["position_rmse"], runs[0]["metrics"]["position_rmse"])

    def test_failed_short_run_has_no_full_horizon_score(self):
        config = self.clean(duration=4.0, budget=0, state_limit=2.0)
        run = simulate(config, "periodic")
        self.assertEqual(run["status"], "state_limit")
        self.assertLess(run["duration_completed"], config.duration)
        self.assertIsNone(run["metrics"]["position_rmse"])
        self.assertIsNone(run["metrics"]["quadratic_cost"])
        self.assertGreater(run["metrics"]["partial_position_integral"], 0)

    def test_controller_failure_keeps_failure_and_sensor_count(self):
        run = simulate(self.clean(), "periodic", lambda observation: float("nan"))
        self.assertEqual(run["status"], "controller_error")
        self.assertEqual(run["metrics"]["sensor_samples"], 1)
        self.assertEqual(run["duration_completed"], 0)
        self.assertIsNone(run["metrics"]["position_rmse"])
        json.dumps(run, allow_nan=False)

    def test_same_seed_repeats_exactly_and_every_policy_uses_the_same_trace(self):
        config = self.clean(measurement_noise=0.05, process_noise=0.03, loss_probability=0.3)
        first, second = compare(config), compare(config)
        self.assertEqual(first, second)
        self.assertEqual({run["trace_sha256"] for run in first["runs"]}, {first["exogenous_trace_sha256"]})
        changed = compare(replace(config, seed=config.seed + 1))
        self.assertNotEqual(changed["exogenous_trace_sha256"], first["exogenous_trace_sha256"])
        for run in first["runs"]:
            expected = sum(row["sent"] and first["exogenous_trace"]["loss_uniform"][i] < config.loss_probability
                           for i, row in enumerate(run["trajectory"][:-1]))
            self.assertEqual(run["packets"]["dropped"], expected)

    def test_each_policy_receives_a_new_controller(self):
        instances = []

        class Counter:
            def __init__(self):
                self.calls = 0

            def __call__(self, observation):
                self.calls += 1
                return 0

        def factory(config):
            value = Counter()
            instances.append(value)
            return value

        result = compare(self.clean(), factory)
        self.assertEqual(len({id(instance) for instance in instances}), 3)
        self.assertEqual([item.calls for item in instances],
                         [run["metrics"]["controller_evaluations"] for run in result["runs"]])

    def test_every_case_balances_packets_and_bounds_input(self):
        for plant in ("scalar", "double_integrator"):
            for loss in (0.0, 0.5, 1.0):
                config = self.clean(plant=plant, loss_probability=loss, delay_steps=7, budget=9)
                for run in compare(config)["runs"]:
                    with self.subTest(plant=plant, loss=loss, policy=run["policy"]):
                        packets = run["packets"]
                        self.assertEqual(packets["attempted"], packets["delivered"] + packets["dropped"] + packets["in_flight"])
                        self.assertLessEqual(packets["attempted"], config.budget)
                        self.assertTrue(all(abs(row["input"]) <= config.input_limit for row in run["trajectory"]))

    def test_invalid_configuration_is_rejected(self):
        for change in ({"budget": True}, {"budget": -1}, {"budget": 501}, {"dt": 0},
                       {"dt": float("nan")}, {"kp": 10**500}, {"duration": 1.001},
                       {"delay_steps": -1}, {"loss_probability": 1.1}, {"plant": []},
                       {"measurement_noise": True}, {"seed": 2**32}, {"state_limit": 0}):
            with self.subTest(change=str(change)):
                with self.assertRaises(ValueError):
                    self.clean(**change)
        with self.assertRaises(ValueError):
            Config.from_dict({"unrecognized": 1})

    def test_export_preserves_existing_output(self):
        result = compare(self.clean())
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "new"
            export(result, folder)
            before = {path.name: path.read_bytes() for path in folder.iterdir()}
            self.assertEqual(json.loads(before["result.json"]), result)
            with self.assertRaises(FileExistsError):
                export(result, folder)
            self.assertEqual({path.name: path.read_bytes() for path in folder.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
