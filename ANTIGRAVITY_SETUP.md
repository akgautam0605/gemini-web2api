# Antigravity Gateway Setup (macOS)

This guide connects Antigravity IDE to a local `gemini-web2api` server through
Antigravity's OpenAI-compatible enterprise gateway. It uses a separate temporary
Antigravity profile and environment variables; it does not edit the normal IDE
profile or global Antigravity settings.

## Prerequisites

1. Run `gemini-web2api` locally and confirm it listens on port `8081`.
2. Make sure the gateway's `config.json` has an API key in `api_keys`. Use the
   value already configured for your installation; do not copy it into this
   document or commit it.
3. Install and sign in to Antigravity CLI (`agy`) in your normal user account.
   Check that `agy models` completes and lists the models available to that
   account. The gateway discovers these models dynamically.
4. Install `jq` if it is not already available (`brew install jq`).

## Start the local gateway

From the project directory, use the same launch command you normally use. For
the standalone server, the project README uses:

```sh
cd ~/AI-Models/gemini-web2api
python gemini_web2api.py
```

Keep this terminal open. In another terminal, check that the gateway is
responding and that authentication works:

```sh
curl -fsS http://127.0.0.1:8081/v1/models \
  -H 'Authorization: Bearer YOUR_GATEWAY_API_KEY' | jq -r '.data[].id'
```

Replace `YOUR_GATEWAY_API_KEY` with the key already configured in `config.json`.
The output includes the Gemini Web IDs and, when `agy models` succeeds, IDs
prefixed with `antigravity/`.

## Launch an isolated Antigravity gateway session

In the second terminal, enter the gateway key without displaying it or saving it
in shell history:

```sh
read -s 'GATEWAY_API_KEY?Gateway API key: '
echo
export AGY_LLM_GATEWAY_URL='http://127.0.0.1:8081'
export AGY_LLM_GATEWAY_API_KEY="$GATEWAY_API_KEY"
export AGY_LLM_GATEWAY_WIRE_PROTOCOL='openai'
export AGY_LLM_GATEWAY_MODELS="$(curl -fsS "$AGY_LLM_GATEWAY_URL/v1/models" \
  -H "Authorization: Bearer $GATEWAY_API_KEY" | jq -r '.data | map(.id) | join(",")')"

PROFILE_DIR="$(mktemp -d /private/tmp/antigravity-gateway.XXXXXX)"
/Applications/Antigravity.app/Contents/MacOS/Antigravity \
  --user-data-dir="$PROFILE_DIR" --new-window
```

The model allowlist is built from the local `/v1/models` response each time you
launch. This makes the picker follow the models currently advertised by the
gateway. The separate profile is stored under `/private/tmp`; quit this
Antigravity window when finished. Its environment variables end when the
launching terminal session ends. Starting Antigravity from the Dock does not
inherit them.

## Verify a Gemini Web model

In the isolated Antigravity window, select a model such as `gemini-3.1-pro` and
send a short plain-text prompt. You can also test the same endpoint directly:

```sh
curl -fsS http://127.0.0.1:8081/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -d '{"model":"gemini-3.1-pro","messages":[{"role":"user","content":"Reply with exactly: Gateway works"}]}'
```

To check streaming, add `"stream":true` to the JSON body and `--no-buffer` to
the `curl` command. A successful stream returns `text/event-stream` chunks and
ends with `data: [DONE]`.

## Verify an Antigravity CLI model

Use an ID actually printed by `agy models` and shown in `/v1/models`, for
example `antigravity/gemini-3.8-flash-low`:

```sh
curl -N http://127.0.0.1:8081/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $GATEWAY_API_KEY" \
  -d '{"model":"antigravity/gemini-3.8-flash-low","stream":true,"messages":[{"role":"user","content":"Reply with exactly: Antigravity works"}]}'
```

## Current limits and troubleshooting

- The `antigravity/` adapter currently handles text chat only. It rejects
  OpenAI tools/function calling and multimodal input. Antigravity IDE's agent
  may attach tools to its requests; if so, the IDE request can fail with
  `Antigravity CLI provider does not support OpenAI tools`. A direct text-only
  `curl` request is the way to verify the CLI-backed provider today.
- Only models returned by the local gateway are selectable. Antigravity model
  access depends on the signed-in CLI account and Google-side availability.
- Gemini 4 Argon and Hydrogen are not hard-coded into the Gemini Web provider.
  The Gemini Web implementation needs verified upstream model routing before
  those names can be advertised safely; adding names alone can silently route
  to another model. Check `/v1/models` before relying on either model.
- If the IDE picker has no gateway models, confirm the gateway is running,
  re-run the launch commands in the same terminal (including the environment
  variables), and launch the isolated window again.
- If `/v1/models` returns `invalid api key`, use the exact key in the local
  `config.json` `api_keys` list.
- If `agy models` fails, sign in to the CLI and retry. The model list is
  discovered from that command; no Antigravity IDE configuration is changed.

## Return to the normal IDE profile

Quit the isolated Antigravity window. Open Antigravity normally from the Dock or
Applications. The normal profile and its settings were not edited by this
setup.
