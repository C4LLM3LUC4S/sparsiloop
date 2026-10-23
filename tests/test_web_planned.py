import base64
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
import zipfile

from event_control_lab.engine import Config
from event_control_lab.planned_report import export_selection, export_test
from event_control_lab.planned_study import PlannedSpec, make_trace, select_schedule, test_schedule
from event_control_lab.web_planned import MAX_REQUEST_BYTES
import test_server


class WebPlannedTests(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTests.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTests.tearDownClass.__func__)
    request = test_server.ServerTests.request

    def spec(self, plant="scalar"):
        return PlannedSpec(config=Config(plant=plant, duration=0.2, budget=10, heartbeat=0.2,
                                        measurement_noise=0, process_noise=0, loss_probability=0),
                           absolute_thresholds=(0.1, 2), relative_thresholds=(0.2,),
                           selection_seeds=(91, 92), test_seeds=(93,), rmse_limit=100)

    def post(self, path, value):
        status, _, payload = self.request("POST", path, json.dumps(value))
        self.assertEqual(status, 200, payload[:300])
        return json.loads(payload)

    def archive_matches(self, response, record, testing=False):
        content = base64.b64decode(response["archive_base64"])
        self.assertEqual(hashlib.sha256(content).hexdigest(), response["archive_sha256"])
        with zipfile.ZipFile(io.BytesIO(content)) as archive, tempfile.TemporaryDirectory() as temporary:
            self.assertIsNone(archive.testzip())
            (export_test if testing else export_selection)(record, Path(temporary) / "direct")
            files = {path.name: path.read_bytes() for path in (Path(temporary) / "direct").iterdir()}
            self.assertEqual(set(archive.namelist()), set(files))
            for name, data in files.items():
                self.assertEqual(archive.read(name), data, name)
                self.assertEqual(name, Path(name).name)

    def test_complete_choice_and_report_match_direct_api_for_both_models(self):
        for plant in ("scalar", "double_integrator"):
            spec = self.spec(plant)
            with self.subTest(plant=plant):
                direct = json.loads(json.dumps(select_schedule(spec)))
                response = self.post("/api/planned/select", {"spec": asdict(spec)})
                self.assertEqual(response["record"], direct)
                self.archive_matches(response, direct)

    def test_stages_use_only_declared_seeds_and_testing_does_not_reselect(self):
        spec, seen = self.spec(), []
        def trace(config):
            seen.append(config.seed)
            return make_trace(config)
        with patch("event_control_lab.planned_study.make_trace", side_effect=trace):
            chosen = self.post("/api/planned/select", {"spec": asdict(spec)})["record"]
        self.assertEqual(seen, list(spec.selection_seeds))
        before = deepcopy(chosen)
        seen.clear()
        with patch("event_control_lab.planned_study.make_trace", side_effect=trace), patch(
                "event_control_lab.web_planned.select_schedule", side_effect=AssertionError("no reselection")):
            response = self.post("/api/planned/test", {"selection": chosen})
        self.assertEqual(seen, list(spec.test_seeds))
        self.assertEqual(chosen, before)
        self.assertEqual(response["record"], json.loads(json.dumps(test_schedule(chosen))))
        self.archive_matches(response, response["record"], testing=True)

    def test_complete_large_record_can_be_reused_without_truncation(self):
        spec = PlannedSpec(config=Config(plant="double_integrator", duration=4, budget=60),
                           absolute_thresholds=tuple(x/10 for x in range(8)),
                           relative_thresholds=tuple(x/10 for x in range(8)),
                           selection_seeds=(1, 2, 3, 4, 5), test_seeds=(6, 7, 8, 9, 10), rmse_limit=100)
        choice = self.post("/api/planned/select", {"spec": asdict(spec)})["record"]
        body = json.dumps({"selection": choice})
        self.assertGreater(len(body), 2*1024*1024)
        self.assertLess(len(body), MAX_REQUEST_BYTES)
        response = self.post("/api/planned/test", {"selection": choice})
        self.assertEqual(response["record"]["selection"], choice)
        self.assertEqual(len(choice["selection_runs"]), 85)
        self.archive_matches(response, response["record"], testing=True)

    def test_failed_runs_and_unknown_scores_remain_and_no_choice_does_not_test(self):
        spec = replace(self.spec(), config=Config(duration=0.2, budget=0, heartbeat=0.2,
                       initial_position=5, state_limit=5, measurement_noise=0, process_noise=0))
        choice = self.post("/api/planned/select", {"spec": asdict(spec)})["record"]
        self.assertIsNone(choice["selected_id"])
        self.assertTrue(all(row["run"]["status"] == "state_limit" for row in choice["selection_runs"]))
        self.assertTrue(all(row["run"]["metrics"]["position_rmse"] is None for row in choice["selection_runs"]))
        with patch("event_control_lab.planned_study.make_trace", side_effect=AssertionError("test must not run")):
            response = self.post("/api/planned/test", {"selection": choice})
        self.assertEqual(response["record"]["test_runs"], [])
        self.assertEqual(response["record"]["status"], "not_run_no_eligible_choice")

    def test_web_time_and_total_work_limits_reject_before_simulation(self):
        spec = self.spec()
        oversized = PlannedSpec(config=Config(duration=8, budget=40),
            absolute_thresholds=tuple(x/10 for x in range(8)),
            relative_thresholds=tuple(x/10 for x in range(8)),
            selection_seeds=(1, 2, 3, 4, 5), test_seeds=(6, 7, 8, 9, 10))
        values = [[], {"spec": asdict(spec), "python": "print(1)"},
                  {"spec": asdict(replace(spec, config=replace(spec.config, dt=0.01)))},
                  {"spec": asdict(oversized)}, {"spec": {"selection_seeds": [1], "test_seeds": [1]}}]
        with patch("event_control_lab.web_planned.select_schedule", side_effect=AssertionError("reject before running")):
            for value in values:
                status, _, payload = self.request("POST", "/api/planned/select", json.dumps(value))
                self.assertEqual(status, 400, payload[:300])

    def test_test_endpoint_rejects_new_conditions_corruption_and_wrong_source(self):
        choice = json.loads(json.dumps(select_schedule(self.spec())))
        damaged = deepcopy(choice)
        damaged["spec"]["test_seeds"] = [9001]
        values = [{"selection": choice, "seeds": [9001]}, {"selection": choice, "config": {}},
                  {"selection": damaged}, {"selection": {}}, {"selection": None}]
        with patch("event_control_lab.web_planned.test_schedule", side_effect=AssertionError("reject before testing")):
            for value in values:
                status, _, payload = self.request("POST", "/api/planned/test", json.dumps(value))
                self.assertEqual(status, 400, payload[:300])
            with patch("event_control_lab.planned_study.sources", return_value={}):
                status, _, payload = self.request("POST", "/api/planned/test", json.dumps({"selection": choice}))
                self.assertEqual(status, 400)
                self.assertIn("计算代码", json.loads(payload)["error"])

    def test_local_origin_body_limits_and_malformed_json(self):
        for route in ("/api/planned/select", "/api/planned/test"):
            for headers in ({"Origin": "https://example.org"}, {"Host": "example.org"}):
                self.assertEqual(self.request("POST", route, "{}", headers)[0], 403)
            for data in ("{broken", "[]", "null"):
                self.assertEqual(self.request("POST", route, data)[0], 400)
        status, _, payload = self.request("POST", "/api/planned/test", " "*(MAX_REQUEST_BYTES+1))
        self.assertEqual(status, 400)
        self.assertIn("8 MiB", json.loads(payload)["error"])

    def test_cross_tab_shared_slot_recovers_after_error(self):
        entered, release, responses = Event(), Event(), []
        def blocked(value):
            entered.set()
            if not release.wait(5):
                raise ValueError("test did not release")
            raise ValueError("test failure")
        with patch("event_control_lab.web_planned.select_from_web", side_effect=blocked):
            worker = Thread(target=lambda:responses.append(self.request("POST", "/api/planned/select", "{}")))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                for route in ("/api/planned/test", "/api/controllers", "/api/evaluate-policy"):
                    self.assertEqual(self.request("POST", route, "{}")[0], 429)
            finally:
                release.set()
                worker.join(5)
        self.assertEqual(responses[0][0], 400)
        self.post("/api/planned/select", {"spec": asdict(self.spec())})

    def test_defaults_and_script_are_included_and_do_not_require_remote_resources(self):
        status, headers, content = self.request("GET", "/planned.js")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertIn(b"/api/planned/", content)
        status, _, content = self.request("GET", "/api/planned/default")
        self.assertEqual(status, 200)
        spec = PlannedSpec.from_dict(json.loads(content))
        self.assertEqual(spec.config.dt, 0.02)


if __name__ == "__main__":
    unittest.main()
