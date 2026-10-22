from dataclasses import replace
import json
import math
import random
import unittest

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab, run_ilc, run_q_learning, teaching_config
from event_control_lab.controllers import CFDLMFAC, MFACParameters, QController, QParameters, QTable, TrialILC, ilc_next
from event_control_lab.engine import Observation, compare, simulate


def small_spec(**changes):
    return replace(ControllerLabSpec(), config=replace(teaching_config(), duration=0.2, budget=10),
                   ilc_trials=3, training_seeds=(101, 102, 103), evaluation_seeds=(2001,), **changes)


class MFACChecks(unittest.TestCase):
    def test_independent_first_two_updates(self):
        config = teaching_config()
        model = CFDLMFAC(config, MFACParameters(phi0=1, eta=1, mu=1, rho=1, penalty=1))
        self.assertEqual(model(Observation((1,), 0, 0)), -0.5)
        second = model(Observation((0.75,), config.dt, config.dt))
        self.assertAlmostEqual(model.phi, 0.9)
        self.assertAlmostEqual(second, -0.5 - 0.675 / 1.81)

    def test_applied_input_history_and_sign_reset(self):
        config = replace(teaching_config(), input_limit=0.1)
        model = CFDLMFAC(config, MFACParameters(phi0=1, eta=1, mu=0.01, rho=1, penalty=0.01))
        self.assertEqual(model(Observation((1,), 0, 0)), -0.1)
        model(Observation((2,), config.dt, config.dt))
        self.assertEqual(model.updates[1]["delta_u"], -0.1)
        self.assertEqual(model.updates[1]["reset_reason"], "estimate_sign_changed")
        self.assertEqual(model.phi, 1)

    def test_no_fabricated_bootstrap_or_irregular_time(self):
        c = teaching_config()
        model = CFDLMFAC(c)
        model(Observation((1,), 0, 0))
        self.assertIsNone(model.updates[0]["delta_y"])
        for observation in (Observation((1,), 0, 0), Observation((1,), 0.04, 0.04),
                            Observation((1,), 0, 0.02), Observation((math.nan,), 0.02, 0.02)):
            with self.assertRaises(ValueError):
                model(observation)

    def test_reset_between_runs_and_unsupported_network_is_visible(self):
        c = replace(teaching_config(), duration=0.2, budget=10)
        a, b = CFDLMFAC(c), CFDLMFAC(c)
        self.assertEqual(simulate(c, "periodic", a), simulate(c, "periodic", b))
        bad = replace(c, delay_steps=1)
        result = simulate(bad, "periodic", CFDLMFAC(bad))
        self.assertEqual(result["status"], "controller_error")
        self.assertIsNone(result["metrics"]["position_rmse"])


class ILCChecks(unittest.TestCase):
    def test_shifted_update_uses_next_received_sample_and_leaves_terminal(self):
        self.assertEqual(ilc_next((0, 0, 0), (999, 0.5, -0.25), 2, 4), (-1, 0.5, 0))

    def test_input_learning_matches_independent_two_interval_dynamics(self):
        spec = small_spec()
        result = run_ilc(spec)
        first, second = result["trials"][:2]
        expected_y1 = math.exp(spec.config.dt) - spec.config.kp * math.expm1(spec.config.dt)
        self.assertAlmostEqual(first["received_observations"][1], expected_y1)
        self.assertAlmostEqual(second["feedforward_used"][0], -spec.ilc_gain * expected_y1)
        for trial in result["trials"]:
            self.assertEqual(trial["run"]["trajectory"][0]["state"], [1])
            self.assertEqual(trial["feedforward_used"][-1], 0)
        self.assertFalse(result["trials"][-1]["learning_applied"])

    def test_incomplete_trial_does_not_learn_or_fill_missing_values(self):
        spec = small_spec()
        spec = replace(spec, config=replace(spec.config, kp=0, initial_position=0.99, state_limit=1))
        result = run_ilc(spec)
        self.assertEqual(len(result["trials"]), spec.ilc_trials)
        for trial in result["trials"]:
            self.assertEqual(trial["run"]["status"], "state_limit")
            self.assertFalse(trial["learning_applied"])
            self.assertIsNone(trial["next_feedforward"])
            self.assertIsNone(trial["run"]["metrics"]["position_rmse"])

    def test_ilc_only_accepts_declared_full_regular_trial(self):
        c = small_spec().config
        with self.assertRaises(ValueError):
            TrialILC(c, [0])
        with self.assertRaises(ValueError):
            ilc_next((0, 0), (1,), 1, 4)
        with self.assertRaises(ValueError):
            TrialILC(c, [0] * c.steps)(Observation((1,), 0.02, 0.02))


