# LiteLLM Proxy for OpenCode

LiteLLM gateway that proxies Claude Code and OpenAI requests through an OpenCode server
protected by Cloudflare Access.

## Architecture

```
                  ┌─── docker compose ──────────────────────────────────┐
                  │                                                      │
  Claude Code     │  ┌──────────┐   ┌──────────────────────────────┐   │   ┌──────────────────┐
  OpenAI clients  │  │          │   │            proxy             │   │   │  Cloudflare      │
  ───────────────▶│  │ LiteLLM  │──▶│  strips auth headers         │───┼──▶│  Access          │──▶ OpenCode
       :4000      │  │  :4000   │   │  injects cf-access-token     │   │   │  (JWT validate)  │
                  │  │          │   │            :8080              │   │   └──────────────────┘
                  │  └──────────┘   └──────────────┬───────────────┘   │
                  │  ┌──────────┐                  │ (volume mount)    │
                  │  │ Postgres │   ~/.cloudflared/<host>-*-token       │
                  │  └──────────┘   re-read on every request           │
                  └──────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. First-time setup (auth + .env + cacert.pem)
./setup.sh --url https://llmapi.yourdomain.com

# 2. Start
docker compose up -d
```

## Setup Details

`setup.sh` handles everything interactively:

- Authenticates with Cloudflare Access via `cloudflared access login`
- Writes a token to `~/.cloudflared/<hostname>-*-token`
- Generates `.env` with random LiteLLM keys
- Generates `cacert.pem` from the system keychain

The proxy container mounts `~/.cloudflared` read-only and re-reads the token
file on every request — **no restart needed after `refresh-token.sh`**.

## Manual Setup

```bash
# 1. Create .env
cat > .env <<EOF
API_BASE_URL=https://llmapi.yourdomain.com
CF_ACCESS_TOKEN=        # fallback only; token file is preferred
LITELLM_MASTER_KEY=sk-litellm-change-me
LITELLM_SALT_KEY=sk-litellm-change-me
EOF

# 2. Generate cacert.pem (macOS)
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > cacert.pem

# 3. Authenticate
./refresh-token.sh

# 4. Start
docker compose up -d
```

## Configure Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000/v1
export ANTHROPIC_API_KEY=<LITELLM_MASTER_KEY from .env>
```

## Token Refresh

CF Access tokens expire (~24 h). Refresh without restarting:

```bash
./refresh-token.sh
```

The proxy picks up the new token from `~/.cloudflared/<hostname>-*-token`
on the next request automatically.

## Commands

```bash
make up          # Start all services
make down        # Stop all services
make restart     # Restart all services
make logs        # Tail all logs
make logs-proxy  # Tail proxy logs only
make status      # Show service status
make health      # Check proxy health
make auth        # Re-authenticate with Cloudflare Access
make setup       # Run interactive setup
```

## Token Sources (priority order)

1. `~/.cloudflared/<hostname>-*-token` — written by `cloudflared access login`
2. `CF_ACCESS_TOKEN` env var in `.env` — fallback

## Available Models

**Anthropic**: `claude-sonnet-4-20250514`, `claude-opus-4-5-20251101`, all claude-3.x variants

**OpenAI**: `gpt-4o`, `gpt-4o-mini`, `o1`, `o3`, `o3-mini`, `o4-mini`, and more
