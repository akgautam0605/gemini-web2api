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


def _prompt_from_messages(messages):
    """Flatten OpenAI text messages while keeping role boundaries explicit."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty array")
    parts = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("each message must be an object")
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            text = []
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    raise ValueError("Antigravity CLI supports text message content only")
                text.append(str(item.get("text", "")))
            content = "\n".join(text)
        if not isinstance(content, str):
            raise ValueError("Antigravity CLI supports text message content only")
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def stream_completion(model_id, messages, config):
    """Yield text deltas from a one-shot, isolated headless CLI session."""
    cli = find_cli(config)
    if not cli:
        raise RuntimeError("Antigravity CLI (agy) was not found; set antigravity_cli or add it to PATH")
    prompt = _prompt_from_messages(messages)
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
