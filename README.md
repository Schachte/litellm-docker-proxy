# LiteLLM Proxy for OpenCode

LiteLLM gateway that proxies Claude Code requests through OpenCode (Cloudflare Access protected).

## Setup

1. **Create `.env`**:
   ```bash
   LITELLM_MASTER_KEY=sk-litellm-master-key-change-me
   LITELLM_SALT_KEY=sk-litellm-salt-key-change-me
   CF_ACCESS_TOKEN=<your-token>
   ```

2. **Generate SSL certs** (macOS):
   ```bash
   security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > cacert.pem
   ```

3. **Authenticate & start**:
   ```bash
   ./refresh-token.sh
   docker compose up -d
   ```

## Configure Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:4000/v1
export ANTHROPIC_API_KEY=sk-litellm-master-key-change-me
```

## Token Refresh

```bash
./refresh-token.sh && docker compose restart proxy
```

## Available Models

- `claude-sonnet-4-20250514`, `claude-opus-4-5-20251101`
- `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini`
