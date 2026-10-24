"""Frozen inference, complete history, phase separation and independent reuse."""

from copy import deepcopy
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.controllers import QController, QTable
from event_control_lab import planned_context as context, planned_policy as planned
from event_control_lab.planned_study import PlannedSpec, digest, select_schedule
from event_control_lab.policy import checkpoint, checkpoint_digest, load_checkpoint
from event_control_lab.web_planned import test_from_web as web_test


ROOT = Path(__file__).resolve().parents[1]


class PlannedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lab = ControllerLabSpec()
        cls.lab = replace(lab, config=replace(lab.config, duration=0.4, budget=20),
                          training_seeds=(101, 102), evaluation_seeds=(1001,))
        cls.saved = checkpoint(controller_lab(cls.lab, "rl"))

    def spec(self, **changes):
        config = replace(self.lab.config, budget=10, initial_position=0.75, heartbeat=0.4)
        return replace(PlannedSpec(config=config, absolute_thresholds=(2,), relative_thresholds=(),
                                  selection_seeds=(3001, 3002), test_seeds=(4001, 4002), rmse_limit=100), **changes)

    def test_actual_checkpoint_is_frozen_with_fresh_controller_and_fixed_initial_state(self):
        before, instances = deepcopy(self.saved), []
        def fresh(config, table):
            controller = QController(config, table)
            instances.append(controller)
            return controller
        with patch.object(planned, "QController", side_effect=fresh), \
                patch.object(QTable, "update", side_effect=AssertionError("must not train")):
            saved = context.select_with_context(self.spec(), policy_checkpoint=self.saved)
            self.assertEqual({c.config.seed for c in instances}, {3001, 3002})
            self.assertEqual(saved["result"]["selection_traces"].keys(), {"3001", "3002"})
            tested = context.test_with_context(json.loads(json.dumps(saved)))
        self.assertEqual(before, self.saved)
        self.assertEqual(len({id(c) for c in instances}), len(instances))
        self.assertTrue(all(c.rng is None and c.updates == [] for c in instances))
        for row in saved["result"]["selection_runs"] + tested["result"]["test_runs"]:
            self.assertEqual(row["run"]["trajectory"][0]["state"], [0.75])
            self.assertEqual(row["controller"]["before_sha256"], self.saved["table_sha256"])
            self.assertEqual(row["controller"]["after_sha256"], self.saved["table_sha256"])
            self.assertEqual(row["controller"]["learning_updates"], 0)
            first, second = row["run"]["trajectory"][:2]
            expected = 0.75 * math.exp(self.spec().config.dt) + first["input"] * math.expm1(self.spec().config.dt)
            self.assertAlmostEqual(second["state"][0], expected)
        self.assertEqual(tested["result"]["selected_id"], saved["result"]["selected_id"])
        self.assertEqual(tested["context"]["selection"], saved["context"]["selection"])

    def test_periodic_reference_uses_same_policy_trace_cap_and_only_reserved_tests(self):
        chosen = planned.select_policy_schedule(self.spec(), policy_checkpoint=self.saved)
        tested = planned.test_policy_schedule(chosen)
        self.assertEqual(set(tested["test_traces"]), {"4001", "4002"})
        for seed in self.spec().test_seeds:
            rows = [r for r in tested["test_runs"] if r["seed"] == seed]
            self.assertEqual(len({r["run"]["trace_sha256"] for r in rows}), 1)
            self.assertEqual({r["config"]["budget"] for r in rows}, {10})
            self.assertEqual({r["controller"]["before_sha256"] for r in rows}, {self.saved["table_sha256"]})
            self.assertTrue(any("periodic_reference" in r["roles"] for r in rows))

    def test_history_keeps_each_phase_and_refuses_all_known_used_seeds(self):
        chosen = planned.select_policy_schedule(self.spec(), policy_checkpoint=self.saved)
        tested = planned.test_policy_schedule(chosen)
        history = tested["policy_after"]
        self.assertEqual([r["phase"] for r in history["planned_history"]], ["selection", "test"])
        self.assertEqual(history["checkpoint"]["previous_evaluation_seeds"], [1001, 3001, 3002, 4001, 4002])
        load_checkpoint(history["checkpoint"])
        planned.history_for(history)
        with patch.object(planned, "simulate", side_effect=AssertionError("must reject first")):
            for seed in (101, 1001, 3001, 4001):
                with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, "编号已经"):
                    planned.select_policy_schedule(self.spec(selection_seeds=(seed,), test_seeds=(6001,)), policy_checkpoint=history)
        next_choice = planned.select_policy_schedule(self.spec(selection_seeds=(5001,), test_seeds=(6001,)), policy_checkpoint=history)
        self.assertEqual(len(next_choice["policy_after"]["planned_history"]), 3)
        self.assertEqual(next_choice["policy_after"]["planned_history"][:2], history["planned_history"])

    def test_missing_table_source_or_clock_mismatch_is_rejected_before_simulation(self):
        bad = deepcopy(self.saved)
        bad["source_sha256"] = {}
        bad["checkpoint_sha256"] = checkpoint_digest(bad)
        with patch.object(planned, "simulate", side_effect=AssertionError("must reject first")):
            for value in (None, self.saved["table"], bad):
                with self.assertRaises(ValueError):
                    context.select_with_context(self.spec(), policy_checkpoint=value if value is not None else {})
            for changes in ({"dt": 0.04, "duration": 0.8}, {"input_limit": 2}, {"plant": "double_integrator"}):
                spec = self.spec(config=replace(self.spec().config, **changes))
                with self.assertRaisesRegex(ValueError, "保留训练时"):
                    planned.select_policy_schedule(spec, policy_checkpoint=self.saved)
        with self.assertRaisesRegex(ValueError, "不能同时"):
            context.select_with_context(self.spec(), policy_checkpoint=self.saved, plant=object())

    def test_declared_development_history_survives_next_plan_and_legacy_checkpoint(self):
        spec = self.spec(previously_used_seeds=(1001, 7001, 7002))
        selected = planned.select_policy_schedule(spec, policy_checkpoint=self.saved)
        tested = planned.test_policy_schedule(selected)
        history = tested["policy_after"]
        self.assertEqual(history["declared_development_seeds"], [7001, 7002])
        planned.history_for(history)
        self.assertTrue({7001, 7002} <= set(history["checkpoint"]["previous_evaluation_seeds"]))
        for value in (history, history["checkpoint"]):
            with self.assertRaisesRegex(ValueError, "编号已经"):
                planned.select_policy_schedule(self.spec(selection_seeds=(7001,), test_seeds=(8001,)), policy_checkpoint=value)

    def test_damaged_choice_initialization_history_and_boolean_seed_are_rejected(self):
        original = planned.select_policy_schedule(self.spec(selection_seeds=(1,)), policy_checkpoint=self.saved)
        variants = []
        for field, value in (("source_sha256", {}), ("initial_state_rule", "random seed initial state"),
                             ("rule", "select with tests"), ("selected_id", "missing")):
            record = deepcopy(original)
            record[field] = value
            variants.append(record)
        record = deepcopy(original)
        record["selection_runs"][0]["controller"]["initialization_config"]["initial_position"] = True
        variants.append(record)
        record = deepcopy(original)
        record["selection_runs"][0]["seed"] = True
        variants.append(record)
        record = deepcopy(original)
        record["policy_after"]["planned_history"][0]["phase"] = "test"
        record["policy_after"]["history_sha256"] = digest({k: v for k, v in record["policy_after"].items() if k != "history_sha256"})
        variants.append(record)
        with patch.object(planned, "simulate", side_effect=AssertionError("invalid choice ran")):
            for record in variants:
                record["record_sha256"] = digest({k: v for k, v in record.items() if k != "record_sha256"})
                with self.assertRaises(ValueError):
                    planned.test_policy_schedule(record)

    def test_no_eligible_choice_keeps_failed_selection_history_without_running_tests(self):
        spec = self.spec(config=replace(self.spec().config, budget=0, initial_position=1, state_limit=1))
        saved = context.select_with_context(spec, policy_checkpoint=self.saved)
        original = deepcopy(saved)
        with patch.object(planned, "simulate", side_effect=AssertionError("no choice must not test")):
            tested = context.test_with_context(saved)
        self.assertEqual(saved, original)
        self.assertEqual(tested["result"]["test_runs"], [])
        self.assertEqual(tested["result"]["policy_after"], saved["result"]["policy_after"])
        self.assertEqual(tested["context"]["test"], {"state": "not_run", "runtime": None})
        self.assertIsNone(saved["result"]["selected_id"])
        self.assertTrue(all(row["run"]["metrics"]["position_rmse"] is None for row in saved["result"]["selection_runs"]))

    def test_test_only_controller_failure_keeps_nulls_choice_and_used_test_history(self):
        saved = planned.select_policy_schedule(self.spec(), policy_checkpoint=self.saved)
        original = QController.__call__
        def fail_test(controller, observation):
            if controller.config.seed in self.spec().test_seeds:
                raise RuntimeError("test controller failure")
            return original(controller, observation)
        with patch.object(QController, "__call__", fail_test):
            tested = planned.test_policy_schedule(saved)
        self.assertEqual(tested["selected_id"], saved["selected_id"])
        self.assertEqual(tested["status"], "did_not_meet_declared_tests")
        self.assertIsNone(tested["selected_summary"]["all_runs_mean_rmse"])
        self.assertTrue(all(row["rmse_selected_minus_periodic"] is None for row in tested["paired_results"]))
        self.assertEqual(tested["policy_after"]["planned_history"][-1]["seeds"], [4001, 4002])

    def test_mutated_table_is_not_exported_as_frozen(self):
        original = QController.__call__
        def mutate(controller, observation):
            controller.table.values[(0, 0)] = (1.0,) * 7
            return original(controller, observation)
        with patch.object(QController, "__call__", mutate), self.assertRaisesRegex(ValueError, "改变了冻结"):
            planned.select_policy_schedule(self.spec(), policy_checkpoint=self.saved)

    def test_report_redraw_and_updated_checkpoint_keep_raw_results_and_phase_history(self):
        choice = planned.select_policy_schedule(self.spec(), policy_checkpoint=self.saved)
        tested = planned.test_policy_schedule(choice)
        with tempfile.TemporaryDirectory() as folder, patch.object(planned, "simulate", side_effect=AssertionError("redraw simulated")):
            for index, value in enumerate((choice, tested)):
                out = Path(folder) / str(index)
                context.export_bundle(value, out)
                self.assertEqual(json.loads((out / "policy-history.json").read_text("utf-8")), value["policy_after"])
                load_checkpoint(json.loads((out / "policy-checkpoint.json").read_text("utf-8")))
                page = (out / "report.html").read_text("utf-8")
                self.assertIn("不再训练", page)
                self.assertIn("不会按种子另抽初态", page)
                self.assertNotIn("这里只使用固定反馈控制器", page)
                self.assertIn("policy-history.json", page)

    def test_web_reuses_same_frozen_record_and_legacy_behavior_is_unchanged(self):
        saved = context.select_with_context(self.spec(), policy_checkpoint=self.saved)
        with patch.object(QTable, "update", side_effect=AssertionError("web trained")):
            response = web_test({"selection": saved})
        self.assertEqual(response["record"], context.test_with_context(saved)["result"])
        self.assertEqual(context.select_with_context(self.spec())["result"], select_schedule(self.spec()))
        with self.assertRaisesRegex(ValueError, "不能更换模型"):
            context.test_with_context(saved, plant=object())

    def test_separate_cli_processes_keep_originals_and_history_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            spec, policy = folder / "spec.json", folder / "policy.json"
            spec.write_text(json.dumps(asdict(self.spec())), encoding="utf-8")
            policy.write_text(json.dumps(self.saved), encoding="utf-8")
            original = policy.read_bytes()
            def invoke(*arguments):
                return subprocess.run([sys.executable, "-m", "event_control_lab.planned_study", *map(str, arguments)],
                                      cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            choice, tested, refused = folder / "choice", folder / "test", folder / "refused"
            empty = folder / "null.json"
            empty.write_text("null", encoding="utf-8")
            missing = invoke("select", "--spec", spec, "--policy-checkpoint", empty, "--out", refused)
            self.assertEqual(missing.returncode, 2)
            self.assertFalse(refused.exists())
            first = invoke("select", "--spec", spec, "--policy-checkpoint", policy, "--out", choice)
            self.assertEqual(first.returncode, 0, first.stderr)
            raw = (choice / "selection-bundle.json").read_bytes()
            second = invoke("test", choice / "selection-bundle.json", "--out", tested)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(policy.read_bytes(), original)
            self.assertEqual((choice / "selection-bundle.json").read_bytes(), raw)
            last = invoke("select", "--spec", spec, "--policy-checkpoint", tested / "policy-history.json", "--out", refused)
            self.assertEqual(last.returncode, 2)
            self.assertIn("编号已经", last.stderr)
            self.assertFalse(refused.exists())
