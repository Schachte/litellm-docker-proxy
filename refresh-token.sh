#!/bin/bash
# Refresh Cloudflare Access token for the OpenCode API.
#
# Uses `cloudflared access login <URL>` which writes a token to
# ~/.cloudflared/<hostname>-*-token — the proxy reads that file dynamically
# on every request, so no container restart is needed after refreshing.
#
# Usage:
#   ./refresh-token.sh                      # reads API_BASE_URL from .env
#   ./refresh-token.sh https://my.host.com  # explicit URL

set -e

# ── Resolve target URL ───────────────────────────────────────────────────────
if [ -n "$1" ]; then
    TARGET_URL="$1"
elif [ -f .env ]; then
    TARGET_URL=$(grep -E '^API_BASE_URL=' .env | cut -d= -f2- | tr -d '"'"'" | head -1)
fi

if [ -z "$TARGET_URL" ]; then
    echo "Error: could not determine API_BASE_URL."
    echo "Usage: $0 <URL>  or set API_BASE_URL in .env"
    exit 1
fi

HOSTNAME=$(python3 -c "from urllib.parse import urlparse; print(urlparse('$TARGET_URL').hostname)")

echo "Authenticating with Cloudflare Access: $TARGET_URL"

# ── Primary: cloudflared access login ────────────────────────────────────────
if command -v cloudflared &>/dev/null; then
    cloudflared access login "$TARGET_URL"
    TOKEN_FILE=$(ls -t "$HOME/.cloudflared/${HOSTNAME}-"*"-token" 2>/dev/null | head -1)
    if [ -n "$TOKEN_FILE" ]; then
        echo "Token written to: $TOKEN_FILE"
        echo "Proxy reads this file on each request — no restart needed."
        # Keep .env in sync as fallback
        TOKEN=$(cat "$TOKEN_FILE")
        if grep -q "^CF_ACCESS_TOKEN=" .env 2>/dev/null; then
            sed -i '' "s|^CF_ACCESS_TOKEN=.*|CF_ACCESS_TOKEN=$TOKEN|" .env
        else
            echo "CF_ACCESS_TOKEN=$TOKEN" >> .env
        fi
        echo "Done."
        exit 0
    fi
fi

# ── Fallback: opencode auth login ────────────────────────────────────────────
echo "cloudflared not found or token not written, trying opencode auth login..."
opencode auth login "$TARGET_URL"

TOKEN_FILE=$(ls -t "$HOME/.cloudflared/${HOSTNAME}-"*"-token" 2>/dev/null | head -1)
if [ -z "$TOKEN_FILE" ]; then
    echo "Error: Token file not found after login."
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE")
if grep -q "^CF_ACCESS_TOKEN=" .env 2>/dev/null; then
    sed -i '' "s|^CF_ACCESS_TOKEN=.*|CF_ACCESS_TOKEN=$TOKEN|" .env
else
    echo "CF_ACCESS_TOKEN=$TOKEN" >> .env
fi

echo "Token saved to .env. Proxy will pick it up on the next request."
