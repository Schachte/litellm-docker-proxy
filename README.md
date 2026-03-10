# LiteLLM Proxy for OpenCode

LiteLLM gateway that proxies LLM requests through a local OpenCode server, optionally exposed publicly via Cloudflare Tunnel at `litellm.ryan-schachte.com`.

## Architecture

```
                  ┌─── docker compose ──────────────────────────────────┐
                  │                                                      │
  Claude Code     │  ┌──────────┐   ┌───────────┐                      │
  OpenAI clients  │  │          │   │   proxy    │   host.docker.internal:4096
  ───────────────▶│  │ LiteLLM  │──▶│  :8080     │──▶ opencode serve
       :4000      │  │  :4000   │   │            │                      │
                  │  └────┬─────┘   └────────────┘                      │
                  │       │                                              │
                  │  ┌────▼─────┐                                       │
                  │  │ Postgres │                                        │
                  │  └──────────┘                                        │
                  │                                                      │
                  │  ┌─────────────┐  (make up only)                    │
                  │  │ cloudflared │──▶ litellm.ryan-schachte.com       │
                  │  └─────────────┘                                    │
                  └──────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. First-time setup
make init

# 2. Authenticate with OpenCode (opens browser, one-time)
make auth

# 3a. Start with Cloudflare Tunnel (public access)
make up

# 3b. Or start locally only (no tunnel)
make local
```

`make up` and `make local` both automatically start `opencode serve` in the background if it isn't already running.

## Commands

```
make init         First-time setup: generate .env + cacert.pem
make auth         Authenticate with OpenCode (opens browser)
make up           Start opencode serve + LiteLLM + Cloudflare Tunnel
make local        Start opencode serve + LiteLLM (localhost only, no tunnel)
make down         Stop everything (including opencode serve)
make restart      Restart everything
make logs         Tail all docker logs
make logs-proxy   Tail proxy logs
make logs-litellm Tail LiteLLM logs
make logs-serve   Tail opencode serve logs
make status       Show all service status
make health       Check health endpoints
make test-curl    Quick smoke test
```

## Configure Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000/v1
export ANTHROPIC_API_KEY=<LITELLM_MASTER_KEY from .env>
```

## Using with OpenCode CLI

```bash
# Local
export OPENAI_API_KEY="<LITELLM_MASTER_KEY>"
export OPENAI_BASE_URL="http://localhost:4000/v1"

# Or remote (via tunnel, requires make up)
export OPENAI_API_KEY="<LITELLM_MASTER_KEY>"
export OPENAI_BASE_URL="https://litellm.ryan-schachte.com/v1"

# Use any model from the config
opencode -m openai/claude-sonnet-4-6
```

When using a custom `OPENAI_BASE_URL`, prefix all models with `openai/`, even non-OpenAI models.

## Configure OpenCode as a Provider

Add LiteLLM as a custom provider in `opencode.json`. This routes OpenCode through LiteLLM instead of directly to the upstream APIs, giving you centralized logging, rate limiting, and spend tracking.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "litellm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LiteLLM Proxy",
      "options": {
        "baseURL": "http://localhost:4000/v1",
        "apiKey": "{env:LITELLM_MASTER_KEY}"
      },
      "models": {
        "claude-3-haiku-20240307":    { "name": "Claude 3 Haiku" },
        "claude-opus-4-0":            { "name": "Claude Opus 4.0" },
        "claude-opus-4-1-20250805":   { "name": "Claude Opus 4.1 (2025-08-05)" },
        "claude-opus-4-20250514":     { "name": "Claude Opus 4 (2025-05-14)" },
        "claude-opus-4-5":            { "name": "Claude Opus 4.5" },
        "claude-opus-4-5-20251101":   { "name": "Claude Opus 4.5 (2025-11-01)" },
        "claude-opus-4-6":            { "name": "Claude Opus 4.6" },
        "claude-sonnet-4-5":          { "name": "Claude Sonnet 4.5" },
        "claude-sonnet-4-5-20250929": { "name": "Claude Sonnet 4.5 (2025-09-29)" },
        "claude-sonnet-4-6":          { "name": "Claude Sonnet 4.6" },
        "gemini-2.5-flash":           { "name": "Gemini 2.5 Flash" },
        "gemini-2.5-pro":             { "name": "Gemini 2.5 Pro" },
        "gemini-3-flash-preview":     { "name": "Gemini 3 Flash Preview" },
        "gemini-3-pro-preview":       { "name": "Gemini 3 Pro Preview" },
        "gemini-3.1-pro-preview":     { "name": "Gemini 3.1 Pro Preview" },
        "gpt-4.1":                    { "name": "GPT-4.1" },
        "gpt-4.1-mini":               { "name": "GPT-4.1 Mini" },
        "gpt-4.1-nano":               { "name": "GPT-4.1 Nano" },
        "gpt-4o":                     { "name": "GPT-4o" },
        "gpt-4o-2024-05-13":          { "name": "GPT-4o (2024-05-13)" },
        "gpt-4o-2024-08-06":          { "name": "GPT-4o (2024-08-06)" },
        "gpt-4o-2024-11-20":          { "name": "GPT-4o (2024-11-20)" },
        "gpt-5-mini":                 { "name": "GPT-5 Mini" },
        "gpt-5.1":                    { "name": "GPT-5.1" },
        "gpt-5.1-chat-latest":        { "name": "GPT-5.1 Chat Latest" },
        "gpt-5.2":                    { "name": "GPT-5.2" },
        "gpt-5.4":                    { "name": "GPT-5.4" },
        "o1":                         { "name": "o1" },
        "o3-mini":                    { "name": "o3-mini" },
        "o4-mini":                    { "name": "o4-mini" },
        "kimi-k2.5":                  { "name": "Kimi K2.5 (Workers AI)" },
        "glm-4.7-flash":              { "name": "GLM-4.7 Flash (Workers AI)" }
      }
    }
  }
}
```

For remote access via the tunnel, change `baseURL` to `https://litellm.ryan-schachte.com/v1`.

> **Note:** This creates a loop — OpenCode → LiteLLM → proxy → opencode serve → real provider. Useful for observability and spend tracking; skip it if you just want direct provider access.

## Web UI

```
Local:  http://localhost:4000/ui/
Remote: https://litellm.ryan-schachte.com/ui/
```

Login with `UI_USERNAME` / `UI_PASSWORD` from `.env`.

## Remote Access

`make up` exposes LiteLLM at `litellm.ryan-schachte.com` via Cloudflare Tunnel (protected by Cloudflare Access). To use from another machine:

```bash
# Install cloudflared (one-time)
brew install cloudflared

# Authenticate (one-time)
cloudflared access login https://litellm.ryan-schachte.com

# Make requests
cloudflared access curl https://litellm.ryan-schachte.com/v1/chat/completions \
  -X POST \
  -H "Authorization: Bearer <LITELLM_MASTER_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Hello!"}]}'
```

## Available Models

Models are defined in `config.local.yaml`. Current list:

| Provider | Models |
|----------|--------|
| Anthropic | `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-opus-4-6`, `claude-opus-4-5`, `claude-opus-4-0`, and dated variants |
| OpenAI | `gpt-4o`, `gpt-4.1`, `gpt-5.1`, `gpt-5.2`, `o1`, `o3-mini`, `o4-mini`, and more |
| Google | `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-3-flash-preview`, `gemini-3-pro-preview`, `gemini-3.1-pro-preview` |
| Workers AI | `kimi-k2.5`, `glm-4.7-flash` |
