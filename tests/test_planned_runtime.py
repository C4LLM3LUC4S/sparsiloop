from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_control_lab import Config
from event_control_lab import planned_study as planned
from event_control_lab import planned_context as context


def runtime(version, system, second):
    return {"python_implementation": "CPython", "python_version": version, "os_family": system,
            "python_pointer_bits": 64, "sparsiloop_version": "0.0.1", "float_radix": 2,
            "float_mantissa_bits": 53, "captured_at_utc": f"2026-10-23T02:00:{second:02d}+00:00"}


A = runtime("3.10.19", "Linux", 1)
B = runtime("3.12.5", "Windows", 2)
C = runtime("3.14.0", "macOS", 3)


class PlannedRuntimeTests(unittest.TestCase):
    def spec(self, **changes):
        return replace(planned.PlannedSpec(config=Config(duration=0.8, dt=0.1, budget=8, heartbeat=0.8,
            delay_steps=0, measurement_noise=0, process_noise=0, loss_probability=0),
            absolute_thresholds=(2,), relative_thresholds=(2,), selection_seeds=(11,), test_seeds=(21,), rmse_limit=100), **changes)

    def test_selection_test_and_redraw_environments_are_distinct_without_numeric_changes(self):
        spec = self.spec()
        original_sources = planned.sources()
        with patch.object(context, "runtime_info", return_value=A):
            chosen = context.select_with_context(spec)
        before = deepcopy(chosen)
        self.assertEqual(chosen["result"], planned.select_schedule(spec))
        with patch.object(context, "runtime_info", return_value=B):
            tested = context.test_with_context(chosen)
        self.assertEqual(tested["result"], planned.test_schedule(chosen["result"]))
        self.assertEqual(chosen, before)
        self.assertEqual(tested["context"]["selection"]["runtime"], A)
        self.assertEqual(tested["context"]["test"]["runtime"], B)
        self.assertEqual(planned.sources(), original_sources)
        with tempfile.TemporaryDirectory() as temporary, patch.object(context, "runtime_info", return_value=C), \
                patch.object(planned, "simulate", side_effect=AssertionError("redraw must not simulate")):
            output = Path(temporary) / "redrawn"
            manifest = context.export_bundle(tested, output)
            self.assertEqual(manifest["execution"], tested["context"])
            self.assertEqual(manifest["report_rendering"], C)
            self.assertEqual(json.loads((output / "test.json").read_text()), json.loads(json.dumps(tested["result"])))
            page = (output / "report.html").read_text(encoding="utf-8")
            for version in ("3.10.19", "3.12.5", "3.14.0"):
                self.assertIn(version, page)
            self.assertEqual(context.as_bundle(json.loads((output / "selection-bundle.json").read_text()))["context"], chosen["context"])

    def test_old_records_keep_unknown_execution_when_rendered_and_when_tested(self):
        choice = planned.select_schedule(self.spec())
        testing = planned.test_schedule(choice)
        before = deepcopy([choice, testing])
        with tempfile.TemporaryDirectory() as temporary, patch.object(context, "runtime_info", return_value=C), \
                patch.object(planned, "simulate", side_effect=AssertionError("render must not run")):
            for name, record in (("choice", choice), ("test", testing)):
                manifest = context.export_bundle(record, Path(temporary) / name)
                self.assertEqual(manifest["execution"]["selection"], {"state": "not_recorded", "runtime": None})
                if name == "test":
                    self.assertEqual(manifest["execution"]["test"], {"state": "not_recorded", "runtime": None})
                self.assertEqual(manifest["report_rendering"], C)
        with patch.object(context, "runtime_info", return_value=B):
            result = context.test_with_context(choice)
        self.assertEqual(result["context"]["selection"]["state"], "not_recorded")
        self.assertIsNone(result["context"]["selection"]["runtime"])
        self.assertEqual(result["context"]["test"]["runtime"], B)
        self.assertEqual([choice, testing], before)

    def test_context_binding_and_checksum_refuse_spliced_results_or_edited_metadata(self):
        chosen = context.select_with_context(self.spec())
        other = planned.select_schedule(self.spec(test_seeds=(31,)))
        values = []
        stale = deepcopy(chosen)
        stale["result"] = other
        values.append(stale)
        damaged = deepcopy(chosen)
        damaged["context"]["selection"]["runtime"]["python_version"] = "0.0"
        values.append(damaged)
        invalid = deepcopy(chosen)
        invalid["context"]["selection"]["state"] = []
        invalid["context"]["context_sha256"] = planned.digest({k:v for k,v in invalid["context"].items() if k!="context_sha256"})
        values.append(invalid)
        with patch.object(context, "test_schedule", side_effect=AssertionError("invalid context must not test")):
            for value in values:
                with self.subTest(value=values.index(value)), self.assertRaises(ValueError):
                    context.test_with_context(value)

    def test_unknown_environment_cannot_be_relabelled_with_current_runtime(self):
        value = context.as_bundle(planned.select_schedule(self.spec()))
        value["context"]["selection"]["runtime"] = A
        value["context"]["context_sha256"] = planned.digest({k:v for k,v in value["context"].items() if k!="context_sha256"})
        with self.assertRaisesRegex(ValueError, "不能补上当前环境"):
            context.as_bundle(value)

    def test_no_eligible_choice_has_no_test_runtime_and_does_not_consume_test_seeds(self):
        with patch.object(context, "runtime_info", return_value=A):
            chosen = context.select_with_context(self.spec(rmse_limit=1e-8))
        with patch.object(context, "runtime_info", return_value=B), \
                patch.object(planned, "simulate", side_effect=AssertionError("test seeds must not run")):
            tested = context.test_with_context(chosen)
        self.assertEqual(tested["context"]["test"], {"state": "not_run", "runtime": None})
        self.assertEqual(tested["result"]["test_runs"], [])
        context.as_bundle(tested)

    def test_json_numeric_notation_does_not_invalidate_context_but_real_change_does(self):
        selected = context.select_with_context(self.spec())
        body = json.dumps(selected)
        changed_notation = body.replace('"initial_position": 1.0', '"initial_position": 1')
        self.assertNotEqual(body, changed_notation)
        context.as_bundle(json.loads(changed_notation))
        different = deepcopy(selected)
        different["result"]["spec"]["config"]["initial_position"] = 1.1
        with self.assertRaises(ValueError):
            context.as_bundle(different)

    def test_runtime_capture_is_allowlisted_and_does_not_query_hostname_or_private_environment(self):
        with patch.object(platform, "uname", side_effect=AssertionError("do not query host identity")), \
                patch.dict("os.environ", {"PRIVATE_TEST_SECRET":"must-not-appear", "USERPROFILE":"private-path-marker"}):
            actual = context.runtime_info()
        context.validate_runtime(actual)
        self.assertEqual(set(actual), context.RUNTIME_FIELDS)
        self.assertNotIn("must-not-appear", json.dumps(actual))
        self.assertNotIn("private-path-marker", json.dumps(actual))
        self.assertEqual(actual["python_version"], platform.python_version())

    def test_fresh_process_cli_preserves_bundle_lineage_render_does_not_rerun_and_bad_file_recovers(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="Runtime context 空格 ") as temporary:
            base = Path(temporary)
            plan = base / "spec.json"
            plan.write_text(json.dumps(asdict(self.spec())), encoding="utf-8")
            def command(*arguments):
                return subprocess.run([sys.executable, "-m", "event_control_lab.planned_study", *arguments],
                    cwd=root, capture_output=True, encoding="utf-8", timeout=20)
            selected = command("select", "--spec", str(plan), "--out", str(base / "choice"))
            self.assertEqual(selected.returncode, 0, selected.stderr)
            original = (base / "choice/selection-bundle.json").read_bytes()
            tested = command("test", str(base / "choice/selection-bundle.json"), "--out", str(base / "test"))
            self.assertEqual(tested.returncode, 0, tested.stderr)
            self.assertEqual((base / "choice/selection-bundle.json").read_bytes(), original)
            a = json.loads(original)["context"]["selection"]
            b = json.loads((base / "test/test-bundle.json").read_text())["context"]
            self.assertEqual(a, b["selection"])
            self.assertEqual(b["test"]["state"], "recorded")
            redrawn = command("render", str(base / "test/test-bundle.json"), "--out", str(base / "redrawn"))
            self.assertEqual(redrawn.returncode, 0, redrawn.stderr)
            self.assertIn("没有运行选择或测试", redrawn.stdout)
            self.assertEqual((base / "redrawn/test.json").read_bytes(), (base / "test/test.json").read_bytes())
            self.assertEqual(json.loads((base / "redrawn/environment.json").read_text())["execution"], b)
            target = base / "redrawn/report.html"
            checksum = hashlib.sha256(target.read_bytes()).hexdigest()
            self.assertEqual(command("render", str(plan), "--out", str(base / "redrawn")).returncode, 2)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), checksum)
            self.assertEqual(command("render", str(plan), "--out", str(base / "bad")).returncode, 2)
            self.assertFalse((base / "bad").exists())


if __name__ == "__main__":
    unittest.main()
