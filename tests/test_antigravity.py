import io
import json
import subprocess
import unittest
from unittest import mock

from gemini_web2api.antigravity import (
    _prompt_from_messages, discover_models, parse_tool_calls as parse_antigravity_tool_calls,
    stream_completion,
)
from gemini_web2api.server import GeminiHandler, ThreadedServer
import runpy
from pathlib import Path
monolithic_server = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "gemini_web2api.py"),
    run_name="gemini_web2api_monolithic_test",
)


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

    def test_tool_schemas_are_included_in_prompt(self):
        prompt = _prompt_from_messages(
            [{"role": "user", "content": "Add two numbers"}],
            [{"type": "function", "function": {
                "name": "add", "description": "Add two numbers",
                "parameters": {"type": "object", "properties": {"a": {"type": "number"}}},
            }}],
            "auto",
        )
        self.assertIn('"name": "add"', prompt)
        self.assertIn("```tool_call", prompt)

    def test_tool_response_is_limited_to_declared_tool_names(self):
        text, calls = parse_antigravity_tool_calls(
            '```tool_call\n{"name":"unsafe","arguments":{}}\n```',
            [{"type": "function", "function": {"name": "lookup"}}],
        )
        self.assertEqual(text, "")
        self.assertEqual(calls, [])

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


class MonolithicLauncherEndpointTests(unittest.TestCase):
    """The documented launcher runs gemini_web2api.py, so cover its handler too."""

    @classmethod
    def setUpClass(cls):
        from http.server import HTTPServer
        from socketserver import ThreadingMixIn

        class Server(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        cls.server = Server(("127.0.0.1", 0), monolithic_server["GeminiHandler"])
        cls.thread = __import__("threading").Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    @mock.patch("gemini_web2api.antigravity.stream_completion", return_value=iter([
        '```tool_call\n{"name":"lookup","arguments":{"query":"x"}}\n```'
    ]))
    def test_monolithic_chat_returns_openai_tool_call(self, completion):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps({
            "model": "antigravity/model-x",
            "messages": [{"role": "user", "content": "Look this up"}],
            "tools": [{"type": "function", "function": {
                "name": "lookup", "parameters": {"type": "object"},
            }}],
        })
        conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(data["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(completion.call_args.args[-2], json.loads(body)["tools"])

    @mock.patch("gemini_web2api.antigravity.stream_completion", return_value=iter([
        '```tool_call\n{"name":"lookup","arguments":{"query":"x"}}\n```'
    ]))
    def test_chat_completion_returns_openai_tool_call(self, completion):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps({
            "model": "antigravity/model-x",
            "messages": [{"role": "user", "content": "Look this up"}],
            "tools": [{"type": "function", "function": {
                "name": "lookup", "parameters": {"type": "object"},
            }}],
        })
        conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data["choices"][0]["finish_reason"], "tool_calls")
        self.assertEqual(data["choices"][0]["message"]["tool_calls"][0]["function"]["name"], "lookup")
        self.assertEqual(completion.call_args.args[-2], json.loads(body)["tools"])

    @mock.patch("gemini_web2api.antigravity.stream_completion", return_value=iter([
        '```tool_call\n{"name":"lookup","arguments":{"query":"x"}}\n```'
    ]))
    def test_chat_completion_streaming_returns_tool_call_chunk(self, _completion):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps({
            "model": "antigravity/model-x", "stream": True,
            "messages": [{"role": "user", "content": "Look this up"}],
            "tools": [{"type": "function", "function": {
                "name": "lookup", "parameters": {"type": "object"},
            }}],
        })
        conn.request("POST", "/v1/chat/completions", body, {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = response.read().decode()
        conn.close()
        self.assertEqual(response.status, 200)
        self.assertIn('"tool_calls"', data)
        self.assertIn('"finish_reason": "tool_calls"', data)
        self.assertIn("data: [DONE]", data)


if __name__ == "__main__":
    unittest.main()
