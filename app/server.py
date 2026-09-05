import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest

from app.config import AppError, ROOT, Settings
from app.database import fetch_rows
from app.model import plan_question
from app.plans import example_plan
from app.tables import make_table


def create_server(settings, port):
    lane = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Questions and table rows are not logged.

        def reply(self, status, body, mime="application/json"):
            data = json.dumps(body, ensure_ascii=False).encode() if mime == "application/json" else body
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            active_port = self.server.server_address[1]
            return self.headers.get("Host") in (f"localhost:{active_port}", f"127.0.0.1:{active_port}")

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {"error": "Use the local app address."})
            if self.path == "/api/status":
                return self.reply(200, {"version": (ROOT / "VERSION").read_text().strip(), "database": settings.get("DB_KIND"), "model": settings.get("AI_MODEL") or "Not configured"})
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if self.path not in assets:
                return self.reply(404, {"error": "Not found."})
            filename, mime = assets[self.path]
            self.reply(200, (ROOT / "web" / filename).read_bytes(), mime)

        def do_POST(self):
            active_port = self.server.server_address[1]
            allowed_origins = (None, f"http://localhost:{active_port}", f"http://127.0.0.1:{active_port}")
            if not self.valid_host() or self.headers.get("Origin") not in allowed_origins or self.headers.get_content_type() != "application/json":
                return self.reply(403, {"error": "Requests must come from the local app."})
            if self.path not in ("/api/ask", "/api/sample"):
                return self.reply(404, {"error": "Not found."})
            if not lane.acquire(blocking=False):
                return self.reply(429, {"error": "A question is already running. Try again when it finishes."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32000:
                    raise AppError("Request is empty or too large. Start a new question.")
                self.connection.settimeout(10)
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise AppError("Invalid request.")
                view = payload.get("view", "auto")
                if view not in ("auto", "summary", "detail"):
                    raise AppError("Unknown table layout.")
                if self.path == "/api/sample":
                    if settings.get("DB_KIND") != "demo":
                        raise AppError("Sample buttons are only available with fictional demo data.")
                    plan = example_plan("summary" if view == "auto" else view)
                else:
                    question, history = payload.get("question"), payload.get("history", [])
                    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
                        raise AppError("Enter a question of up to 4,000 characters.")
                    if not isinstance(history, list) or len(history) > 16:
                        raise AppError("Start a new question to clear the long conversation.")
                    for message in history:
                        if not isinstance(message, dict) or set(message) != {"role", "content"} or message["role"] not in ("user", "assistant") or not isinstance(message["content"], str) or len(message["content"]) > 4000:
                            raise AppError("Invalid conversation context.")
                    plan = plan_question(settings, question.strip(), history, view)
                if plan["kind"] == "clarify":
                    return self.reply(200, {"kind": "clarify", "question": plan["question"]})
                table = make_table(fetch_rows(settings, plan), settings.schema, plan)
                self.reply(200, {"kind": "table", "table": table, "plan": plan})
            except (AppError, ValueError) as error:
                self.reply(400, {"error": str(error) if isinstance(error, AppError) else "Invalid request JSON or length."})
            except Exception:
                self.reply(500, {"error": "The request could not be completed. Check the local configuration and source schema."})
            finally:
                lane.release()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="B2B Local Data")
    parser.add_argument("--home", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    try:
        settings = Settings.load(args.home)
        if args.check:
            print("Configuration is valid. Live SQL and Qwen connections have not been tested.")
            return
        server = create_server(settings, settings.number("APP_PORT", 8765, high=65535))
        print(f"B2B Local Data: http://127.0.0.1:{server.server_address[1]}  (database: {settings.get('DB_KIND')})", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    except AppError as error:
        parser.exit(1, str(error) + "\n")
