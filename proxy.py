#!/usr/bin/env python3
"""
Reverse proxy sidecar for LiteLLM.

Two modes (PROXY_MODE env var):

  local  (default) — Translates standard Anthropic / OpenAI API requests into
                      OpenCode's session-based REST API and forwards them to a
                      local `opencode serve` instance.
  tunnel           — Passthrough proxy that injects a Cloudflare Access JWT and
                      forwards raw requests to a remote server.
"""

import glob
import json
import os
import sys
import asyncio
import time
import uuid
from urllib.parse import urlparse

import aiohttp
from aiohttp import web

# ── Configuration ────────────────────────────────────────────────────────────

PROXY_MODE = os.environ.get("PROXY_MODE", "local").lower()

_DEFAULT_URL = "http://host.docker.internal:4096" if PROXY_MODE == "local" else ""
API_BASE_URL = os.environ.get("API_BASE_URL", _DEFAULT_URL).rstrip("/")

_remote_host = urlparse(API_BASE_URL).hostname or ""
_TOKEN_PATTERN = (
    os.path.expanduser(f"~/.cloudflared/{_remote_host}-*-token") if _remote_host else ""
)
_TOKEN_ENV = os.environ.get("CF_ACCESS_TOKEN", "")

HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    ]
)

STRIP_HEADERS = frozenset(
    [
        "host",
        "x-api-key",
        "authorization",
        "content-length",
        "cf-access-token",
    ]
)

session: aiohttp.ClientSession | None = None

# ── Local-mode state ─────────────────────────────────────────────────────────
# Reuse a single OpenCode session per provider/model pair to avoid creating
# thousands of sessions.  Maps "providerID/modelID" → session_id.
_oc_sessions: dict[str, str] = {}


# ── CF token helpers (tunnel mode) ───────────────────────────────────────────


def get_cf_token() -> str:
    if _TOKEN_PATTERN:
        files = glob.glob(_TOKEN_PATTERN)
        if files:
            try:
                token = open(files[0]).read().strip()
                if token:
                    return token
            except OSError:
                pass
    if _TOKEN_ENV:
        return _TOKEN_ENV
    return ""


# ── OpenCode session helpers (local mode) ────────────────────────────────────


async def oc_get_or_create_session(provider_id: str, model_id: str) -> str:
    """Return an OpenCode session ID, creating one if necessary."""
    key = f"{provider_id}/{model_id}"
    if key in _oc_sessions:
        return _oc_sessions[key]

    url = f"{API_BASE_URL}/session"
    payload = {"title": f"litellm-proxy {key}"}
    async with session.post(url, json=payload) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(
                f"Failed to create OpenCode session: {resp.status} {body}"
            )
        data = await resp.json()
        sid = data["id"]
        _oc_sessions[key] = sid
        print(f"[local] Created OpenCode session {sid} for {key}", file=sys.stderr)
        return sid


async def oc_send_message(
    session_id: str, provider_id: str, model_id: str, text: str
) -> dict:
    """Send a message to OpenCode and return the raw response dict."""
    url = f"{API_BASE_URL}/session/{session_id}/message"
    payload = {
        "parts": [{"type": "text", "text": text}],
        "model": {"providerID": provider_id, "modelID": model_id},
    }
    async with session.post(
        url,
        json=payload,
        timeout=aiohttp.ClientTimeout(total=600, sock_read=300),
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"OpenCode error: {resp.status} {body}")
        return await resp.json()


