.PHONY: help up local auth down restart logs logs-proxy logs-litellm status health test-curl inject-opencode

OPENCODE_PORT := 4096
LITELLM_URL   ?= http://localhost:4000/v1

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ─── First-time setup ─────────────────────────────────────────────────────────

.env:
	@cp .env.example .env
	@python3 -c "\
import re, secrets; \
txt = open('.env').read(); \
txt = re.sub(r'^LITELLM_MASTER_KEY=.*', 'LITELLM_MASTER_KEY=sk-litellm-' + secrets.token_hex(16), txt, flags=re.M); \
txt = re.sub(r'^LITELLM_SALT_KEY=.*',   'LITELLM_SALT_KEY=sk-litellm-'   + secrets.token_hex(16), txt, flags=re.M); \
open('.env', 'w').write(txt)"
	@echo "Created .env with random LiteLLM keys"

cacert.pem:
	@if [ "$$(uname)" = "Darwin" ]; then \
	    security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > cacert.pem; \
	elif [ -f /etc/ssl/certs/ca-certificates.crt ]; then \
	    cp /etc/ssl/certs/ca-certificates.crt cacert.pem; \
	elif [ -f /etc/ssl/cert.pem ]; then \
	    cp /etc/ssl/cert.pem cacert.pem; \
	else \
	    echo "Cannot locate system CA bundle — create cacert.pem manually"; exit 1; \
	fi
	@echo "Generated cacert.pem"

init: .env cacert.pem ## First-time setup: generate .env + cacert.pem
	@echo ""
	@echo "Setup complete. Next: make auth && make up"

# ─── Auth ────────────────────────────────────────────────────────────────────

auth: ## Authenticate with OpenCode (opens browser)
	opencode auth login

# ─── Serve ───────────────────────────────────────────────────────────────────

_serve:
	@if lsof -i :$(OPENCODE_PORT) -sTCP:LISTEN > /dev/null 2>&1; then \
		echo "opencode serve already running on :$(OPENCODE_PORT)"; \
	else \
		echo "Starting opencode serve on :$(OPENCODE_PORT)..."; \
		nohup opencode serve --port $(OPENCODE_PORT) > /tmp/opencode-serve.log 2>&1 & \
		echo $$! > .opencode.pid; \
		for i in $$(seq 1 10); do \
			sleep 1; \
			if lsof -i :$(OPENCODE_PORT) -sTCP:LISTEN > /dev/null 2>&1; then break; fi; \
		done; \
		if lsof -i :$(OPENCODE_PORT) -sTCP:LISTEN > /dev/null 2>&1; then \
			echo "opencode serve started (pid $$(cat .opencode.pid))"; \
		else \
			echo "ERROR: opencode serve failed to start — check /tmp/opencode-serve.log"; \
			exit 1; \
		fi; \
	fi

# ─── Run ─────────────────────────────────────────────────────────────────────

up: _serve ## Start opencode serve + LiteLLM + Cloudflare Tunnel
	docker compose --profile tunnel up -d --build
	@echo ""
	@echo "LiteLLM ready:"
	@echo "  Local:  http://localhost:4000"
	@echo "  Public: https://litellm.ryan-schachte.com"

local: _serve ## Start opencode serve + LiteLLM (localhost only, no tunnel)
	docker compose up -d --build
	@echo ""
	@echo "LiteLLM ready: http://localhost:4000"

# ─── Docker ──────────────────────────────────────────────────────────────────

down: ## Stop all services (including opencode serve)
	docker compose --profile tunnel down
	@if [ -f .opencode.pid ]; then \
		PID=$$(cat .opencode.pid); \
		if kill -0 $$PID 2>/dev/null; then \
			kill $$PID && echo "Stopped opencode serve (pid $$PID)"; \
		fi; \
		rm -f .opencode.pid; \
	elif lsof -ti :$(OPENCODE_PORT) -sTCP:LISTEN > /dev/null 2>&1; then \
		kill $$(lsof -ti :$(OPENCODE_PORT) -sTCP:LISTEN) 2>/dev/null && echo "Stopped opencode serve"; \
	fi

restart: down up ## Restart everything

# ─── Logs ────────────────────────────────────────────────────────────────────

logs: ## Tail logs for all services
	docker compose logs -f

logs-proxy: ## Tail proxy logs
	docker compose logs -f proxy

logs-litellm: ## Tail LiteLLM logs
	docker compose logs -f litellm

logs-serve: ## Tail opencode serve logs
	@tail -f /tmp/opencode-serve.log

# ─── Status ──────────────────────────────────────────────────────────────────

status: ## Show service status
	@docker compose --profile tunnel ps
	@echo ""
	@if lsof -i :$(OPENCODE_PORT) -sTCP:LISTEN > /dev/null 2>&1; then \
		echo "opencode serve: running on :$(OPENCODE_PORT)"; \
	else \
		echo "opencode serve: not running"; \
	fi

health: ## Check health endpoints
	@echo "LiteLLM: " && curl -sf http://localhost:4000/health/liveliness && echo ""

# ─── Testing ─────────────────────────────────────────────────────────────────

test-curl: ## Quick smoke test via curl
	@MASTER_KEY=$$(grep LITELLM_MASTER_KEY .env | cut -d= -f2); \
	echo "=== Testing via LiteLLM (localhost:4000) ==="; \
	curl -s http://localhost:4000/v1/chat/completions \
	  -H "Content-Type: application/json" \
	  -H "Authorization: Bearer $$MASTER_KEY" \
	  -d '{"model":"claude-sonnet-4-5","messages":[{"role":"user","content":"Say hello in one word"}]}' \
	  | python3 -m json.tool

# ─── OpenCode integration ─────────────────────────────────────────────────────

inject-opencode: ## Inject LiteLLM provider into ~/.config/opencode/opencode.json (override: LITELLM_URL=...)
	@python3 -c "\
import re, json, os; \
url = '$(LITELLM_URL)'; \
names = re.findall(r'model_name:\s*(\S+)', open('config.local.yaml').read()); \
models = {n: {'name': n} for n in names}; \
p = os.path.expanduser('~/.config/opencode/opencode.json'); \
os.makedirs(os.path.dirname(p), exist_ok=True); \
cfg = json.load(open(p)) if os.path.exists(p) else {}; \
cfg.setdefault('\$$schema', 'https://opencode.ai/config.json'); \
cfg.setdefault('provider', {})['litellm'] = { \
  'npm': '@ai-sdk/openai-compatible', \
  'name': 'LiteLLM Proxy', \
  'options': {'baseURL': url, 'apiKey': '{env:LITELLM_MASTER_KEY}'}, \
  'models': models}; \
json.dump(cfg, open(p, 'w'), indent=2); \
print(f'Injected {len(models)} models into {p}')"
	@echo ""
	@echo "Ensure LITELLM_MASTER_KEY is exported in your shell:"
	@echo "  export LITELLM_MASTER_KEY=\$$(grep LITELLM_MASTER_KEY .env | cut -d= -f2)"
