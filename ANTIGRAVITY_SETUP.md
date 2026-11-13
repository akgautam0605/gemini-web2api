# Antigravity Gateway Setup (macOS)

This guide connects the Antigravity App to a local `gemini-web2api` server
through Antigravity's OpenAI-compatible enterprise gateway. It uses a separate
temporary app profile and environment variables; it does not edit the normal
app or IDE profile or global Antigravity settings. The standalone Antigravity
IDE does not support custom enterprise gateways; use the Antigravity App for
this integration.

For one-click switching, double-click
[`switch_antigravity_profile.command`](switch_antigravity_profile.command) in
Finder. Choose the gateway-enabled Antigravity App, the normal Antigravity App,
or the normal standalone IDE from its menu.
Gateway mode reads the first key from this project's `config.json` (or prompts
for it without echoing), starts `python gemini_web2api.py` in the background if
the local gateway is not already responding, fetches the current model list,
and launches the Antigravity App. Server output goes to
`~/Library/Logs/gemini-web2api-profile-switcher.log`. Normal mode opens the
regular app or IDE profile. Close an already open Antigravity App before
switching profiles to avoid reusing the wrong window.

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

## Antigravity IDE support

Google's current support matrix excludes the standalone Antigravity IDE from
custom enterprise gateway deployments. Passing `AGY_LLM_GATEWAY_*` variables
to its Electron process can open a separate window, but does not make the
standalone IDE route requests through this gateway. Use option 1 in the
switcher, which opens the supported Antigravity App with the isolated gateway
profile. The IDE remains available in its normal profile using option 3.

### Local profile and backup locations

- Gateway Antigravity App profile: `/private/tmp/antigravity-gateway-profile-all`
- Legacy IDE gateway test profile: `/private/tmp/antigravity-ide-gateway-profile` (retained; standalone IDE gateway is unsupported)
- Private local backup copy: `/Users/ashish/Documents/Codex/antigravity-profile-backups/gateway-ide-profile-2026-11-13/profile`

The backup is outside this repository, has owner-only directory permissions,
and is not tracked or pushed by Git. Antigravity profiles can contain cookies,
local storage, and other private session data; keep the backup private. The
original IDE profile remains at its existing path and was not deleted. The
switcher recreates the temporary App profile if macOS has cleaned it up; the
legacy IDE backup can be restored manually if needed.

## Switch Google accounts when Antigravity quota is exhausted

First identify the provider from the selected model ID:

- For `antigravity/...` models, the request uses the Google account signed in to
  the local Antigravity CLI. In an interactive `agy` session, enter `/logout`,
  then start `agy` again and sign in with the other Google account. Restart the
  IDE after signing in. Antigravity shares local sign-in credentials between
  its app, CLI, and IDE, so this signs out of the shared local Antigravity
  session.
- For Gemini Web IDs such as `gemini-3.1-pro`, the request uses the Gemini
  account represented by the cookie file configured on the local gateway.
  Antigravity sign-in does not switch that account. To use another account,
  configure a separate cookie file for that account in the gateway's existing
  `cookie_file` setting, then restart the gateway. Do not paste cookies or
  tokens into the IDE, this guide, or chat.
- The `sk-gemini` value is the local gateway API key; it is not the Google
  account credential and switching it does not change model quota.

If the Antigravity App is using an API-key or enterprise gateway authentication
mode instead of a personal Antigravity sign-in, `/logout` does not switch the
upstream account; switch the account or key at the gateway provider instead.

## Current limits and troubleshooting

- The `antigravity/` adapter supports text chat and OpenAI function tools.
  Tool schemas are supplied to `agy` as prompt instructions and parsed tool
  calls are returned to the client; the gateway does not execute those tools.
  Multimodal input is still unsupported.
- Google documents enterprise custom gateways for Antigravity App, CLI, and
  supported IDE extensions; the standalone Antigravity IDE is not a supported
  enterprise deployment surface. Use option 1 in the profile switcher for the
  local gateway. See [Google's supported products](https://antigravity.google/docs/enterprise).
- Only models returned by the local gateway are selectable. Antigravity model
  access depends on the signed-in CLI account and Google-side availability.
- Gemini 4 Argon and Hydrogen are not hard-coded into the Gemini Web provider.
  The Gemini Web implementation needs verified upstream model routing before
  those names can be advertised safely; adding names alone can silently route
  to another model. Check `/v1/models` before relying on either model.
- If the Antigravity App picker has no gateway models, confirm the gateway is
  running and relaunch option 1 in the switcher.
- If `/v1/models` returns `invalid api key`, use the exact key in the local
  `config.json` `api_keys` list.
- If `agy models` fails, sign in to the CLI and retry. The model list is
  discovered from that command; no Antigravity IDE configuration is changed.

## Return to normal profiles

Choose option 2 or 3 in the switcher to open the normal Antigravity App or
standalone IDE profile. Their settings were not edited by this
setup.
