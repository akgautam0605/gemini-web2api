import http.client
import importlib.util
import json
from pathlib import Path
import threading
from http.server import HTTPServer
from socketserver import ThreadingMixIn
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gemini_web2api_standalone", PROJECT / "gemini_web2api.py")
standalone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(standalone)


class TestServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class StandaloneAntigravityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = TestServer(("127.0.0.1", 0), standalone.GeminiHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    @mock.patch("gemini_web2api.antigravity.discover_models", return_value=[("model-x", "Model X")])
    def test_single_file_model_list_preserves_gemini_and_adds_antigravity(self, _discover):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", "/v1/models")
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        ids = {item["id"] for item in data["data"]}
        self.assertIn("gemini-3.6-flash", ids)
        self.assertIn("antigravity/model-x", ids)

    @mock.patch("gemini_web2api.antigravity.stream_completion", return_value=iter(["Antigravity works"]))
    def test_single_file_chat_routes_antigravity_model(self, completion):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        payload = json.dumps({"model": "antigravity/model-x", "messages": [{"role": "user", "content": "Hi"}]})
        conn.request("POST", "/v1/chat/completions", payload, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["model"], "antigravity/model-x")
        self.assertEqual(data["choices"][0]["message"]["content"], "Antigravity works")
        completion.assert_called_once()


if __name__ == "__main__":
    unittest.main()
