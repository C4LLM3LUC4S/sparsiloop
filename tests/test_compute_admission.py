from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
import unittest
from unittest.mock import Mock, patch

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
    def test_full_server_attempts_503_and_closes_even_if_the_client_disconnects(self):
        for failure in (None, ConnectionAbortedError("client disconnected")):
            with self.subTest(send_failure=failure):
                server = LocalServer(("127.0.0.1", 0), Quiet)
                connection = Mock()
                connection.sendall.side_effect = failure
                try:
                    for _ in range(MAX_CONNECTIONS):
                        self.assertTrue(server.connection_slots.acquire(blocking=False))
                    with patch.object(ThreadingHTTPServer, "process_request") as start_worker, \
                            patch.object(server, "shutdown_request") as close:
                        server.process_request(connection, ("127.0.0.1", 1))
                    start_worker.assert_not_called()
                    close.assert_called_once_with(connection)
                    connection.settimeout.assert_called_once_with(0.25)
                    connection.sendall.assert_called_once()
                    header, payload = connection.sendall.call_args.args[0].split(b"\r\n\r\n", 1)
                    self.assertTrue(header.startswith(b"HTTP/1.0 503 Service Unavailable\r\n"))
                    self.assertIn(b"Retry-After: 1\r\n", header)
                    self.assertIn(f"Content-Length: {len(payload)}".encode(), header)
                    self.assertIn("error", json.loads(payload))
                    self.assertFalse(server.connection_slots.acquire(blocking=False))
                finally:
                    server.server_close()

    def test_worker_limit_rejects_overload_and_recovers_without_restarting(self):
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
            # An early close with unread request bytes can reset the client on
            # Windows. Both outcomes reject work; 503 is best-effort guidance.
            try:
                status, retry, body = request()
            except ConnectionError:
                pass
            else:
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
