from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import unittest

from event_control_lab.server import Handler


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_page_and_static_assets_work_without_external_resources(self):
        for path in ("/", "/app.js", "/style.css", "/study.js", "/policy-memory.js"):
            status, headers, content = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertGreater(len(content), 100)
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

    def test_valid_api_runs_both_objects(self):
        for plant in ("scalar", "double_integrator"):
            status, _, payload = self.request("POST", "/api/compare", json.dumps({"plant": plant}))
            self.assertEqual(status, 200)
            result = json.loads(payload)
            self.assertEqual(len(result["runs"]), 3)
            self.assertEqual(result["config"]["plant"], plant)

    def test_invalid_inputs_return_readable_errors(self):
        for payload in ("{broken", "[]", '{"budget":true}', '{"dt":NaN}', '{"kp":1e308}'):
            status, _, content = self.request("POST", "/api/compare", payload)
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(content))

    def test_cross_origin_post_and_nonlocal_host_are_rejected(self):
        for path in ("/api/compare", "/api/study"):
            status, _, _ = self.request("POST", path, "{}", {"Origin": "https://example.org"})
            self.assertEqual(status, 403)
            status, _, _ = self.request("POST", path, "{}", {"Host": "not-local.example"})
            self.assertEqual(status, 403)

    def test_study_api_retains_all_requested_cases(self):
        value = {"config": {"duration": 1, "budget": 20}, "thresholds": [0.1, 0.2], "seeds": [8, 9]}
        status, _, payload = self.request("POST", "/api/study", json.dumps(value))
        self.assertEqual(status, 200)
        result = json.loads(payload)
        self.assertEqual(len(result["pairs"]), 8)
        self.assertEqual(len(result["runs"]), 16)
        self.assertEqual(result["analysis"], "posthoc-attempted-packet-reference-v1")
        for invalid in ("[]", '{"thresholds":[]}', '{"seeds":[true]}', '{"controller_code":"print(1)"}'):
            status, _, payload = self.request("POST", "/api/study", invalid)
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(payload))

    def test_arbitrary_files_and_controller_code_are_not_exposed(self):
        status, _, _ = self.request("GET", "/../engine.py")
        self.assertEqual(status, 404)
        status, _, _ = self.request("POST", "/api/compare", '{"controller_code":"print(1)"}')
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
