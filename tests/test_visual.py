"""Photo search goes through the HTTP/session pipeline and only returns mock records."""

import base64
import http.cookiejar
import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from superchat.__main__ import make_handler
from superchat.repositories import load_repositories
from superchat.semantic_conversation import SemanticConversationEngine
from superchat.visual import VisualSearchService, decode_image


DATA = Path(__file__).resolve().parents[1] / "SuperChat_Mock_Data"
TEST_IMAGE = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\nfixture-bytes").decode("ascii")


class FakeAnalyzer:
    def __init__(self, answer):
        self.answer = answer

    def analyze(self, image, mime, catalogue):
        assert mime == "image/png"
        assert {row["id"] for row in catalogue} == {
            row["id"] for row in load_repositories(DATA).products.list_all()}
        return self.answer


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.engine = SemanticConversationEngine(load_repositories(DATA))
        self.session = self.engine.sessions.get_or_create(None)

    def test_catalogue_matches_and_confidence_update_shopping_state(self):
        self.engine.visual.analyzer = FakeAnalyzer({
            "confidence": 0.82, "category": "audio", "candidate_ids": ["P001", "P002"]})
        result = self.engine.respond_to_image(self.session, TEST_IMAGE)
        self.assertEqual(result["route"], "shopping")
        self.assertIn("82%", result["reply"])
        self.assertIn("P001", result["reply"])
        self.assertEqual(self.session.shopping.result_ids, ["P001", "P002"])
        self.assertEqual(self.session.active_domain, "shopping")
        self.assertNotIn("base64", str(result))

    def test_uncertain_or_invented_match_does_not_change_domain_state(self):
        self.engine.visual.analyzer = FakeAnalyzer({
            "confidence": 0.4, "category": "audio", "candidate_ids": ["P001"]})
        result = self.engine.respond_to_image(self.session, TEST_IMAGE)
        self.assertEqual(result["route"], "clarify")
        self.assertIsNone(self.session.active_domain)
        self.engine.visual.analyzer = FakeAnalyzer({
            "confidence": 0.99, "category": "audio", "candidate_ids": ["P999"]})
        result = self.engine.respond_to_image(self.session, TEST_IMAGE)
        self.assertEqual(result["route"], "clarify")
        self.assertNotIn("P999", result["reply"])
        self.assertEqual(self.session.shopping.result_ids, [])

    def test_http_photo_request_uses_same_history(self):
        self.engine.visual.analyzer = FakeAnalyzer({
            "confidence": 0.8, "category": "audio", "candidate_ids": ["P001"]})
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.engine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            request = urllib.request.Request(
                base + "/api/visual-search",
                data=json.dumps({"image": TEST_IMAGE}).encode(),
                headers={"Content-Type": "application/json"})
            result = json.load(client.open(request))
            self.assertEqual(result["route"], "shopping")
            self.assertEqual(len(json.load(client.open(base + "/api/session"))["history"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_invalid_image_is_rejected(self):
        with self.assertRaisesRegex(Exception, "valid JPEG"):
            decode_image("data:image/png;base64," + base64.b64encode(b"not a photo").decode())


if __name__ == "__main__":
    unittest.main()
