# fastapi-topaz Makefile
# Unified Makefile for library development and integration tests

.DEFAULT_GOAL := help
.PHONY: help setup clean lint lint-fix quality test test-fast ci info
.PHONY: docs docs-serve docs-build docs-deploy
.PHONY: py-security typecheck version build test-upload upload git-status git-tag release
.PHONY: int-build int-up int-down int-restart int-restart-webapp int-clean int-status int-setup
.PHONY: int-logs int-logs1 int-logs5 int-logs-webapp int-logs-topaz int-logs-authentik
.PHONY: int-db-upgrade int-db-migrate int-db-downgrade int-db-shell
.PHONY: int-shell int-topaz-shell int-topaz-reload int-auth-password int-certs
.PHONY: int-tf-init int-tf-plan int-tf-apply int-tf-destroy
.PHONY: int-lint int-lint-fix
.PHONY: e2e e2e-fast e2e-alice e2e-bob e2e-cookies e2e-clean

# Colors
RESET := \033[0m
BOLD := \033[1m
CYAN := \033[36m
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m

# Paths
INT_DIR := integration-tests
E2E_DIR := integration-tests/e2e
TF_DIR := integration-tests/infra/terraform/authentik-webapp

##@ Help
help: ## Display this help message
	@echo "$(BLUE)fastapi-topaz$(RESET) - Library + Integration Tests"
	@echo "=================================================="
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make $(YELLOW)<target>$(RESET)\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2 } /^##@/ { printf "\n$(GREEN)%s$(RESET)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

cmd-exists-%:
	@hash $(*) > /dev/null 2>&1 || \
		(echo "ERROR: '$(*)' must be installed and available on your PATH."; exit 1)

# ==============================================================================
##@ Library
# ==============================================================================
setup: cmd-exists-uv ## Setup development environment
	uv venv
	uv sync --all-extras

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .coverage htmlcov/ .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

lint: cmd-exists-uv ## Run ruff linter
	@echo "$(BLUE)Running ruff linter on library...$(RESET)"
	uv run ruff check src/ test/
	@echo "$(GREEN)OK$(RESET)"

lint-fix: cmd-exists-uv ## Fix linting issues and format
	uv run ruff check src/ test/ --fix
	uv run ruff format src/ test/

quality: lint typecheck ## Run all quality checks

test: cmd-exists-uv ## Run unit tests with coverage
	@echo "$(BLUE)Running unit tests...$(RESET)"
	uv run pytest test/ -v

test-fast: cmd-exists-uv ## Run unit tests without coverage
	uv run pytest test/ -v --no-cov

ci: quality test ## Run all CI checks
	@echo "$(GREEN)CI passed$(RESET)"

# ==============================================================================
##@ Security
# ==============================================================================
py-security: ## Run security audit (pip-audit + bandit)
py-security: cmd-exists-uv
	@echo "$(BLUE)Running security audit...$(RESET)"
	@echo "$(YELLOW)Checking dependencies with pip-audit...$(RESET)"
	-uv run pip-audit
	@echo ""
	@echo "$(YELLOW)Scanning code with bandit...$(RESET)"
	uv run bandit -r src/fastapi_topaz
	@echo "$(GREEN)Security audit complete$(RESET)"

# ==============================================================================
##@ Type Checking
# ==============================================================================
typecheck: ## Run pyright type checker
typecheck: cmd-exists-uv
	@echo "$(BLUE)Running pyright type checker...$(RESET)"
	uv run pyright src/fastapi_topaz
	@echo "$(GREEN)Type checking complete$(RESET)"

# ==============================================================================
##@ Documentation
# ==============================================================================
docs: docs-serve ## Alias for docs-serve

docs-serve: cmd-exists-uv ## Serve docs locally with live reload
	@echo "$(BLUE)Starting documentation server on port 8080...$(RESET)"
	uv run --extra docs mkdocs serve -a localhost:8080

docs-build: cmd-exists-uv ## Build static documentation
	@echo "$(BLUE)Building documentation...$(RESET)"
	uv run --extra docs mkdocs build
	@echo "$(GREEN)Documentation built in site/$(RESET)"

docs-deploy: cmd-exists-uv ## Deploy docs to GitHub Pages
	@echo "$(BLUE)Deploying documentation...$(RESET)"
	uv run --extra docs mkdocs gh-deploy --force
	@echo "$(GREEN)Documentation deployed$(RESET)"

# ==============================================================================
##@ Integration - Services
# ==============================================================================
int-build: ## Build Docker containers
	@cd $(INT_DIR) && \
	if [ ! -f .env ]; then cat env.authentik .env.example > .env 2>/dev/null || cat env.authentik > .env; fi && \
	docker-compose build

int-up: ## Start all services
	@cd $(INT_DIR) && \
	if [ ! -f .env ]; then cat env.authentik .env.example > .env 2>/dev/null || cat env.authentik > .env; fi && \
	docker-compose up -d
	@echo "Services: Webapp http://localhost:8000 | Authentik http://localhost:9000"

int-down: ## Stop all services
	cd $(INT_DIR) && docker-compose down

int-restart: ## Restart all services
	cd $(INT_DIR) && docker-compose restart

int-restart-webapp: ## Rebuild and restart webapp only
	cd $(INT_DIR) && docker-compose build webapp && docker-compose up -d webapp

int-clean: ## Stop services and remove volumes
	cd $(INT_DIR) && docker-compose down -v && rm -f .env .env.oidc

int-status: ## Show service status and health
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "FastAPI-Topaz POC - Service Status"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo ""
	@echo "Web Services:"
	@echo "  Webapp:          http://localhost:8000"
	@echo "  Swagger API:     http://localhost:8000/docs"
	@echo "  Authentik:       http://localhost:9000"
	@echo "  Location API:    http://localhost:8001"
	@echo ""
	@echo "Authorization:"
	@echo "  Topaz Authorizer:  grpc://localhost:8282"
	@echo "  Topaz Gateway:     http://localhost:8383"
	@echo ""
	@echo "Databases:"
	@echo "  Webapp DB:         postgresql://localhost:5432/webapp_db"
	@echo "  Authentik DB:      postgresql://localhost:5433"
	@echo ""
	@echo "Container Status:"
	@cd $(INT_DIR) && docker-compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  Containers not running"
	@echo ""
	@echo "Health Checks:"
	@printf "  Webapp:           " && curl -sf http://localhost:8000/health >/dev/null 2>&1 && echo "$(GREEN)Healthy$(RESET)" || echo "$(YELLOW)Unhealthy$(RESET)"
	@printf "  Mock Location:    " && curl -sf http://localhost:8001/health >/dev/null 2>&1 && echo "$(GREEN)Healthy$(RESET)" || echo "$(YELLOW)Unhealthy$(RESET)"
	@printf "  Authentik:        " && curl -sf http://localhost:9000/-/health/ready/ >/dev/null 2>&1 && echo "$(GREEN)Healthy$(RESET)" || echo "$(YELLOW)Unhealthy$(RESET)"
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "Run 'make int-logs' to view logs, 'make help' for more commands"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

int-setup: int-certs int-build int-up ## Full setup (certs + build + start + migrate + terraform)
	@echo "Waiting for services..."
	@sleep 15
	@$(MAKE) int-db-upgrade
	@$(MAKE) int-tf-init
	@$(MAKE) int-tf-apply
	@$(MAKE) int-status
	@echo "$(GREEN)Integration environment ready!$(RESET)"

# ==============================================================================
##@ Integration - Logs
# ==============================================================================
int-logs: ## View all service logs (follow)
	cd $(INT_DIR) && docker-compose logs -f

int-logs1: ## View logs from last 1 minute
	cd $(INT_DIR) && docker-compose logs --since 1m

int-logs5: ## View logs from last 5 minutes
	cd $(INT_DIR) && docker-compose logs --since 5m

int-logs-webapp: ## View webapp logs only
	cd $(INT_DIR) && docker-compose logs -f webapp

int-logs-topaz: ## View Topaz logs only
	cd $(INT_DIR) && docker-compose logs -f topaz

int-logs-authentik: ## View Authentik logs only
	cd $(INT_DIR) && docker-compose logs -f authentik-server

# ==============================================================================
##@ Integration - Database
# ==============================================================================
int-db-upgrade: ## Run database migrations
	cd $(INT_DIR) && docker-compose exec webapp uv run alembic upgrade head

int-db-migrate: ## Generate new migration (usage: make int-db-migrate msg="description")
	cd $(INT_DIR) && docker-compose exec webapp uv run alembic revision --autogenerate -m "$(msg)"

int-db-downgrade: ## Rollback last migration
	cd $(INT_DIR) && docker-compose exec webapp uv run alembic downgrade -1

int-db-shell: ## Open PostgreSQL shell
	cd $(INT_DIR) && docker-compose exec postgres psql -U webapp -d webapp_db

# ==============================================================================
##@ Integration - Shells & Debug
# ==============================================================================
int-shell: ## Open webapp container shell
	cd $(INT_DIR) && docker-compose exec webapp /bin/bash

int-topaz-shell: ## Open Topaz container shell
	cd $(INT_DIR) && docker-compose exec topaz /bin/sh

int-topaz-reload: ## Reload Topaz policies
	cd $(INT_DIR) && docker-compose restart topaz
	@echo "Topaz restarted with updated policies"

int-auth-password: ## Get Authentik bootstrap password
	@echo "Authentik Bootstrap Password:"
	@grep '^AUTHENTIK_BOOTSTRAP_PASSWORD' $(INT_DIR)/env.authentik | cut -d= -f2

int-certs: ## Generate TLS certificates for Topaz
	@echo "Generating TLS certificates..."
	@mkdir -p $(INT_DIR)/infra/certs
	@cd $(INT_DIR)/infra/certs && \
	if [ ! -f ca.crt ]; then \
		echo "Creating CA..."; \
		openssl genrsa -out ca.key 4096; \
		openssl req -new -x509 -days 3650 -key ca.key -out ca.crt \
			-subj "/CN=Topaz Dev CA/O=FastAPI-Topaz/C=US"; \
		echo "Creating Topaz server cert..."; \
		openssl genrsa -out topaz.key 2048; \
		openssl req -new -key topaz.key -out topaz.csr \
			-subj "/CN=topaz/O=FastAPI-Topaz/C=US"; \
		echo "subjectAltName=DNS:topaz,DNS:localhost,IP:127.0.0.1" > topaz.ext; \
		openssl x509 -req -days 365 -in topaz.csr -CA ca.crt -CAkey ca.key \
			-CAcreateserial -out topaz.crt -extfile topaz.ext; \
		rm -f topaz.csr topaz.ext; \
		chmod 644 ca.crt topaz.crt; \
		chmod 600 ca.key topaz.key; \
		echo "$(GREEN)Certificates generated in $(INT_DIR)/infra/certs/$(RESET)"; \
	else \
		echo "Certificates already exist. Delete $(INT_DIR)/infra/certs/ to regenerate."; \
	fi

# ==============================================================================
##@ Integration - Terraform
# ==============================================================================
int-tf-init: ## Initialize Terraform
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' $(INT_DIR)/env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform init

int-tf-plan: ## Plan Terraform changes
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' $(INT_DIR)/env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform plan

int-tf-apply: ## Apply Terraform (create OIDC + users)
	@echo "Waiting for Authentik to be ready..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12; do \
		if curl -sf http://localhost:9000/-/health/ready/ >/dev/null 2>&1; then \
			echo "$(GREEN)Authentik ready$(RESET)"; \
			break; \
		fi; \
		echo "  Waiting... ($$i/12)"; \
		sleep 5; \
	done
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' $(INT_DIR)/env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform apply -auto-approve
	@cd $(INT_DIR) && docker-compose restart webapp
	@echo "$(GREEN)Test users: alice@example.com, bob@example.com, charlie@example.com (password: password)$(RESET)"

int-tf-destroy: ## Destroy Terraform resources
	@export TF_VAR_authentik_token=$$(grep '^AUTHENTIK_BOOTSTRAP_TOKEN' $(INT_DIR)/env.authentik | cut -d= -f2) && \
	cd $(TF_DIR) && terraform destroy -auto-approve

# ==============================================================================
##@ Integration - Quality
# ==============================================================================
int-lint: ## Lint webapp and e2e tests
	@echo "$(BLUE)Linting integration tests...$(RESET)"
	cd $(INT_DIR)/webapp && uv run ruff check .
	cd $(E2E_DIR) && uv run ruff check .
	@echo "$(GREEN)OK$(RESET)"

int-lint-fix: ## Fix linting in integration tests
	cd $(INT_DIR)/webapp && uv run ruff check . --fix && uv run ruff format .
	cd $(E2E_DIR) && uv run ruff check . --fix && uv run ruff format .

# ==============================================================================
##@ E2E Tests
# ==============================================================================
e2e-init: ## Init e2e tests
	cd $(E2E_DIR) && uv sync

e2e: ## Run all e2e tests
	cd $(E2E_DIR) && uv run python run_tests.py

e2e-fast: ## Run e2e tests with cached cookies
	cd $(E2E_DIR) && uv run python run_tests.py

e2e-alice: ## Run Alice workflow tests
	cd $(E2E_DIR) && uv run python run_tests.py alice

e2e-bob: ## Run Bob workflow tests
	cd $(E2E_DIR) && uv run python run_tests.py bob

e2e-cookies: ## Get session cookies for testing
	cd $(E2E_DIR) && uv run python run_tests.py --get-cookies

e2e-clean: ## Clean e2e test artifacts
	cd $(E2E_DIR) && rm -rf __pycache__ .pytest_cache .ruff_cache .env.test

# ==============================================================================
##@ Publishing
# ==============================================================================
version: ## Display current package version
	@grep '^version =' pyproject.toml | cut -d'"' -f2

build: clean ## Build distribution packages
build: cmd-exists-uv
	@echo "$(BLUE)Building distribution packages...$(RESET)"
	uv build
	@echo "$(GREEN)Build complete$(RESET)"
	@ls -lh dist/

test-upload: build ## Upload to TestPyPI
test-upload: cmd-exists-uv
	@echo "$(BLUE)Uploading to TestPyPI...$(RESET)"
	uv run twine upload --repository testpypi dist/*
	@echo "$(GREEN)Upload to TestPyPI complete$(RESET)"

upload: build ## Upload to production PyPI
upload: cmd-exists-uv
	@echo "$(BOLD)$(YELLOW)WARNING: Uploading to PRODUCTION PyPI$(RESET)"
	@read -p "Are you sure? Type 'yes' to continue: " confirm; \
	if [ "$$confirm" != "yes" ]; then \
		echo "Upload cancelled"; \
		exit 1; \
	fi
	uv run twine upload dist/*
	@echo "$(GREEN)Upload to PyPI complete$(RESET)"

# ==============================================================================
##@ Git
# ==============================================================================
git-status: ## Show git status
	@git status
	@echo ""
	@git diff --name-status

git-tag: ## Create and push git tag for current version
	@VERSION=$$(grep '^version =' pyproject.toml | cut -d'"' -f2); \
	echo "$(BLUE)Creating tag v$$VERSION...$(RESET)"; \
	git tag -a "v$$VERSION" -m "Release v$$VERSION"; \
	git push origin "v$$VERSION"; \
	echo "$(GREEN)Tag v$$VERSION pushed$(RESET)"

release: build git-tag upload ## Full release: build, tag, upload
	@VERSION=$$(grep '^version =' pyproject.toml | cut -d'"' -f2); \
	echo "$(GREEN)Released v$$VERSION$(RESET)"

# ==============================================================================
##@ Info
# ==============================================================================
info: ## Show project information
	@echo "$(BLUE)fastapi-topaz$(RESET)"
	@echo "=================================================="
	@echo ""
	@echo "$(YELLOW)Structure:$(RESET)"
	@echo "  Library:     src/fastapi_topaz/"
	@echo "  Unit Tests:  test/"
	@echo "  Integration: integration-tests/"
	@echo "  E2E Tests:   integration-tests/e2e/"
	@echo ""
	@echo "$(YELLOW)Quick Start:$(RESET)"
	@echo "  Library dev:  make setup && make test"
	@echo "  Integration:  make int-setup && make e2e"
