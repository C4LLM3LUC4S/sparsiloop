import base64
from dataclasses import asdict, replace
import io
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch
import zipfile

from event_control_lab.controller_lab import ControllerLabSpec, controller_lab
from event_control_lab.policy import evaluate_policy, load_checkpoint
from event_control_lab.web_recipes import run_recipes
import test_server


def contents(response):
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(response["archive_base64"]))) as archive:
        if archive.testzip() is not None:
            raise AssertionError("broken report archive")
        return {name: archive.read(name) for name in archive.namelist()}


class WebRecipeTests(unittest.TestCase):
    setUpClass = classmethod(test_server.ServerTests.setUpClass.__func__)
    tearDownClass = classmethod(test_server.ServerTests.tearDownClass.__func__)
    request = test_server.ServerTests.request

    def spec(self):
        spec = ControllerLabSpec()
        return replace(spec, config=replace(spec.config, duration=0.2, budget=10),
                       ilc_trials=2, training_seeds=(101, 102), evaluation_seeds=(1001,))

    def test_all_methods_and_zip_match_the_same_direct_recipe(self):
        spec = self.spec()
        for method in ("mfac", "ilc", "rl", "all"):
            with self.subTest(method=method):
                status, _, payload = self.request("POST", "/api/controllers", json.dumps({"method":method,"spec":asdict(spec)}))
                self.assertEqual(status, 200, payload[:200])
                response = json.loads(payload)
                files = contents(response)
                direct = json.loads(json.dumps(controller_lab(spec, method)))
                self.assertEqual(json.loads(files["controllers.json"]), direct)
                self.assertIn(b"download", files["report.html"])
                self.assertEqual(len([r for r in response["rows"] if r["stage"]=="training"]), 2 if method in ("all","rl") else 0)

    def test_load_then_test_preserves_policy_and_updates_downloaded_history(self):
        response = run_recipes({"method":"rl", "spec":json.loads(json.dumps(asdict(self.spec())))})
        source = json.dumps(response["checkpoint"], sort_keys=True)
        status, _, payload = self.request("POST", "/api/evaluate-policy", json.dumps({"checkpoint":response["checkpoint"],"seeds":[2001]}))
        self.assertEqual(status, 200, payload[:200])
        result = json.loads(payload)
        files = contents(result)
        direct = evaluate_policy(response["checkpoint"], [2001])
        self.assertEqual(json.loads(files["evaluation.json"]), json.loads(json.dumps(direct)))
        self.assertEqual(len(result["rows"]), 6)
        self.assertTrue(all(r["stage"]!="training" for r in result["rows"]))
        self.assertEqual(json.dumps(response["checkpoint"], sort_keys=True), source)
        saved = json.loads(files["policy-checkpoint.json"])
        load_checkpoint(saved)
        self.assertEqual(saved["previous_evaluation_seeds"], [1001,2001])
        self.assertEqual(result["checkpoint"], saved)
        status, _, _ = self.request("POST", "/api/evaluate-policy", json.dumps({"checkpoint":saved,"seeds":[2001]}))
        self.assertEqual(status, 400)

    def test_invalid_oversized_unsupported_and_executable_payloads_do_not_run(self):
        requests = [[], {"method":"python"}, {"controller_code":"raise RuntimeError()"},
                    {"spec":{"config":{"dt":0.01,"duration":0.2,"budget":20}}},
                    {"spec":{"training_seeds":list(range(129))}}, {"spec":{"ilc_trials":31}}]
        with patch("event_control_lab.web_recipes.controller_lab", side_effect=AssertionError("must reject before running")):
            for value in requests:
                status, _, _ = self.request("POST", "/api/controllers", json.dumps(value))
                self.assertEqual(status, 400, value)
        for route in ("/api/controllers", "/api/evaluate-policy"):
            status, _, _ = self.request("POST", route, "{}", {"Origin":"https://example.org"})
            self.assertEqual(status, 403)
            status, _, _ = self.request("POST", route, "[]")
            self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/evaluate-policy", " "*(2*1024*1024+1))
        self.assertEqual(status, 400)

    def test_another_tab_receives_busy_and_slot_recovers_after_failure(self):
        entered, release = Event(), Event()
        responses = []
        def blocked(value):
            entered.set()
            if not release.wait(5):
                raise ValueError("test did not release")
            raise ValueError("invalid test fixture")
        with patch("event_control_lab.server.run_recipes", side_effect=blocked):
            worker = Thread(target=lambda:responses.append(self.request("POST","/api/controllers","{}")))
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.request("POST","/api/controllers","{}")[0], 429)
            finally:
                release.set()
                worker.join(5)
        self.assertEqual(responses[0][0], 400)
        self.assertEqual(self.request("POST","/api/controllers", json.dumps({"method":"mfac","spec":asdict(self.spec())}))[0], 200)

    def test_report_links_resolve_inside_extracted_zip_and_no_files_escape(self):
        files = contents(run_recipes({"method":"rl", "spec":json.loads(json.dumps(asdict(self.spec()))) }))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, data in files.items():
                self.assertEqual(Path(name).name,name)
                (root/name).write_bytes(data)
            self.assertTrue((root/"policy-checkpoint.json").is_file())
            self.assertTrue((root/"report.html").is_file())
        for route in ("/controllers.js", "/api/controllers/default"):
            self.assertEqual(self.request("GET",route)[0],200)


if __name__ == "__main__":
    unittest.main()
