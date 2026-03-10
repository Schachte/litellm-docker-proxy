#!/bin/bash
# Login to Cloudflare Access for tunnel and export token

set -e

TUNNEL_HOSTNAME="${1:-}"

if [ -z "$TUNNEL_HOSTNAME" ]; then
    echo "Usage: ./tunnel-login.sh your-subdomain.your-domain.com"
    exit 1
fi

echo "Logging in to $TUNNEL_HOSTNAME..."
cloudflared access login "https://$TUNNEL_HOSTNAME"

# Find the token file
TOKEN_FILE=$(ls -t ~/.cloudflared/${TUNNEL_HOSTNAME}-*-token 2>/dev/null | head -1)

if [ -z "$TOKEN_FILE" ]; then
    echo "Error: Token file not found"
    exit 1
fi

echo ""
echo "Token cached at: $TOKEN_FILE"
echo ""
echo "To use in requests:"
echo "  export CF_ACCESS_TOKEN=\$(cat $TOKEN_FILE)"
echo "  curl -H \"cf-access-token: \$CF_ACCESS_TOKEN\" https://$TUNNEL_HOSTNAME/v1/models"
