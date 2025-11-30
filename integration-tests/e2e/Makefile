.PHONY: help install test test-fast test-alice test-bob test-sharing test-failures test-public cookies clean lint format quality check-services setup

# Colors for output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m # No Color

help:
	@echo "$(BLUE)Integration Tests - Available Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Setup:$(NC)"
	@echo "  make install          - Install package and dependencies"
	@echo "  make setup            - Complete setup (services + users + install)"
	@echo ""
	@echo "$(GREEN)Testing:$(NC)"
	@echo "  make test             - Run all integration tests"
	@echo "  make test-fast        - Run tests with cached cookies (skip auth)"
	@echo "  make test-alice       - Run Alice's workflow tests"
	@echo "  make test-bob         - Run Bob's workflow tests"
	@echo "  make test-sharing     - Run document sharing tests"
	@echo "  make test-failures    - Run authorization failure tests"
	@echo "  make test-public      - Run public document tests"
	@echo "  make test-verbose     - Run tests with verbose output"
	@echo "  make test-debug       - Run tests with print statements"
	@echo ""
	@echo "$(GREEN)Authentication:$(NC)"
	@echo "  make cookies          - Get session cookies via HTTP auth"
	@echo "  make cookies-debug    - Get cookies with debug output (troubleshooting)"
	@echo "  make cookies-show     - Display current cookie values"
	@echo "  make cookies-clear    - Clear cached cookies"
	@echo ""
	@echo "$(GREEN)Quality:$(NC)"
	@echo "  make lint             - Run linter (ruff)"
	@echo "  make format           - Format code (ruff)"
	@echo "  make typecheck        - Run type checker (basedpyright)"
	@echo "  make quality          - Run all quality checks"
	@echo ""
	@echo "$(GREEN)Services:$(NC)"
	@echo "  make check-services   - Check if required services are running"
	@echo "  make start-services   - Start all services (docker-compose)"
	@echo "  make stop-services    - Stop all services"
	@echo "  make create-users     - Create test users in Authentik"
	@echo ""
	@echo "$(GREEN)Maintenance:$(NC)"
	@echo "  make clean            - Remove cache and temp files"
	@echo "  make clean-all        - Deep clean (venv + cache)"
	@echo ""
	@echo "$(YELLOW)Quick Start:$(NC)"
	@echo "  1. make setup         # One-time setup"
	@echo "  2. make test          # Run tests"
	@echo ""

# Installation
install:
	@echo "$(BLUE)Installing integration tests package...$(NC)"
	uv pip install -e .
	@echo "$(GREEN)✓ Installation complete$(NC)"

install-dev:
	@echo "$(BLUE)Installing with dev dependencies...$(NC)"
	uv pip install -e ".[dev]"
	@echo "$(GREEN)✓ Dev installation complete$(NC)"

# Setup
setup: check-services create-users install cookies
	@echo ""
	@echo "$(GREEN)========================================$(NC)"
	@echo "$(GREEN)✓ Setup complete!$(NC)"
	@echo "$(GREEN)========================================$(NC)"
	@echo ""
	@echo "Run tests with: make test"
	@echo ""

check-services:
	@echo "$(BLUE)Checking services...$(NC)"
	@python run_tests.py --setup 2>/dev/null | grep -A 1 "Checking" || echo "Run 'make start-services' first"

start-services:
	@echo "$(BLUE)Starting services...$(NC)"
	cd .. && make up
	@echo "$(GREEN)✓ Services started$(NC)"
	@echo "Waiting for services to be ready..."
	@sleep 10

stop-services:
	@echo "$(BLUE)Stopping services...$(NC)"
	cd .. && make down
	@echo "$(GREEN)✓ Services stopped$(NC)"

create-users:
	@echo "$(BLUE)Creating test users in Authentik...$(NC)"
	cd .. && make tf-apply
	@echo "$(GREEN)✓ Test users created$(NC)"

# Testing
test:
	@echo "$(BLUE)Running all integration tests...$(NC)"
	uv run python run_tests.py

test-fast:
	@echo "$(BLUE)Running tests with cached cookies...$(NC)"
	@if [ -f .env.test ]; then \
		export $$(cat .env.test | xargs) && uv run python run_tests.py; \
	else \
		echo "$(YELLOW)⚠ No cached cookies found. Run 'make cookies' first$(NC)"; \
		uv run python run_tests.py; \
	fi

test-alice:
	@echo "$(BLUE)Running Alice's workflow tests...$(NC)"
	uv run python run_tests.py alice

test-bob:
	@echo "$(BLUE)Running Bob's workflow tests...$(NC)"
	uv run python run_tests.py bob

test-sharing:
	@echo "$(BLUE)Running document sharing tests...$(NC)"
	uv run python run_tests.py sharing

test-failures:
	@echo "$(BLUE)Running authorization failure tests...$(NC)"
	uv run python run_tests.py auth-failures

test-public:
	@echo "$(BLUE)Running public document tests...$(NC)"
	uv run python run_tests.py public

test-verbose:
	@echo "$(BLUE)Running tests with verbose output...$(NC)"
	uv run pytest tests/ -v

