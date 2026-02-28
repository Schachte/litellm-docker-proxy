.PHONY: help setup auth up down restart logs logs-proxy logs-litellm status health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ─── Setup ───────────────────────────────────────────────────────────────────

setup: ## Run interactive setup (auth + .env + cacert.pem)
	./setup.sh

auth: ## Refresh Cloudflare Access token (no restart needed)
	./refresh-token.sh

# ─── Docker ──────────────────────────────────────────────────────────────────

up: ## Start all services (detached)
	docker compose up -d --build

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

# ─── Logs ────────────────────────────────────────────────────────────────────

logs: ## Tail logs for all services
	docker compose logs -f

logs-proxy: ## Tail proxy logs
	docker compose logs -f proxy

logs-litellm: ## Tail LiteLLM logs
	docker compose logs -f litellm

# ─── Status ──────────────────────────────────────────────────────────────────

status: ## Show service status
	docker compose ps

health: ## Check proxy health endpoints
	@echo "Anthropic proxy:" && curl -sf http://localhost:8080/health && echo ""
	@echo "OpenAI proxy:   " && curl -sf http://localhost:8081/health && echo ""
	@echo "LiteLLM:        " && curl -sf http://localhost:4000/health/liveliness && echo ""
