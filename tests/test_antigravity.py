import io
import json
import subprocess
import unittest
from unittest import mock

from gemini_web2api.antigravity import _prompt_from_messages, discover_models, stream_completion
from gemini_web2api.server import GeminiHandler, ThreadedServer


class AntigravityAdapterTests(unittest.TestCase):
    @mock.patch("gemini_web2api.antigravity.find_cli", return_value="/fake/agy")
    @mock.patch("gemini_web2api.antigravity.subprocess.run")
    def test_discovers_cli_models(self, run, _find):
        run.return_value = subprocess.CompletedProcess([], 0,
            "gemini-3.7-flash-medium  Gemini 3.7 Flash (Medium)\n", "")
        self.assertEqual(discover_models({}), [("gemini-3.7-flash-medium", "Gemini 3.7 Flash (Medium)")])
        self.assertEqual(run.call_args.args[0], ["/fake/agy", "models"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_text_message_conversion_rejects_images(self):
        with self.assertRaisesRegex(ValueError, "text message content only"):
            _prompt_from_messages([{"role": "user", "content": [{"type": "image_url"}]}])

    @mock.patch("gemini_web2api.antigravity.tempfile.TemporaryDirectory")
    @mock.patch("gemini_web2api.antigravity.subprocess.Popen")
    @mock.patch("gemini_web2api.antigravity.find_cli", return_value="/fake/agy")
    def test_stream_uses_sandbox_plan_and_parses_deltas(self, _find, popen, tempdir):
        tempdir.return_value.__enter__.return_value = "/tmp/isolated"
        proc = mock.Mock()
        proc.stdin = io.StringIO()
        proc.stdout = io.StringIO(
            json.dumps({"event": "step_update", "step_update": {"step_type": "agent_response", "text_delta": "Hi"}}) + "\n" +
            json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "Hi"}}) + "\n")
        proc.stderr = io.StringIO()
        proc.wait.return_value = 0
        proc.poll.return_value = 0
        popen.return_value = proc
        self.assertEqual(list(stream_completion("model-x", [{"role": "user", "content": "hello"}], {})), ["Hi"])
        args = popen.call_args.args[0]
        self.assertIn("--sandbox", args)
        self.assertIn("plan", args)
        self.assertEqual(popen.call_args.kwargs["cwd"], "/tmp/isolated")
        self.assertFalse(popen.call_args.kwargs.get("shell", True))


class AntigravityEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadedServer(("127.0.0.1", 0), GeminiHandler)
        cls.thread = __import__("threading").Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    @mock.patch("gemini_web2api.server.discover_models", return_value=[("model-x", "Model X")])
    def test_model_list_preserves_gemini_and_adds_antigravity(self, _discover):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request("GET", "/v1/models")
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        ids = {item["id"] for item in data["data"]}
        self.assertIn("gemini-3.6-flash", ids)
        self.assertIn("antigravity/model-x", ids)

    @mock.patch("gemini_web2api.server.antigravity_stream_completion", return_value=iter(["Hello", " world"]))
    def test_chat_completion_non_streaming(self, _completion):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps({"model": "antigravity/model-x", "messages": [{"role": "user", "content": "Hi"}]})
        conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["choices"][0]["message"]["content"], "Hello world")

    @mock.patch("gemini_web2api.server.antigravity_stream_completion", return_value=iter(["Hello"]))
    def test_chat_completion_streaming(self, _completion):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps({"model": "antigravity/model-x", "stream": True, "messages": [{"role": "user", "content": "Hi"}]})
        conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = response.read().decode()
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn('"content": "Hello"', data)
        self.assertIn("data: [DONE]", data)


if __name__ == "__main__":
    unittest.main()
