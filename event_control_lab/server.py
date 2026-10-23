"""Loopback-only UI; no uploaded controllers or remote services."""

from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import BoundedSemaphore

from .engine import Config, compare
from .study import StudySpec, study
from .web_recipes import default_specification, error_message, run_recipes, test_saved_policy
from . import web_planned


WEB = Path(__file__).with_name("web")
RECIPE_SLOT = BoundedSemaphore(1)


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
                  "/style.css": ("style.css", "text/css"), "/study.js": ("study.js", "text/javascript"),
                  "/controllers.js": ("controllers.js", "text/javascript"),
                  "/planned.js": ("planned.js", "text/javascript")}
        if self.path in routes:
            name, mime = routes[self.path]
            return self.respond(200, (WEB / name).read_bytes(), mime + "; charset=utf-8")
        if self.path == "/api/default":
            return self.respond(200, json.dumps(asdict(Config())).encode())
        if self.path == "/api/health":
            return self.respond(200, b'{"status":"ok","version":"0.0.1"}')
        if self.path == "/api/controllers/default":
            return self.respond(200, json.dumps(default_specification()).encode())
        if self.path == "/api/planned/default":
            return self.respond(200, json.dumps(web_planned.default_specification()).encode())
        self.respond(404, b'{"error":"not found"}')

    def do_POST(self):
        planned = self.path in {"/api/planned/select", "/api/planned/test"}
        guarded = planned or self.path in {"/api/controllers", "/api/evaluate-policy"}
        if not guarded and self.path not in {"/api/compare", "/api/study"}:
            return self.respond(404, b'{"error":"not found"}')
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") not in {host, f"localhost:{self.server.server_port}"}:
            return self.respond(403, b'{"error":"local host required"}')
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {"http://" + host, f"http://localhost:{self.server.server_port}"}:
            return self.respond(403, b'{"error":"same origin required"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
            maximum = (web_planned.MAX_REQUEST_BYTES if planned else
                       2 * 1024 * 1024 if self.path == "/api/evaluate-policy" else 65536)
            if length <= 0:
                raise ValueError(f"request must contain 1..{maximum} bytes")
            self.connection.settimeout(10)
            data = self.rfile.read(min(length, maximum + 1))
            if length > maximum:
                raise ValueError(f"request must contain 1..{maximum} bytes")
            value = json.loads(data)
            if guarded:
                if not RECIPE_SLOT.acquire(blocking=False):
                    return self.respond(429, json.dumps({"error": "另一个控制实验还在运行，请等它结束后再试。"}, ensure_ascii=False).encode())
                try:
                    routes = {"/api/controllers": run_recipes, "/api/evaluate-policy": test_saved_policy,
                              "/api/planned/select": web_planned.select_from_web,
                              "/api/planned/test": web_planned.test_from_web}
                    result = routes[self.path](value)
                finally:
                    RECIPE_SLOT.release()
            else:
                result = study(StudySpec.from_dict(value)) if self.path == "/api/study" else compare(Config.from_dict(value))
            payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            if guarded:
                message = web_planned.error_message(str(exc)) if planned else error_message(str(exc))
                return self.respond(400, json.dumps({"error": message, "detail": str(exc)}, ensure_ascii=False).encode())
            return self.respond(400, json.dumps({"error": str(exc)}, ensure_ascii=False).encode())
        except OSError:
            return self.respond(500, json.dumps({"error": "这次没能生成下载文件，请检查本机临时目录的可用空间和写入权限。"}, ensure_ascii=False).encode())
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
