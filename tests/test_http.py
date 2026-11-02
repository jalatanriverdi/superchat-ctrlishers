import http.cookiejar
import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from superchat.__main__ import SingleInstanceHTTPServer, make_handler
from superchat.conversation import ConversationEngine
from superchat.repositories import load_repositories


DATA_DIR = Path(__file__).resolve().parent.parent / "SuperChat_Mock_Data"


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = ConversationEngine(load_repositories(DATA_DIR))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine))
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        self.client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def post(self, path, payload):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        return self.client.open(request)

    def test_chat_page_and_cookie_session(self):
        page = self.client.open(self.base + "/").read().decode("utf-8")
        self.assertIn("SuperChat", page)
        self.assertIn('id="chat-form"', page)
        result = json.load(self.post("/api/chat", {
            "message": "Find me a flight from Baku to Istanbul on Friday."
        }))
        self.assertEqual(result["route"], "flights")
        self.assertIn("F013", result["reply"])
        history = json.load(self.client.open(self.base + "/api/session"))["history"]
        self.assertEqual(len(history), 2)
        self.assertIn("Orbit Zero", json.load(self.post("/api/chat", {
            "message": "What is playing tonight?"
        }))["reply"])
        self.assertEqual(len(json.load(self.client.open(self.base + "/api/session"))["history"]), 4)
        self.assertEqual(json.load(self.post("/api/reset", {}))["history"], [])
        self.assertEqual(json.load(self.client.open(self.base + "/api/session"))["history"], [])

    def test_invalid_chat_request_is_controlled(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/chat", {"message": ""})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("Enter a message", json.load(caught.exception)["error"])
        caught.exception.close()

    def test_deployment_readiness_requires_interpreter_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.client.open(self.base + "/ready")
            self.assertEqual(caught.exception.code, 503)
            caught.exception.close()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}):
            self.assertEqual(json.load(self.client.open(self.base + "/ready"))["status"], "ready")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-placeholder"}, clear=True):
            self.assertEqual(json.load(self.client.open(self.base + "/ready"))["status"], "ready")

    def test_env_file_is_not_served_over_http(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.client.open(self.base + "/.env")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_second_demo_server_cannot_claim_same_port(self):
        first = SingleInstanceHTTPServer(("127.0.0.1", 0),
                                         make_handler(ConversationEngine(load_repositories(DATA_DIR))))
        try:
            with self.assertRaises(OSError):
                SingleInstanceHTTPServer(("127.0.0.1", first.server_port),
                                         make_handler(ConversationEngine(load_repositories(DATA_DIR))))
        finally:
            first.server_close()

    def test_unrelated_message_after_search_does_not_repeat_results(self):
        first = json.load(self.post("/api/chat", {"message": "Show me running shoes"}))
        self.assertIn("P009", first["reply"])
        answer = json.load(self.post("/api/chat", {"message": "who is donalt trump"}))
        self.assertEqual(answer["route"], "out_of_scope")
        self.assertNotIn("P009", answer["reply"])
        self.assertEqual(len(answer["history"]), 4)
        self.assertIn("P009", json.load(self.post("/api/chat", {
            "message": "Back to running shoes"
        }))["reply"])


if __name__ == "__main__":
    unittest.main()
