#!/bin/bash
# Refresh CF Access token via opencode auth

set -e

echo "Authenticating with opencode..."
opencode auth login https://opencode.cloudflare.dev

# Find the newly created token
TOKEN_FILE=$(ls -t ~/.cloudflared/opencode.cloudflare.dev-*-token 2>/dev/null | head -1)

if [ -z "$TOKEN_FILE" ]; then
    echo "Error: Token file not found after login"
    exit 1
fi

TOKEN=$(cat "$TOKEN_FILE")

# Update .env file
if grep -q "^CF_ACCESS_TOKEN=" .env 2>/dev/null; then
    sed -i '' "s|^CF_ACCESS_TOKEN=.*|CF_ACCESS_TOKEN=$TOKEN|" .env
else
    echo "CF_ACCESS_TOKEN=$TOKEN" >> .env
fi

echo "Token refreshed in .env"