test-debug:
	@echo "$(BLUE)Running tests with print statements...$(NC)"
	uv run pytest tests/ -v -s

test-stop-on-fail:
	@echo "$(BLUE)Running tests (stop on first failure)...$(NC)"
	uv run pytest tests/ -v -x

test-filter:
	@if [ -z "$(FILTER)" ]; then \
		echo "$(YELLOW)Usage: make test-filter FILTER=<pattern>$(NC)"; \
		echo "Example: make test-filter FILTER=alice"; \
	else \
		echo "$(BLUE)Running tests matching: $(FILTER)$(NC)"; \
		uv run pytest tests/ -v -k "$(FILTER)"; \
	fi

test-cov:
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	uv run pytest tests/ -v --cov=tests --cov-report=term-missing

# Authentication
cookies:
	@echo "$(BLUE)Getting session cookies via HTTP auth...$(NC)"
	uv run python run_tests.py --get-cookies

cookies-debug:
	@echo "$(BLUE)Getting session cookies with debug output...$(NC)"
	uv run python run_tests.py --get-cookies --debug

cookies-show:
	@echo "$(BLUE)Current session cookies:$(NC)"
	@if [ -f .env.test ]; then \
		cat .env.test; \
	else \
		echo "$(YELLOW)No cookies found. Run 'make cookies' first.$(NC)"; \
	fi

cookies-clear:
	@echo "$(BLUE)Clearing cached cookies...$(NC)"
	@rm -f .env.test .env.test.local
	@echo "$(GREEN)✓ Cookies cleared$(NC)"

cookies-export:
	@if [ -f .env.test ]; then \
		echo "$(BLUE)Export these to your shell:$(NC)"; \
		echo "  export \$$(cat .env.test | xargs)"; \
	else \
		echo "$(YELLOW)No cookies found. Run 'make cookies' first.$(NC)"; \
	fi

# Quality checks
lint:
	@echo "$(BLUE)Running linter (ruff)...$(NC)"
	uv run ruff check tests/

lint-fix:
	@echo "$(BLUE)Running linter with auto-fix...$(NC)"
	uv run ruff check --fix tests/

format:
	@echo "$(BLUE)Formatting code (ruff)...$(NC)"
	uv run ruff format tests/

format-check:
	@echo "$(BLUE)Checking code format...$(NC)"
	uv run ruff format --check tests/

typecheck:
	@echo "$(BLUE)Running type checker (basedpyright)...$(NC)"
	uv run basedpyright tests/

quality: lint format-check typecheck
	@echo ""
	@echo "$(GREEN)✓ All quality checks passed!$(NC)"
	@echo ""

# CI target
ci: quality test
	@echo ""
	@echo "$(GREEN)========================================$(NC)"
	@echo "$(GREEN)✓ CI checks passed!$(NC)"
	@echo "$(GREEN)========================================$(NC)"
	@echo ""

# Cleaning
clean:
	@echo "$(BLUE)Cleaning cache and temp files...$(NC)"
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -f .coverage 2>/dev/null || true
	rm -f .env.test .env.test.local 2>/dev/null || true
	@echo "$(GREEN)✓ Cleaned$(NC)"

clean-all: clean
	@echo "$(BLUE)Deep cleaning (including venv)...$(NC)"
	rm -rf .venv 2>/dev/null || true
	rm -rf build dist 2>/dev/null || true
	@echo "$(GREEN)✓ Deep clean complete$(NC)"

# Development helpers
watch:
	@echo "$(BLUE)Watching for changes and running tests...$(NC)"
	@echo "$(YELLOW)Note: Install pytest-watch first: uv pip install pytest-watch$(NC)"
	uv run ptw tests/ -- -v

shell:
	@echo "$(BLUE)Starting Python shell with test context...$(NC)"
	uv run python -i -c "from tests.conftest import *; from tests.auth_helper import *; print('Test context loaded. Try: OIDCAuthenticator()')"

# Info
info:
	@echo "$(BLUE)Integration Tests Info:$(NC)"
	@echo ""
	@echo "Package: webapp-integration-tests"
	@echo "Python: $$(python --version 2>&1)"
	@echo "Location: $$(pwd)"
	@echo ""
	@echo "$(BLUE)Test Files:$(NC)"
	@find tests -name "test_*.py" -type f | wc -l | xargs echo "  Test files:"
	@uv run pytest tests/ --collect-only -q 2>/dev/null | tail -1 || echo "  (run 'make install' first)"
	@echo ""
	@echo "$(BLUE)Dependencies:$(NC)"
	@uv pip list 2>/dev/null | grep -E "(pytest|httpx)" || echo "  (run 'make install' first)"
	@echo ""
	@echo "$(BLUE)Services:$(NC)"
	@curl -s http://localhost:8000/health >/dev/null 2>&1 && echo "  ✓ Webapp running" || echo "  ✗ Webapp not running"
	@curl -s http://localhost:9000/-/health/ready/ >/dev/null 2>&1 && echo "  ✓ Authentik running" || echo "  ✗ Authentik not running"
	@echo ""

# Quick shortcuts
t: test
tf: test-fast
ta: test-alice
tb: test-bob
ts: test-sharing
c: cookies
q: quality
h: help
