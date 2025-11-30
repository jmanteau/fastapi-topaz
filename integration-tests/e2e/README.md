# Integration Tests - Standalone Package

Comprehensive integration tests for the FastAPI-Aserto webapp as a **standalone Python package** with **HTTP-based authentication** (no browser required).

## Features

✅ **HTTP-only Authentication** - Direct OIDC flow via HTTP requests, no browser automation
✅ **Standalone Package** - Separate `pyproject.toml`, can be installed independently
✅ **Automatic Service Checks** - Validates all services before running
✅ **Smart Cookie Caching** - Reuses cookies to skip authentication
✅ **Lightweight** - Only requires `httpx` and `pytest`, no Playwright/Selenium
✅ **49 Integration Tests** - Complete user workflows end-to-end

## Quick Start

### Option A: Using Makefile (Recommended)

```bash
cd integration-tests

# Complete setup (one command)
make setup

# Run tests
make test

# Or run specific scenarios
make test-alice      # Alice's workflow
make test-bob        # Bob's workflow
make test-sharing    # Document sharing
make test-failures   # Security tests
make test-public     # Public documents
```

### Option B: Manual Setup

```bash
# 1. Start Services
cd /Users/to108637/DevProjects/topaz-poc
make up

# 2. Create Test Users
make tf-apply

# 3. Install Package
cd integration-tests
uv pip install -e .

# 4. Run Tests
python run_tests.py
```

## How It Works (No Browser!)

The authentication uses **pure HTTP requests** to follow the OIDC authorization code flow:

```
┌────────────────────────────────────────┐
│ python run_tests.py                     │
└───────────┬────────────────────────────┘
            │
            ▼
     ┌──────────────┐
     │ httpx Client │
     │ Health Check │
     └──────┬───────┘
            │
            ▼
     ┌──────────────────┐
     │ Load cookies from │
     │ environment?      │
     └──────┬───────────┘
            │
        No  │  Yes
    ┌───────┴───────┐
    │               │
    ▼               ▼
┌─────────────┐ ┌────────────┐
│ HTTP POST   │ │ Use Cached │
│ to Authentik│ │ Cookies    │
│ OIDC Flow   │ │            │
└─────┬───────┘ └─────┬──────┘
      │               │
      └───────┬───────┘
              │
              ▼
       ┌──────────────┐
       │ Run Pytest   │
       │ with Auth    │
       └──────────────┘
```

### Authentication Flow (HTTP-only)

1. `GET /login` → Redirects to Authentik authorization endpoint
2. `POST /api/v3/flows/executor/{slug}/` → Submit username
3. `POST /api/v3/flows/executor/{slug}/` → Submit password
4. Follow OAuth callback → Get authorization code
5. Exchange code for token → Get session cookie
6. Use session cookie in tests

**No browser automation needed!**

## Makefile Commands

The Makefile provides convenient shortcuts for all common tasks:

```bash
# Show all available commands
make help

# Setup
make install         # Install package
make setup           # Complete setup (services + users + install)

# Testing
make test            # Run all tests
make test-fast       # Run with cached cookies (faster)
make test-alice      # Alice's workflow
make test-bob        # Bob's workflow
make test-sharing    # Document sharing
make test-failures   # Authorization failures
make test-public     # Public documents
make test-verbose    # Verbose output
make test-debug      # Show print statements

# Authentication
make cookies         # Get session cookies
make cookies-show    # Display cookies
make cookies-clear   # Clear cached cookies

# Quality
make lint            # Run linter
make format          # Format code
make typecheck       # Type checking
make quality         # All quality checks

# Services
make check-services  # Check if services are running
make start-services  # Start all services
make stop-services   # Stop services
make create-users    # Create test users

# Maintenance
make clean           # Remove cache files
make clean-all       # Deep clean (including venv)
```

## Usage

### Run All Tests

```bash
# Using Makefile
make test

# Or using Python directly
python run_tests.py
```

Output:
```
============================================================
Checking Services
============================================================
✓ Webapp         OK
✓ Authentik      OK

⚠ Session cookies not found in environment
Attempting automatic login via HTTP (no browser)...

Logging in alice (alice@example.com)...
  → Logging in alice@example.com
  ✓ Login successful
  ✓ alice cookie obtained
...

✓ Successfully obtained all session cookies

▶ Running all integration tests...
============================================================

============================== test session starts ===============================
tests/test_scenario_alice.py::test_alice_creates_private_document PASSED   [  2%]
...
============================== 49 passed in 8.2s =================================

✓ Tests passed!
```

### Pre-fetch Cookies (Faster)

Get cookies once and reuse them:

```bash
# Get cookies via HTTP
python run_tests.py --get-cookies

# Saves to .env.test with:
# ALICE_SESSION_COOKIE="..."
# BOB_SESSION_COOKIE="..."
# CHARLIE_SESSION_COOKIE="..."

# Export and use
export $(cat .env.test | xargs)
python run_tests.py  # Much faster (skips auth)!
```

Or use the standalone auth script:

```bash
python tests/auth_helper.py
```

### Run with Pytest Directly

```bash
# All tests
uv run pytest tests/ -v

# Specific test
uv run pytest tests/test_scenario_alice.py::test_alice_creates_private_document -v

# With options
uv run pytest tests/ -v -x  # Stop on first failure
uv run pytest tests/ -v -s  # Show prints
uv run pytest tests/ -v -k "sharing"  # Filter by name
```