def messages_to_text(messages: list[dict]) -> str:
    """Flatten a chat-completion messages array into a single text prompt."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # content can be a string or a list of content blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)
        if content:
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


def extract_oc_text(oc_resp: dict) -> tuple[str, dict]:
    """Extract assistant text and token info from an OpenCode response."""
    text_parts: list[str] = []
    for part in oc_resp.get("parts", []):
        if part.get("type") == "text":
            text_parts.append(part.get("text", ""))
    text = "\n".join(text_parts)
    info = oc_resp.get("info", {})
    return text, info


# ── Local-mode API handlers ─────────────────────────────────────────────────


async def handle_anthropic_messages(request: web.Request) -> web.StreamResponse:
    """Translate POST /v1/messages (Anthropic) → OpenCode session API."""
    body = await request.json()
    model_id = body.get("model", "")
    messages = body.get("messages", [])
    system_text = body.get("system", "")
    stream = body.get("stream", False)

    prompt_parts = []
    if system_text:
        prompt_parts.append(f"[system]: {system_text}")
    prompt_parts.append(messages_to_text(messages))
    prompt = "\n\n".join(prompt_parts)

    provider_id = "anthropic"
    print(
        f"[local] Anthropic → {provider_id}/{model_id} stream={stream}", file=sys.stderr
    )

    try:
        sid = await oc_get_or_create_session(provider_id, model_id)
        oc_resp = await oc_send_message(sid, provider_id, model_id, prompt)
        text, info = extract_oc_text(oc_resp)
        tokens = info.get("tokens", {})
        msg_id = info.get("id", f"msg_{uuid.uuid4().hex[:24]}")
        stop_reason = info.get("finish", "end_turn")

        if stream:
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
            await resp.prepare(request)

            # Anthropic SSE requires "event: <type>\ndata: <json>\n\n" per the spec.
            def sse(event_type: str, payload: dict) -> bytes:
                return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n".encode()

            await resp.write(
                sse(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": msg_id,
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": model_id,
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {
                                "input_tokens": tokens.get("input", 0),
                                "output_tokens": 0,
                            },
                        },
                    },
                )
            )
            await resp.write(
                sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            )
            await resp.write(sse("ping", {"type": "ping"}))
            await resp.write(
                sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
            )
            await resp.write(
                sse(
                    "content_block_stop",
                    {
                        "type": "content_block_stop",
                        "index": 0,
                    },
                )
            )
            await resp.write(
                sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                        "usage": {"output_tokens": tokens.get("output", 0)},
                    },
                )
            )
            await resp.write(sse("message_stop", {"type": "message_stop"}))
            await resp.write_eof()
            return resp

        return web.json_response(
            {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
                "model": model_id,
                "stop_reason": stop_reason,
                "usage": {
                    "input_tokens": tokens.get("input", 0),
                    "output_tokens": tokens.get("output", 0),
                },
            }
        )
    except Exception as e:
        print(f"[local] error: {e}", file=sys.stderr)
        return web.json_response(
            {"type": "error", "error": {"type": "api_error", "message": str(e)}},
            status=500,
        )


def resolve_provider(model_id: str, default: str = "openai") -> tuple[str, str]:
    """Map a model name to (providerID, modelID) for OpenCode.

    LiteLLM strips the provider prefix before sending, so we infer it from
    the model name pattern.  Gemini models are routed as openai/ in the
    LiteLLM config but need google/ for OpenCode.  Workers AI models use
    @cf/ prefix and need workers-ai/ provider with the full @cf path.
    """
    if model_id.startswith("gemini"):
        return "google", model_id
    if model_id.startswith("@cf/"):
        return "workers-ai", f"workers-ai/{model_id}"
    return default, model_id


async def handle_openai_chat(request: web.Request) -> web.StreamResponse:
    """Translate POST /v1/chat/completions (OpenAI) → OpenCode session API."""
    body = await request.json()
    raw_model = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    prompt = messages_to_text(messages)

    provider_id, model_id = resolve_provider(raw_model)
    print(
        f"[local] chat/completions → {provider_id}/{model_id} stream={stream}",
        file=sys.stderr,
    )

    try:
        sid = await oc_get_or_create_session(provider_id, model_id)
        oc_resp = await oc_send_message(sid, provider_id, model_id, prompt)
        text, info = extract_oc_text(oc_resp)
        tokens = info.get("tokens", {})
        input_t = tokens.get("input", 0)
        output_t = tokens.get("output", 0)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())

        if stream:
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
            await resp.prepare(request)
            chunk_data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": text},
                        "finish_reason": None,
                    }
                ],
            }
            await resp.write(f"data: {json.dumps(chunk_data)}\n\n".encode())
            done_data = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_id,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            await resp.write(f"data: {json.dumps(done_data)}\n\n".encode())
            await resp.write(b"data: [DONE]\n\n")
            await resp.write_eof()
            return resp

        return web.json_response(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": input_t,
                    "completion_tokens": output_t,
                    "total_tokens": input_t + output_t,
                },
            }
        )
    except Exception as e:
        print(f"[local] error: {e}", file=sys.stderr)
        return web.json_response(
            {"error": {"message": str(e), "type": "server_error", "code": 500}},
            status=500,
        )


# ── Tunnel-mode passthrough ─────────────────────────────────────────────────


async def tunnel_proxy(request: web.Request) -> web.StreamResponse:
    """Forward the request as-is, injecting the CF Access token."""
    target_url = f"{API_BASE_URL}{request.path_qs}"
    print(f"[tunnel] {request.method} {request.path}", file=sys.stderr)

    headers: dict[str, str] = {}
    token = get_cf_token()
    if token:
        headers["cf-access-token"] = token
    else:
        print(
            "WARNING: No CF Access token — request will likely be rejected.",
            file=sys.stderr,
        )

    for k, v in request.headers.items():
        if k.lower() not in STRIP_HEADERS and k.lower() not in HOP_BY_HOP:
            headers[k] = v

    body = await request.read() if request.can_read_body else None

    try:
        async with session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=600, sock_read=300),
        ) as resp:
            content_type = resp.headers.get("Content-Type", "")
            is_sse = "text/event-stream" in content_type

            resp_headers = {}
            for k, v in resp.headers.items():
                if k.lower() not in HOP_BY_HOP | {"content-length", "content-encoding"}:
                    resp_headers[k] = v

            if is_sse:
                response = web.StreamResponse(status=resp.status, headers=resp_headers)
                response.content_type = content_type
                await response.prepare(request)
                async for chunk in resp.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
            else:
                return web.Response(
                    status=resp.status,
                    headers=resp_headers,
                    body=await resp.read(),
                )
    except Exception as e:
        print(f"[tunnel] error: {e}", file=sys.stderr)
        return web.Response(status=502, text=f"Proxy error: {e}")


# ── Common handlers ──────────────────────────────────────────────────────────


async def health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def models_handler(request: web.Request) -> web.Response:
    """Return a minimal /v1/models response so LiteLLM health checks pass."""
    return web.json_response({"object": "list", "data": []})


# ── App lifecycle ────────────────────────────────────────────────────────────


async def on_startup(app):
    global session
    ssl_ctx = True if PROXY_MODE == "tunnel" else False
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    session = aiohttp.ClientSession(connector=connector)


async def on_cleanup(app):
    if session:
        await session.close()


async def main():
    if not API_BASE_URL:
        print("ERROR: API_BASE_URL is not set", file=sys.stderr)
        sys.exit(1)

    print(f"Mode:     {PROXY_MODE}", file=sys.stderr)
    print(f"Upstream: {API_BASE_URL}", file=sys.stderr)

    if PROXY_MODE == "tunnel":
        token = get_cf_token()
        src = (
            f"~/.cloudflared/{_remote_host}-*-token"
            if glob.glob(_TOKEN_PATTERN)
            else "CF_ACCESS_TOKEN env"
        )
        if token:
            print(f"CF token: loaded from {src}", file=sys.stderr)
        else:
            print("WARNING: Starting without CF Access token", file=sys.stderr)
    else:
        print("CF token: not required (local mode)", file=sys.stderr)

    app = web.Application()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_get("/health", health)
    app.router.add_get("/v1/models", models_handler)

    if PROXY_MODE == "local":
        # Intercept standard API paths and translate to OpenCode session API.
        # LiteLLM sends with or without /v1 prefix depending on provider SDK.
        app.router.add_post("/v1/messages", handle_anthropic_messages)
        app.router.add_post("/messages", handle_anthropic_messages)
        app.router.add_post("/v1/chat/completions", handle_openai_chat)
        app.router.add_post("/chat/completions", handle_openai_chat)
        # Fall through: forward anything else to OpenCode as-is.
        app.router.add_route("*", "/{path:.*}", tunnel_proxy)
    else:
        # Tunnel mode: forward everything with CF token injection.
        app.router.add_route("*", "/{path:.*}", tunnel_proxy)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print(f"Proxy listening on http://0.0.0.0:8080 -> {API_BASE_URL}", file=sys.stderr)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
