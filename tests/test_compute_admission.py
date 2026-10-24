from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
import unittest
from unittest.mock import patch

from event_control_lab.server import Handler, LocalServer, MAX_CONNECTIONS


class Quiet(Handler):
    def log_message(self, *args):
        pass


class ComputeAdmissionTests(unittest.TestCase):
    def request(self, path, body=b"{}", method="POST"):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body if method == "POST" else None)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_compare_blocks_every_other_compute_route_before_json_decoding(self):
        entered, release = Event(), Event()
        replies = []

        def occupied(config):
            if entered.is_set():
                return {"marker": "unexpected concurrent compute"}
            entered.set()
            if not release.wait(10):
                raise ValueError("fixture not released")
            return {"marker": "first request completed"}

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        serving = Thread(target=self.server.serve_forever, daemon=True)
        serving.start()
        worker = Thread(target=lambda: replies.append(self.request("/api/compare")))
        try:
            with patch("event_control_lab.server.compare", side_effect=occupied):
                worker.start()
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.request("/api/compare")[0], 429)
                for path in ("/api/compare", "/api/study", "/api/controllers", "/api/evaluate-policy",
                             "/api/planned/select", "/api/planned/test"):
                    status, payload = self.request(path, b"not JSON")
                    self.assertEqual(status, 429, path)
                    self.assertIn("error", json.loads(payload))
                self.assertEqual(self.request("/api/health", method="GET")[0], 200)
                release.set()
                worker.join(5)
            self.assertEqual(replies[0][0], 200)
            self.assertEqual(self.request("/api/compare", b"[]")[0], 400)
            self.assertEqual(self.request("/api/compare")[0], 200)
        finally:
            release.set()
            if worker.ident:
                worker.join(5)
            self.server.shutdown()
            self.server.server_close()
            serving.join(5)


class ConnectionAdmissionTests(unittest.TestCase):
    def test_worker_limit_returns_503_and_recovers_without_restarting(self):
        entered, release, lock = Event(), Event(), Lock()
        active = 0
        peak = 0
        replies = []

        class Held(Quiet):
            def do_GET(self):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                    if active == MAX_CONNECTIONS:
                        entered.set()
                try:
                    if not release.wait(10):
                        raise AssertionError("fixture not released")
                    super().do_GET()
                finally:
                    with lock:
                        active -= 1

        server = LocalServer(("127.0.0.1", 0), Held)
        serving = Thread(target=server.serve_forever, daemon=True)
        serving.start()

        def request():
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                body = json.loads(response.read())
                return response.status, response.getheader("Retry-After"), body
            finally:
                connection.close()

        workers = [Thread(target=lambda: replies.append(request())) for _ in range(MAX_CONNECTIONS)]
        try:
            for worker in workers:
                worker.start()
            self.assertTrue(entered.wait(5))
            status, retry, body = request()
            self.assertEqual(status, 503)
            self.assertEqual(retry, "1")
            self.assertIn("error", body)
            self.assertEqual(peak, MAX_CONNECTIONS)
            release.set()
            for worker in workers:
                worker.join(5)
            self.assertEqual(len(replies), MAX_CONNECTIONS)
            self.assertTrue(all(reply[0] == 200 for reply in replies))
            self.assertEqual(request()[0], 200)
        finally:
            release.set()
            for worker in workers:
                if worker.ident:
                    worker.join(5)
            server.shutdown()
            server.server_close()
            serving.join(5)


if __name__ == "__main__":
    unittest.main()