## Test Scenarios

| Scenario | Tests | Description |
|----------|-------|-------------|
| **alice** | 15 | Alice's complete workflow: documents, folders, sharing |
| **bob** | 8 | Bob's workflow: own resources, reading shared/public docs |
| **sharing** | 9 | Document sharing with read/write permissions |
| **auth-failures** | 9 | Security tests: unauthorized access denials |
| **public** | 8 | Public document accessibility and visibility |
| **Total** | **49** | Complete end-to-end integration tests |

## Project Structure

```
integration-tests/
├── pyproject.toml           # Standalone package config
├── README.md                # This file
├── run_tests.py             # Python test runner
└── tests/
    ├── __init__.py
    ├── conftest.py          # Pytest fixtures with HTTP auth
    ├── auth_helper.py       # HTTP-based OIDC authenticator
    ├── test_scenario_alice.py
    ├── test_scenario_bob.py
    ├── test_scenario_sharing.py
    ├── test_scenario_authorization_failures.py
    └── test_scenario_public_documents.py
```

## Dependencies

Minimal dependencies (no browser automation):

```toml
[project.dependencies]
- pytest>=8.3.0
- pytest-asyncio>=0.24.0
- httpx>=0.28.0
```

**That's it!** No Playwright, Selenium, or browser drivers needed.

## Configuration

### Environment Variables

```bash
# Service URLs (optional, defaults shown)
export WEBAPP_URL="http://localhost:8000"
export AUTHENTIK_URL="http://localhost:9000"

# Session cookies (optional, auto-fetched if missing)
export ALICE_SESSION_COOKIE="<cookie>"
export BOB_SESSION_COOKIE="<cookie>"
export CHARLIE_SESSION_COOKIE="<cookie>"

# User credentials (for auto-login)
export TEST_ALICE_EMAIL="alice@example.com"
export TEST_ALICE_PASSWORD="password"
# ... (defaults are shown above)
```

## Troubleshooting

### Services Not Running

```
✗ Webapp         FAILED
```

**Fix:**
```bash
cd /Users/to108637/DevProjects/topaz-poc
make up
make check-health
```

### HTTP Authentication Fails

```
✗ alice login failed
```

**Check:**
1. Users exist in Authentik: http://localhost:9000
2. Credentials are correct (default: password)
3. OIDC provider is configured
4. Webapp can reach Authentik

**Debug:**
```bash
# Test auth manually
python tests/auth_helper.py

# Check Authentik logs
docker-compose logs authentik-server

# Check webapp logs
docker-compose logs webapp
```

### Cookie Expired

Cookies expire after some time. Re-fetch:

```bash
python run_tests.py --get-cookies
export $(cat .env.test | xargs)
```

## Advantages Over Browser Automation

| Feature | HTTP-based (This) | Browser-based |
|---------|------------------|---------------|
| **Speed** | ✓ Fast (~2s for all users) | ✗ Slow (~30s per user) |
| **Dependencies** | ✓ Just httpx + pytest | ✗ Playwright + chromium |
| **Installation** | ✓ `pip install` | ✗ `playwright install` |
| **CI/CD** | ✓ Works everywhere | ✗ Needs display/headless config |
| **Debugging** | ✓ Simple HTTP logs | ✗ Screenshots, traces |
| **Resource Usage** | ✓ Minimal | ✗ Heavy (browser process) |
| **Reliability** | ✓ Stable | ✗ Flaky (timing issues) |

## CI/CD Integration

### GitHub Actions

```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Start services
        run: docker-compose up -d

      - name: Wait for services
        run: sleep 30

      - name: Setup users
        run: |
          cd terraform/authentik-webapp
          terraform init
          terraform apply -auto-approve

      - name: Run integration tests
        run: |
          cd integration-tests
          uv pip install -e .
          python run_tests.py

      - name: Cleanup
        run: docker-compose down
```

**No browser drivers or display configuration needed!**

## Development

### Adding New Tests

Create new test file:

```python
# tests/test_scenario_new.py
from tests.conftest import AuthenticatedClient

def test_new_feature(alice_client: AuthenticatedClient):
    """Test description."""
    response = alice_client.post("/api/resource", json={"data": "value"})
    assert response.status_code == 201
```

Run it:

```bash
python run_tests.py  # Includes new tests automatically
```

### Running Individual Tests

```bash
# Run one test
uv run pytest tests/test_scenario_alice.py::test_alice_creates_private_document -v

# Run with debugging
uv run pytest tests/test_scenario_alice.py -v -s --pdb
```

## Comparison: webapp/tests/integration vs integration-tests/

| Feature | webapp/tests/integration | integration-tests/ |
|---------|-------------------------|-------------------|
| **Location** | Inside webapp package | Standalone package |
| **Dependencies** | Playwright + browser | Just httpx |
| **pyproject.toml** | Shared with webapp | Dedicated |
| **Installation** | Part of webapp install | Independent install |
| **Authentication** | Browser automation | HTTP requests |
| **Speed** | Slower (~45s) | Faster (~8s) |
| **Use Case** | Local dev with UI | CI/CD, automation |

## Support

```bash
# Show help
python run_tests.py --help

# Show setup guide
python run_tests.py --setup

# Get cookies manually
python tests/auth_helper.py

# Check services
python run_tests.py  # Checks automatically
```

## License

Same as parent project.
