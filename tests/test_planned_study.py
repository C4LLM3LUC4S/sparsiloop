import copy
import csv
from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config
from event_control_lab import planned_study as planned
from event_control_lab.planned_report import export_selection, export_test


class PlannedStudyTests(unittest.TestCase):
    def spec(self, **changes):
        config = Config(duration=0.8, dt=0.1, budget=8, heartbeat=0.8,
                        delay_steps=0, measurement_noise=0, process_noise=0, loss_probability=0)
        return replace(planned.PlannedSpec(config=config, absolute_thresholds=(2,),
                                          relative_thresholds=(2,), selection_seeds=(11, 12),
                                          test_seeds=(21, 22), rmse_limit=100), **changes)

    def test_declared_split_and_limits_reject_before_execution(self):
        for changes in ({"test_seeds": (11,)}, {"previously_used_seeds": (21,)},
                        {"selection_seeds": (True,)}, {"test_seeds": (21, 21)},
                        {"absolute_thresholds": (0.2, 0.2)}, {"rmse_limit": float("nan")},
                        {"rmse_limit": True}, {"relative_thresholds": (float("inf"),)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.spec(**changes)
        with self.assertRaises(ValueError):
            planned.PlannedSpec(config=Config(dt=0.002, duration=10, budget=10))
        with self.assertRaises(ValueError):
            planned.PlannedSpec.from_dict({"winner": "periodic"})

    def test_select_does_not_touch_test_seeds_and_fixes_choice_before_test(self):
        spec = self.spec()
        calls = []
        original = planned.simulate

        def observed(config, policy, **kwargs):
            calls.append(config.seed)
            return original(config, policy, **kwargs)

        with patch.object(planned, "simulate", side_effect=observed):
            record = planned.select_schedule(spec)
        self.assertEqual(set(calls), {11, 12})
        self.assertEqual(len(record["selection_runs"]), 6)
        self.assertEqual(record["selected_id"], "absolute-1")
        before = copy.deepcopy(record)
        with patch.object(planned, "simulate", side_effect=observed):
            result = planned.test_schedule(record)
        self.assertEqual(set(calls[6:]), {21, 22})
        self.assertEqual(record, before)
        self.assertEqual(result["selected_id"], "absolute-1")
        for seed in spec.test_seeds:
            pair = [row for row in result["test_runs"] if row["seed"] == seed]
            self.assertEqual(len(pair), 2)
            self.assertEqual({row["config"]["budget"] for row in pair}, {8})
            self.assertEqual(pair[0]["run"]["trace_sha256"], pair[1]["run"]["trace_sha256"])
            self.assertLess(pair[0]["run"]["packets"]["attempted"], pair[1]["run"]["packets"]["attempted"])
        # Changing test outcomes cannot make the fixed selection switch to its reference.
        def failed(config, policy, **kwargs):
            run = original(config, policy, **kwargs)
            if policy == "absolute":
                run.update(status="controller_error", error="test-only injected failure")
                run["metrics"]["position_rmse"] = None
            return run
        with patch.object(planned, "simulate", side_effect=failed):
            rejected = planned.test_schedule(record)
        self.assertEqual(rejected["selected_id"], "absolute-1")
        self.assertEqual(rejected["status"], "did_not_meet_declared_tests")
        self.assertIsNone(rejected["selected_summary"]["all_runs_mean_rmse"])
        self.assertTrue(all(row["rmse_selected_minus_periodic"] is None for row in rejected["paired_results"]))

    def test_hand_computed_objective_ties_and_failed_metrics(self):
        def row(value, attempts, status="complete"):
            return {"run": {"status": status, "metrics": {"position_rmse": value},
                            "packets": {"attempted": attempts}}}
        summary = planned.summarize([row(0.2, 2), row(0.4, 4)], 0.4)
        self.assertEqual(summary["all_requested_mean_attempts"], 3)
        self.assertAlmostEqual(summary["all_runs_mean_rmse"], 0.3)
        self.assertEqual(summary["all_runs_max_rmse"], 0.4)
        self.assertTrue(summary["eligible"])
        one_exceeds = planned.summarize([row(0.1, 2), row(0.5, 4)], 0.4)
        self.assertAlmostEqual(one_exceeds["all_runs_mean_rmse"], 0.3)
        self.assertFalse(one_exceeds["eligible"])
        failed = planned.summarize([row(0.2, 2), row(None, 0, "state_limit")], 100)
        self.assertFalse(failed["eligible"])
        self.assertIsNone(failed["all_runs_mean_rmse"])
        self.assertEqual(failed["complete"], 1)
        self.assertEqual(failed["all_requested_mean_attempts"], 1)
        candidates = [{"id": "first", **summary}, {"id": "same", **summary},
                      {"id": "failed-cheap", **failed}]
        self.assertEqual(planned.choose(candidates), "first")
        candidates[1]["all_runs_mean_rmse"] = 0.25
        self.assertEqual(planned.choose(candidates), "same")
        candidates[0]["all_requested_mean_attempts"] = 2
        self.assertEqual(planned.choose(candidates), "first")

    def test_no_feasible_choice_keeps_test_seeds_unused_and_periodic_is_not_duplicated(self):
        record = planned.select_schedule(self.spec(rmse_limit=1e-8))
        self.assertIsNone(record["selected_id"])
        with patch.object(planned, "simulate", side_effect=AssertionError("tests must stay unused")):
            result = planned.test_schedule(record)
        self.assertEqual(result["status"], "not_run_no_eligible_choice")
        self.assertEqual(result["test_runs"], [])
        self.assertIsNone(result["selected_summary"])
        periodic = planned.test_schedule(planned.select_schedule(self.spec(absolute_thresholds=(), relative_thresholds=())))
        self.assertEqual(len(periodic["test_runs"]), 2)
        self.assertTrue(all(row["roles"] == ["selected", "periodic_reference"] for row in periodic["test_runs"]))
        self.assertEqual(periodic["selected_summary"], periodic["reference_summary"])

    def test_corrupt_reselected_and_different_source_records_are_rejected(self):
        source = planned.select_schedule(self.spec())
        self.assertEqual(planned.load_selection(json.loads(json.dumps(source))), self.spec())
        for field, value in (("selected_id", "periodic"), ("rule", "select best test")):
            changed = copy.deepcopy(source)
            changed[field] = value
            with self.assertRaises(ValueError):
                planned.load_selection(changed)
            changed["record_sha256"] = planned.digest({key: item for key, item in changed.items() if key != "record_sha256"})
            with self.assertRaises(ValueError):
                planned.load_selection(changed)
        changed = copy.deepcopy(source)
        changed["spec"]["test_seeds"] = [11]
        changed["record_sha256"] = planned.digest({key: item for key, item in changed.items() if key != "record_sha256"})
        with self.assertRaises(ValueError):
            planned.load_selection(changed)
        with patch.object(planned, "sources", return_value={"engine.py": "different"}):
            with self.assertRaises(ValueError):
                planned.load_selection(source)
        self.assertNotIn("planned_report.py", source["source_sha256"])
        self.assertNotIn("planned_cli.py", source["source_sha256"])

    def test_fresh_process_commands_preserve_input_and_existing_outputs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="Planned choice 空格 ") as temp:
            base = Path(temp)
            specfile = base / "plan.json"
            specfile.write_text(json.dumps(asdict(self.spec())), encoding="utf-8-sig")
            selection, testing = base / "选择", base / "测试"
            env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="ascii")

            def command(*args):
                return subprocess.run([sys.executable, "-m", "event_control_lab.planned_study", *args],
                                      cwd=root, env=env, capture_output=True, encoding="utf-8", timeout=20)

            chosen = command("select", "--spec", str(specfile), "--out", str(selection))
            self.assertEqual(chosen.returncode, 0, chosen.stderr)
            self.assertIn("测试种子还没有运行", chosen.stdout)
            raw = (selection / "selection.json").read_bytes()
            tested = command("test", str(selection / "selection.json"), "--out", str(testing))
            self.assertEqual(tested.returncode, 0, tested.stderr)
            self.assertIn("这次声明的测试", tested.stdout)
            result = json.loads((testing / "test.json").read_text(encoding="utf-8"))
            self.assertEqual({row["seed"] for row in result["test_runs"]}, {21, 22})
            self.assertEqual(raw, (selection / "selection.json").read_bytes())
            original = (testing / "report.html").read_bytes()
            self.assertEqual(command("test", str(selection / "selection.json"), "--out", str(testing)).returncode, 2)
            self.assertEqual(original, (testing / "report.html").read_bytes())
            info = json.loads((testing / "input-info.json").read_text(encoding="utf-8"))
            self.assertEqual(info["input_sha256"], hashlib.sha256(raw).hexdigest())
            invalid = command("test", str(specfile), "--out", str(base / "invalid"))
            self.assertEqual(invalid.returncode, 2)
            self.assertFalse((base / "invalid").exists())

    def test_reports_retain_failures_and_null_csv_without_overwrite(self):
        bad = self.spec(config=replace(self.spec().config, kp=0, state_limit=1.1))
        record = planned.select_schedule(bad)
        self.assertTrue(all(row["run"]["status"] == "state_limit" for row in record["selection_runs"]))
        record["selection_runs"][0]["run"]["error"] = "<script>unsafe</script>"
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            export_selection(record, folder / "selection")
            page = (folder / "selection/report.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn("<script>", page)
            with (folder / "selection/runs.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 6)
            self.assertTrue(all(row["position_rmse"] == "" for row in rows))
            good = planned.test_schedule(planned.select_schedule(self.spec()))
            export_test(good, folder / "test")
            self.assertIn("所选方案", (folder / "test/report.html").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                export_test(good, folder / "test")


if __name__ == "__main__":
    unittest.main()
