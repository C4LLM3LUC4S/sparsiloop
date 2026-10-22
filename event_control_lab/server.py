"""Loopback-only UI; no uploaded controllers or remote services."""

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .engine import Config, compare
from .study import StudySpec, study


WEB = Path(__file__).with_name("web")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, data, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/favicon.ico":
            return self.respond(204, b"", "image/x-icon")
        routes = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                  "/style.css": ("style.css", "text/css"), "/study.js": ("study.js", "text/javascript")}
        if self.path in routes:
            name, mime = routes[self.path]
            return self.respond(200, (WEB / name).read_bytes(), mime + "; charset=utf-8")
        if self.path == "/api/default":
            return self.respond(200, json.dumps(asdict(Config())).encode())
        if self.path == "/api/health":
            return self.respond(200, b'{"status":"ok","version":"0.0.1"}')
        self.respond(404, b'{"error":"not found"}')

    def do_POST(self):
        if self.path not in {"/api/compare", "/api/study"}:
            return self.respond(404, b'{"error":"not found"}')
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") not in {host, f"localhost:{self.server.server_port}"}:
            return self.respond(403, b'{"error":"local host required"}')
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host, f"http://localhost:{self.server.server_port}"}:
            return self.respond(403, b'{"error":"same origin required"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("request must contain 1..65536 bytes")
            value = json.loads(self.rfile.read(length))
            result = study(StudySpec.from_dict(value)) if self.path == "/api/study" else compare(Config.from_dict(value))
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError) as exc:
            return self.respond(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode())
        self.respond(200, payload)


def serve(port=8788):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SparsiLoop: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
