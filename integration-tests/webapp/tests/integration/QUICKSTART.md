# Integration Tests - Quick Start (Python)

Get started testing the full application stack in 5 minutes - everything in Python!

## Prerequisites

Install test dependencies:

```bash
cd /Users/to108637/DevProjects/topaz-poc/webapp
uv pip install -e ".[integration]"
playwright install chromium  # Install browser for automation
```

## 1. Start Services

```bash
cd /Users/to108637/DevProjects/topaz-poc
make up
```

Wait ~30 seconds, then verify services are running.

## 2. Create Test Users

**Option A: Terraform (Recommended)**

```bash
make tf-init
make tf-apply
```

This automatically creates:
- alice@example.com (password: password)
- bob@example.com (password: password)
- charlie@example.com (password: password)

**Option B: Manual in Authentik**

1. Open http://authentik-server:9000
2. Login with admin credentials (`make auth-password`)
3. Create the 3 users above

## 3. Run Tests (Automatic Authentication)

The test framework automatically handles authentication!

```bash
cd webapp
python tests/integration/run_tests.py
```

The framework will:
1. ✓ Check services are running
2. ✓ Automatically login users with browser automation
3. ✓ Get session cookies
4. ✓ Run all tests

## Optional: Pre-fetch Cookies (Faster)

To avoid browser automation on every test run:

```bash
# Get cookies once (shows browser)
python tests/integration/run_tests.py --get-cookies --headless=no

# Export them
export ALICE_SESSION_COOKIE="..."
export BOB_SESSION_COOKIE="..."
export CHARLIE_SESSION_COOKIE="..."

# Now tests will use cached cookies (much faster!)
python tests/integration/run_tests.py
```

Or save to file:

```bash
# Get and save cookies
python tests/integration/auth_helper.py

# This creates .env.test.local with:
# ALICE_SESSION_COOKIE="..."
# BOB_SESSION_COOKIE="..."
# CHARLIE_SESSION_COOKIE="..."

# Load and use
export $(cat .env.test.local | xargs)
python tests/integration/run_tests.py
```

## Run Specific Scenarios

```bash
# Alice's workflow
python tests/integration/run_tests.py alice

# Bob's workflow
python tests/integration/run_tests.py bob

# Document sharing
python tests/integration/run_tests.py sharing

# Security tests (authorization failures)
python tests/integration/run_tests.py auth-failures

# Public documents
python tests/integration/run_tests.py public
```

## Run with Pytest Directly

```bash
# All tests
uv run pytest tests/integration/ -v

# Specific scenario
uv run pytest tests/integration/test_scenario_alice.py -v

# Specific test
uv run pytest tests/integration/test_scenario_alice.py::test_alice_creates_private_document -v

# Stop on first failure
uv run pytest tests/integration/ -v -x

# Show print statements
uv run pytest tests/integration/ -v -s

# Filter by name
uv run pytest tests/integration/ -v -k "sharing"
```

## Expected Output

```
==================================================
Checking Services
==================================================
✓ Webapp         OK
✓ Authentik      OK

⚠ Session cookies not found in environment
Attempting automatic login with browser automation...
Logging in alice (alice@example.com)...
  ✓ alice logged in successfully
Logging in bob (bob@example.com)...
  ✓ bob logged in successfully
Logging in charlie (charlie@example.com)...
  ✓ charlie logged in successfully

✓ Successfully obtained all session cookies

▶ Running all integration tests...
==================================================

================================ test session starts =================================
tests/integration/test_scenario_alice.py::test_alice_creates_private_document PASSED
tests/integration/test_scenario_alice.py::test_alice_creates_public_document PASSED
...
tests/integration/test_scenario_public_documents.py::test_complete_public_document_workflow PASSED

================================== 49 passed in 12.4s =================================

✓ Tests passed!
```

## Troubleshooting

### Services Not Running

```
✗ Webapp         FAILED
```

**Fix:**
```bash
make up
make check-health
```

### Browser Automation Fails

```
Failed to get cookies for: alice, bob, charlie
```

**Check:**
1. Users exist in Authentik: http://localhost:9000
2. Passwords are correct (default: "password")
3. Webapp is accessible: http://localhost:8000

**Debug with visible browser:**
```bash
python tests/integration/run_tests.py --get-cookies --headless=no
```

### Playwright Not Installed

```
❌ Playwright not installed!
```

**Fix:**
```bash
uv pip install playwright
playwright install chromium
```

### Tests Timeout

Increase timeout in conftest.py `AuthenticatedClient` or use:
```bash
export PYTEST_TIMEOUT=60
```

## Features

✅ **100% Python** - No bash scripts required
✅ **Automatic Authentication** - Browser automation handles SSO
✅ **Service Health Checks** - Validates services before running
✅ **Smart Cookie Caching** - Reuses cookies when available
✅ **Clean Test Runner** - Simple Python script with help
✅ **Full Integration** - Tests against real services

## What's Tested

- **Alice Workflow** (15 tests): Document/folder CRUD, sharing
- **Bob Workflow** (8 tests): Own resources, reading shared/public
- **Sharing** (9 tests): Read/write permissions, collaboration
- **Authorization** (9 tests): Security, unauthorized access denial
- **Public Documents** (8 tests): Public visibility, access control

**Total: 49 integration tests**

## Next Steps

- **CI/CD Integration**: See README.md for GitHub Actions example
- **Add More Tests**: Use existing tests as templates
- **Custom Scenarios**: Create new test files in tests/integration/
- **Debug Failures**: Use `-v -s` for verbose output with prints

## Need Help?

```bash
# Show help
python tests/integration/run_tests.py --help

# Show setup guide
python tests/integration/run_tests.py --setup

# Check services
python tests/integration/run_tests.py  # Checks automatically

# Get detailed docs
cat tests/integration/README.md
```