class RLChecks(unittest.TestCase):
    def test_hand_computed_bellman_and_terminal_targets(self):
        table = QTable(10, 4, QParameters(alpha=0.5, gamma=0.9))
        s, t = (0, 1), (1, 2)
        table.values[t] = (0, 1, 2, 3, 4, 5, 6)
        record = table.update(s, 3, -2, t)
        self.assertAlmostEqual(record["target"], 3.4)
        self.assertAlmostEqual(table.row(s)[3], 1.7)
        terminal = table.update(s, 3, -2, t, terminal=True)
        self.assertEqual(terminal["target"], -2)
        self.assertAlmostEqual(table.row(s)[3], -0.15)

    def test_learning_receives_next_sample_and_no_terminal_truth(self):
        c = small_spec().config
        table = QTable(c.steps, c.input_limit, QParameters(epsilon=0))
        model = QController(c, table, rng=random.Random(1))
        self.assertEqual(model(Observation((1,), 0, 0)), 0)
        self.assertEqual(model.updates, [])
        model(Observation((2,), c.dt, c.dt))
        self.assertAlmostEqual(model.updates[0]["reward"], -0.08)
        result = run_q_learning(small_spec())
        for episode in result["training"]:
            self.assertEqual(episode["completed_updates"], c.steps - 1)
            self.assertTrue(episode["q_updates"][-1]["terminal"])

    def test_checkpoint_roundtrip_and_frozen_evaluation(self):
        result = run_q_learning(small_spec())
        table = QTable.from_snapshot(json.loads(json.dumps(result["frozen_table"])))
        self.assertEqual(table.fingerprint(), result["frozen_sha256"])
        self.assertEqual(result["frozen_sha256"], result["frozen_after_evaluation_sha256"])
        before = table.snapshot()
        compare(small_spec().config, lambda c: QController(c, table))
        self.assertEqual(table.snapshot(), before)

    def test_checkpoint_rejects_nonfinite_duplicate_and_invalid_grid(self):
        table = QTable(10, 4)
        table.update((0, 1), 3, -1, (1, 2))
        for modification in ("nan", "duplicate", "bad_state", "bad_actions"):
            snapshot = json.loads(json.dumps(table.snapshot()))
            if modification == "nan":
                snapshot["rows"][0]["q"][0] = math.nan
            elif modification == "duplicate":
                snapshot["rows"].append(snapshot["rows"][0])
            elif modification == "bad_state":
                snapshot["rows"][0]["state"] = [10, 1]
            else:
                snapshot["actions"][0] = 123
            with self.assertRaises(ValueError):
                QTable.from_snapshot(snapshot)

    def test_seed_split_and_explicit_protocol_errors(self):
        spec = small_spec()
        with self.assertRaises(ValueError):
            replace(spec, evaluation_seeds=spec.training_seeds)
        with self.assertRaises(ValueError):
            replace(spec, training_seeds=(1, 1))
        for change in ({"delay_steps": 1}, {"budget": 0}, {"measurement_noise": 0.1},
                       {"plant": "double_integrator"}):
            with self.assertRaises(ValueError):
                replace(spec, config=replace(spec.config, **change))

    def test_evaluation_budget_is_bounded_before_allocating_runs(self):
        with self.assertRaises(ValueError):
            replace(ControllerLabSpec(), evaluation_seeds=tuple(range(1000, 1512)))

    def test_reproducibility_includes_raw_trials_and_training(self):
        first = controller_lab(small_spec())
        self.assertEqual(first, controller_lab(small_spec()))
        json.dumps(first, allow_nan=False)
        q = first["cases"]["rl"]
        self.assertEqual(len(q["evaluation"]), 1)
        self.assertNotEqual(q["initial_table"], q["frozen_table"])
        self.assertEqual(q["training_seeds"], [101, 102, 103])


if __name__ == "__main__":
    unittest.main()
