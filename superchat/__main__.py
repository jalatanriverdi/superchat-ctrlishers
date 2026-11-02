"""Run the local SuperChat web application with one command."""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .semantic_conversation import SemanticConversationEngine
from .data_validation import DataSourceError
from .repositories import load_repositories
from .settings import load_local_env


STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


class SingleInstanceHTTPServer(ThreadingHTTPServer):
    """Do not let an older Windows server silently share the demo port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_handler(engine: SemanticConversationEngine):
    class Handler(BaseHTTPRequestHandler):
        def _session(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                session_id = cookie["superchat_session"].value if "superchat_session" in cookie else None
            except Exception:
                session_id = None
            return engine.sessions.get_or_create(session_id)

        def _send(self, status: HTTPStatus, body: bytes, content_type: str,
                  session_id: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if session_id:
                self.send_header(
                    "Set-Cookie",
                    f"superchat_session={session_id}; Path=/; HttpOnly; SameSite=Lax",
                )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, payload: dict,
                  session_id: str | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", session_id)

        def do_GET(self) -> None:
            if self.path == "/ready":
                ready = bool(os.environ.get("OPENROUTER_API_KEY") or
                             os.environ.get("OPENAI_API_KEY"))
                self._json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                           {"status": "ready" if ready else "missing_api_key"})
                return
            if self.path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok", "data_counts": {
                    name: len(getattr(engine.repositories, name).list_all())
                    for name in ("flights", "products", "movies", "cinemas", "showtimes")
                }})
                return
            if self.path == "/api/session":
                session = self._session()
                self._json(HTTPStatus.OK, {"history": list(session.history)}, session.id)
                return
            static = STATIC_FILES.get(self.path)
            if static:
                filename, content_type = static
                try:
                    body = (STATIC_DIR / filename).read_bytes()
                except OSError:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Page unavailable."})
                    return
                self._send(HTTPStatus.OK, body, content_type)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

        def do_POST(self) -> None:
            if self.path not in {"/api/chat", "/api/reset", "/api/visual-search",
                                 "/api/card-action"}:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            max_length = 6_000_000 if self.path == "/api/visual-search" else 16_384
            if length < 0 or length > max_length:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size."})
                return
            try:
                payload = json.loads(self.rfile.read(length)) if length else {}
            except (UnicodeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON request."})
                return
            if not isinstance(payload, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Expected a JSON object."})
                return
            session = self._session()
            if self.path == "/api/reset":
                session = engine.sessions.reset(session.id)
                self._json(HTTPStatus.OK, {"history": []}, session.id)
                return
            if self.path == "/api/visual-search":
                image = payload.get("image")
                if not isinstance(image, str):
                    self._json(HTTPStatus.BAD_REQUEST,
                               {"error": "Choose a photo to search."}, session.id)
                    return
                try:
                    result = engine.respond_to_image(session, image)
                except Exception:
                    logging.exception("Unexpected photo search error")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                               {"error": "Photo search is temporarily unavailable."}, session.id)
                    return
                self._json(HTTPStatus.OK, result, session.id)
                return
            if self.path == "/api/card-action":
                domain, item_id, intent = (payload.get(key) for key in
                                           ("domain", "id", "action"))
                if not all(isinstance(value, str) for value in
                           (domain, item_id, intent)):
                    self._json(HTTPStatus.BAD_REQUEST,
                               {"error": "Invalid card action."}, session.id)
                    return
                try:
                    result = engine.respond_to_card_action(session, domain, item_id, intent)
                except ValueError as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, session.id)
                    return
                except Exception:
                    logging.exception("Unexpected card action error")
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                               {"error": "Card action is temporarily unavailable."}, session.id)
                    return
                self._json(HTTPStatus.OK, result, session.id)
                return
            message = payload.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 2000:
                self._json(HTTPStatus.BAD_REQUEST,
                           {"error": "Enter a message of 1 to 2000 characters."}, session.id)
                return
            try:
                result = engine.respond(session, message)
            except Exception:
                logging.exception("Unexpected chat error")
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR,
                           {"error": "Something went wrong. Please try again."}, session.id)
                return
            self._json(HTTPStatus.OK, result, session.id)

    return Handler


def main() -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description="Start SuperChat")
    parser.add_argument("--data-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "SuperChat_Mock_Data")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    try:
        engine = SemanticConversationEngine(load_repositories(args.data_dir))
    except DataSourceError as exc:
        print(f"SuperChat data error: {exc}", file=sys.stderr)
        return 1
    try:
        server = SingleInstanceHTTPServer((args.host, args.port), make_handler(engine))
    except OSError as exc:
        print(f"Cannot start SuperChat on port {args.port}: {exc}. "
              "Stop the earlier server or choose another port with --port.",
              file=sys.stderr)
        return 1
    print(f"SuperChat is running at http://{args.host}:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
