"""Model identity, stage boundaries, independent dynamics and complete local reuse."""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config, PlantAdapter
from event_control_lab import planned_context as context, planned_models as models
from event_control_lab import planned_study as legacy
from event_control_lab.web_planned import test_from_web as web_test
from examples.own_model_case import actuator_model


ROOT = Path(__file__).resolve().parents[1]


class PlannedModelTests(unittest.TestCase):
    def spec(self, **changes):
        config = Config(duration=0.8, dt=0.1, budget=8, heartbeat=0.8, delay_steps=0,
                        loss_probability=0, measurement_noise=0, process_noise=0)
        return replace(legacy.PlannedSpec(config=config, absolute_thresholds=(2,),
            relative_thresholds=(2,), selection_seeds=(11, 12), test_seeds=(21, 22), rmse_limit=100), **changes)

    def test_local_model_first_step_matches_independent_ode_calculation(self):
        choice = models.select_model_schedule(self.spec(), plant=actuator_model())
        expected = math.exp(-0.4 * 0.1) - 2 * 1.2 * (-math.expm1(-0.4 * 0.1)) / 0.4
        self.assertAlmostEqual(choice["selection_runs"][0]["run"]["trajectory"][1]["state"][0], expected)
        self.assertEqual(choice["model"]["parameters"]["decay_per_second"], 0.4)
        self.assertEqual(choice["format"], models.FORMAT)

    def test_fresh_model_per_run_and_no_test_seeds_during_selection_or_reselection(self):
        base, initialized = actuator_model(), []
        def factory(config):
            initialized.append(asdict(config))
            return base.factory(config)
        plant = replace(base, factory=factory)
        spec = self.spec()
        choice = context.select_with_context(spec, plant=plant)
        self.assertEqual(len(initialized), 6)
        self.assertEqual({row["seed"] for row in initialized}, {11, 12})
        self.assertEqual(choice["result"]["selected_id"], "absolute-1")
        before = deepcopy(choice)
        tested = context.test_with_context(json.loads(json.dumps(choice)), plant=plant)
        self.assertEqual(choice, before)
        self.assertEqual(len(initialized), 10)
        self.assertEqual({row["seed"] for row in initialized[6:]}, {21, 22})
        self.assertEqual(tested["result"]["selected_id"], "absolute-1")
        self.assertEqual(tested["context"]["selection"], choice["context"]["selection"])
        for seed in spec.test_seeds:
            pair = [row for row in tested["result"]["test_runs"] if row["seed"] == seed]
            self.assertEqual({row["config"]["budget"] for row in pair}, {8})
            self.assertEqual(pair[0]["run"]["trace_sha256"], pair[1]["run"]["trace_sha256"])
        for row in choice["result"]["selection_runs"] + tested["result"]["test_runs"]:
            self.assertEqual(row["run"]["plant_initialization_config"], row["config"])
            self.assertEqual(row["run"]["trajectory"][0]["state"], [1.0])

    def test_missing_or_changed_model_is_rejected_before_simulation(self):
        plant = actuator_model()
        choice = context.select_with_context(self.spec(), plant=plant)
        alternatives = [None, actuator_model(gain=1.3), replace(plant, state_units=("other",)),
                        replace(plant, source_sha256="0" * 64), replace(plant, name="other")]
        with patch.object(models, "simulate", side_effect=AssertionError("must reject before running")):
            for other in alternatives:
                with self.subTest(model=other), self.assertRaises(ValueError):
                    context.test_with_context(choice, plant=other)
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            models.select_model_schedule(self.spec(), plant=replace(plant, source_sha256=None))

    def test_damaged_identity_initialization_and_choice_are_not_silently_accepted(self):
        plant = actuator_model()
        original = models.select_model_schedule(self.spec(), plant=plant)
        variants = []
        for key, value in (("source_sha256", {}), ("rule", "pick using tests"), ("selected_id", "periodic")):
            value_record = deepcopy(original)
            value_record[key] = value
            variants.append(value_record)
        row_changed = deepcopy(original)
        row_changed["selection_runs"][0]["run"]["plant_initialization_config"]["budget"] = 1
        variants.append(row_changed)
        for value in variants:
            value["record_sha256"] = legacy.digest({k: v for k, v in value.items() if k != "record_sha256"})
            with self.subTest(key=value["selected_id"]), self.assertRaises(ValueError), \
                    patch.object(models, "simulate", side_effect=AssertionError("invalid record ran")):
                models.test_model_schedule(value, plant=plant)

    def test_model_failure_is_retained_and_does_not_invent_test_results(self):
        calls = []
        def fail(config):
            calls.append(config.seed)
            raise RuntimeError("original model initialization failed")
        plant = replace(actuator_model(), factory=fail)
        choice = context.select_with_context(self.spec(), plant=plant)
        self.assertIsNone(choice["result"]["selected_id"])
        self.assertEqual(set(calls), {11, 12})
        for row in choice["result"]["selection_runs"]:
            self.assertEqual(row["run"]["status"], "plant_error")
            self.assertIsNone(row["run"]["metrics"]["position_rmse"])
            self.assertIn("original model initialization failed", row["run"]["error"])
        tested = context.test_with_context(choice, plant=plant)
        self.assertEqual(len(calls), 6)
        self.assertEqual(tested["result"]["test_runs"], [])
        self.assertEqual(tested["context"]["test"], {"state": "not_run", "runtime": None})

    def test_boolean_run_ids_and_non_object_traces_are_rejected(self):
        plant = actuator_model()
        original = models.select_model_schedule(self.spec(selection_seeds=(1,)), plant=plant)
        variants = []
        for field in ("seed", "config", "plant_initialization_config"):
            record = deepcopy(original)
            if field == "seed":
                record["selection_runs"][0]["seed"] = True
            elif field == "config":
                record["selection_runs"][0]["config"]["initial_position"] = True
            else:
                record["selection_runs"][0]["run"]["plant_initialization_config"]["initial_position"] = True
            variants.append(record)
        record = deepcopy(original)
        record["selection_traces"] = ["1"]
        variants.append(record)
        for record in variants:
            record["record_sha256"] = legacy.digest({k: v for k, v in record.items() if k != "record_sha256"})
            with self.assertRaises(ValueError), patch.object(models, "simulate", side_effect=AssertionError("invalid record ran")):
                models.test_model_schedule(record, plant=plant)

    def test_test_failure_keeps_the_selected_candidate_and_all_null_metrics(self):
        plant = actuator_model()
        def factory(config):
            if config.seed in (21, 22):
                raise RuntimeError("test-stage failure")
            return plant.factory(config)
        adapted = replace(plant, factory=factory)
        selected = models.select_model_schedule(self.spec(), plant=adapted)
        tested = models.test_model_schedule(selected, plant=adapted)
        self.assertEqual(tested["selected_id"], selected["selected_id"])
        self.assertEqual(tested["status"], "did_not_meet_declared_tests")
        self.assertEqual(len(tested["test_runs"]), 4)
        self.assertIsNone(tested["selected_summary"]["all_runs_mean_rmse"])
        self.assertTrue(all(row["rmse_selected_minus_periodic"] is None for row in tested["paired_results"]))

    def test_raw_records_keep_unknown_environments_and_redraw_without_model_execution(self):
        raw = models.select_model_schedule(self.spec(), plant=actuator_model())
        tested = models.test_model_schedule(raw, plant=actuator_model())
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(models, "simulate", side_effect=AssertionError("redraw simulated")):
            for index, record in enumerate((raw, tested)):
                destination = Path(folder) / str(index)
                manifest = context.export_bundle(record, destination)
                self.assertEqual(manifest["execution"]["selection"]["state"], "not_recorded")
                if index:
                    self.assertEqual(manifest["execution"]["test"]["state"], "not_recorded")
                self.assertEqual(json.loads((destination / "model.json").read_text("utf-8")), raw["model"])
                page = (destination / "report.html").read_text("utf-8")
                self.assertIn("本地模型", page)
                self.assertIn("normalized_displacement", page)
                self.assertNotIn("x&#x27; = x + u", page)
                self.assertIn("首个状态", page)

    def test_legacy_built_in_records_stay_usable_and_cannot_swap_models(self):
        before = legacy.sources()
        choice = legacy.select_schedule(self.spec())
        self.assertEqual(context.select_with_context(self.spec())["result"], choice)
        self.assertEqual(context.test_with_context(choice)["result"], legacy.test_schedule(choice))
        with self.assertRaises(ValueError):
            context.test_with_context(choice, plant=actuator_model())
        self.assertEqual(legacy.sources(), before)

    def test_browser_refuses_local_model_records_without_executing_them(self):
        saved = context.select_with_context(self.spec(), plant=actuator_model())
        with patch.object(models, "simulate", side_effect=AssertionError("browser ran local code")), \
                self.assertRaisesRegex(ValueError, "网页不执行模型代码"):
            web_test({"selection": saved})

    def test_position_velocity_model_and_html_metadata_are_kept_explicit(self):
        def factory(config):
            return lambda state, command, dt: (state[0] + dt * state[1] + dt * dt * command / 2,
                                               state[1] + dt * command)
        plant = PlantAdapter("<script>original fixture</script>", "double_integrator", factory,
            state_units=("m", "m/s"), input_unit="m/s2", source="original unit-test model",
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        spec = self.spec(config=replace(self.spec().config, plant="double_integrator", initial_velocity=-0.3))
        saved = context.select_with_context(spec, plant=plant)
        tested = context.test_with_context(saved, plant=plant)
        self.assertEqual(tested["result"]["status"], "met_declared_tests")
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "report"
            context.export_bundle(tested, destination)
            page = (destination / "report.html").read_text("utf-8")
            self.assertNotIn("<script>", page)
            self.assertIn("&lt;script&gt;", page)
            self.assertIn("m/s", page)
            self.assertIn("-0.3", page)

    def test_separate_source_commands_preserve_parameters_and_reject_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            spec = folder / "spec.json"
            spec.write_text(json.dumps(asdict(self.spec())), encoding="utf-8")
            def invoke(*arguments):
                return subprocess.run([sys.executable, "-m", "examples.planned_model_case", *map(str, arguments)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            chosen, tested, rejected = folder / "choice", folder / "test", folder / "rejected"
            self.assertEqual(invoke("select", "--spec", spec, "--out", chosen).returncode, 0)
            source = chosen / "selection-bundle.json"
            before = source.read_bytes()
            mismatch = invoke("test", source, "--decay", "0.4", "--gain", "1.3", "--out", rejected)
            self.assertEqual(mismatch.returncode, 2)
            self.assertFalse(rejected.exists())
            self.assertIn("不会退回内置模型", mismatch.stderr)
            result = invoke("test", source, "--decay", "0.4", "--gain", "1.2", "--out", tested)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(json.loads((tested / "test.json").read_text("utf-8"))["status"], "met_declared_tests")
