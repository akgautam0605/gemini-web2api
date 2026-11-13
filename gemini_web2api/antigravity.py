"""Secure adapter for the installed Antigravity CLI (agy)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def find_cli(config):
    """Resolve an explicit CLI path, PATH entry, or standard per-user install."""
    configured = config.get("antigravity_cli")
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which("agy")
    if found:
        return found
    fallback = Path.home() / ".gemini" / "bin" / "agy"
    return str(fallback) if fallback.is_file() and os.access(fallback, os.X_OK) else None


def discover_models(config, timeout=20):
    """Return model ids and labels from `agy models`, or an empty list."""
    cli = find_cli(config)
    if not cli:
        return []
    try:
        result = subprocess.run([cli, "models"], capture_output=True, text=True,
                                timeout=timeout, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    models = []
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._/-]*)(?:\t+|\s{2,})(.+?)\s*$", line)
        if match:
            models.append((match.group(1), match.group(2)))
    return models


def _prompt_from_messages(messages, tools=None, tool_choice=None):
    """Convert OpenAI text messages and optional tool schemas to a CLI prompt."""
    from .tools import messages_to_prompt

    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    if any(not isinstance(message, dict) for message in messages):
        raise ValueError("each message must be an object")
    if tools is not None:
        if not isinstance(tools, list):
            raise ValueError("tools must be an array")
        for tool in tools:
            function = tool.get("function", tool) if isinstance(tool, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"]:
                raise ValueError("each tool must define a function name")
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, list) and any(
            not isinstance(item, dict) or item.get("type") not in ("text", "input_text")
            for item in content
        ):
            raise ValueError("Antigravity CLI supports text message content only")
        if not isinstance(content, (str, list)) and content is not None:
            raise ValueError("Antigravity CLI supports text message content only")
    prompt, images = messages_to_prompt(messages, tools, tool_choice)
    if images:
        raise ValueError("Antigravity CLI supports text message content only")
    return prompt


def parse_tool_calls(text, tools, tool_choice=None):
    """Parse only calls whose function names were declared by the client."""
    from .tools import parse_tool_calls as parse_openai_tool_calls

    clean, calls = parse_openai_tool_calls(text)
    allowed = set()
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function", tool)
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            allowed.add(function["name"])
    if isinstance(tool_choice, dict):
        selected = tool_choice.get("function", {}).get("name")
        if selected:
            allowed.intersection_update({selected})
    return clean, [call for call in calls if call["function"]["name"] in allowed]


def stream_completion(model_id, messages, config, tools=None, tool_choice=None):
    """Yield text deltas from a one-shot, isolated headless CLI session."""
    cli = find_cli(config)
    if not cli:
        raise RuntimeError("Antigravity CLI (agy) was not found; set antigravity_cli or add it to PATH")
    prompt = _prompt_from_messages(messages, tools, tool_choice)
    # Empty cwd and sandboxed plan mode keep API prompts away from the project tree
    # and avoid granting the agent permission to execute workspace changes.
    with tempfile.TemporaryDirectory(prefix="gemini-web2api-agy-") as workdir:
        args = [cli, "--input-format", "stream-json", "--output-format", "stream-json",
                "--sandbox", "--mode", "plan", "--model", model_id]
        try:
            proc = subprocess.Popen(args, cwd=workdir, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", bufsize=1, shell=False)
        except OSError as exc:
            raise RuntimeError(f"could not start Antigravity CLI: {exc}") from exc
        assert proc.stdin and proc.stdout
        timeout = max(1, int(config.get("antigravity_timeout_sec", 180)))
        timer = threading.Timer(timeout, proc.kill)
        timer.daemon = True
        timer.start()
        try:
            proc.stdin.write(json.dumps({"event": "user", "message": {"content": prompt}}) + "\n")
            proc.stdin.close()
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "step_update":
                    update = event.get("step_update", {})
                    delta = update.get("text_delta") if update.get("step_type") == "agent_response" else None
                    if delta:
                        yield delta
                elif event.get("event") == "result":
                    result = event.get("result", {})
                    if result.get("status") != "SUCCESS":
                        raise RuntimeError(result.get("error") or "Antigravity CLI request failed")
            code = proc.wait(timeout=1)
            if code:
                if timer.finished.is_set():
                    raise RuntimeError("Antigravity CLI request timed out")
                stderr = proc.stderr.read() if proc.stderr else ""
                raise RuntimeError(stderr.strip() or f"Antigravity CLI exited with status {code}")
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stderr:
                proc.stderr.close()
