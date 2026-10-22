from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from event_control_lab import Config, Observation, compare, simulate
from examples.simple_pid_case import PIDAdapter, clock_negative_control, load_pid, run_case


load_pid()  # This optional test suite requires the exact pinned real library.


class SimplePIDTests(unittest.TestCase):
    def clean(self, **changes):
        return Config(**{"duration": 1, "budget": 10, "loss_probability": 0,
                         "measurement_noise": 0, "process_noise": 0, **changes})

    def test_sampling_gate_negative_control_and_real_arrival_gap_components(self):
        self.assertEqual(clock_negative_control()["outputs"], [-2, -2])
        controller = PIDAdapter(self.clean(), ki=0.1, kd=0.05)
        self.assertEqual(controller(Observation((1,), 0, 0.04)), -2)
        self.assertAlmostEqual(controller(Observation((0.5,), 0.2, 0.24)), -0.885)
        self.assertEqual(controller.updates[0]["components_p_i_d"], [-2, 0, 0])
        self.assertAlmostEqual(controller.updates[1]["elapsed_since_prior_arrival"], 0.2)
        self.assertIsNone(controller.updates[0]["elapsed_since_prior_arrival"])

    def test_p_only_adapter_matches_native_trajectories_with_loss_and_delay(self):
        for plant in ("scalar", "double_integrator"):
            config = self.clean(plant=plant, kd=0, loss_probability=0.3,
                                measurement_noise=0.01, process_noise=0.02, delay_steps=3)
            native = compare(config)
            adapted = compare(config, lambda current: PIDAdapter(current, ki=0, kd=0))
            for left, right in zip(native["runs"], adapted["runs"]):
                self.assertEqual(left["trajectory"], right["trajectory"])
                self.assertEqual(left["packets"], right["packets"])

    def test_controller_uses_delivered_old_position_and_no_calls_on_drops(self):
        config = self.clean(delay_steps=3)
        controller = PIDAdapter(config)
        result = simulate(config, "periodic", controller)
        self.assertEqual(controller.updates[0]["observed_position"], 1)
        self.assertAlmostEqual(controller.updates[0]["arrival_time"], 0.06)
        self.assertGreater(result["trajectory"][3]["state"][0], 1)
        self.assertEqual(len(controller.updates), result["packets"]["delivered"])
        dropped = PIDAdapter(replace(config, loss_probability=1))
        simulate(replace(config, loss_probability=1), "periodic", dropped)
        self.assertEqual(dropped.updates, [])

    def test_fresh_stateful_pid_instances_make_repeated_runs_identical(self):
        config = self.clean()
        instances = []

        def factory(current):
            value = PIDAdapter(current)
            instances.append(value)
            return value

        first, second = compare(config, factory), compare(config, factory)
        self.assertEqual(first, second)
        self.assertEqual(len({id(item) for item in instances}), 6)
        self.assertTrue(all(item.updates[0]["bootstrap_proportional_only"] for item in instances))

    def test_internal_clipping_is_visible_separately_from_actuator_counts(self):
        controller = PIDAdapter(self.clean(input_limit=1))
        self.assertEqual(controller(Observation((5,), 0, 0)), -1)
        self.assertEqual(controller.updates[0]["components_p_i_d"][0], -10)

    def test_invalid_or_repeated_arrival_is_rejected(self):
        controller = PIDAdapter(self.clean())
        controller(Observation((1,), 0, 0.04))
        for observation in (Observation((1,), 0, 0.04), Observation((1,), 0, 0.02),
                            Observation((1,), 0.1, 0.08), Observation((1, 2), 0, 0.1),
                            Observation((float("nan"),), 0, 0.1)):
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                controller(observation)

    def test_case_exports_controller_provenance_updates_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "new case"
            result, record = run_case(self.clean(), folder)
            self.assertEqual(record["version"], "2.0.1")
            self.assertEqual(record["license"], "MIT")
            self.assertEqual(json.loads((folder / "controller.json").read_text()), record)
            for run in result["runs"]:
                self.assertEqual(len(record["updates_by_policy"][run["policy"]]),
                                 run["metrics"]["controller_evaluations"])
            before = {path.name: path.read_bytes() for path in folder.iterdir()}
            with self.assertRaises(FileExistsError):
                run_case(self.clean(), folder)
            self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})


if __name__ == "__main__":
    unittest.main()
