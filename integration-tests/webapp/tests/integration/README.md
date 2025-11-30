# Integration Tests - Full Stack Testing (Python)

Comprehensive integration tests that test complete user workflows against the running application stack (Authentik SSO, Topaz Authorization, PostgreSQL, FastAPI).

**100% Python implementation** with automatic browser-based authentication.

## Prerequisites

### 0. Install Dependencies

```bash
cd /Users/to108637/DevProjects/topaz-poc/webapp
uv pip install -e ".[integration]"
playwright install chromium
```

### 1. Running Services

All Docker services must be running:

```bash
cd /Users/to108637/DevProjects/topaz-poc
make up  # or docker-compose up -d
```

Verify services are healthy:
```bash
make check-health
```

Services required:
- **Webapp** (localhost:8000) - FastAPI application
- **Authentik** (authentik-server:9000) - OIDC authentication
- **Topaz** (localhost:8282) - Authorization service
- **PostgreSQL** (localhost:5432) - Database
- **Mock Location API** (localhost:8001) - Location service

### 2. Test Users Setup

Create test users in Authentik:

1. Access Authentik admin panel: http://authentik-server:9000
2. Login with bootstrap credentials (check `.env` or run `make auth-password`)
3. Create three test users:

   **Alice** (alice@example.com, password: password)
   - Role: User/Admin (depending on tests)
   - Use for: Document creation, sharing tests

   **Bob** (bob@example.com, password: password)
   - Role: User
   - Use for: Document consumption, authorization denial tests

   **Charlie** (charlie@example.com, password: password)
   - Role: User
   - Use for: Multi-user sharing tests

Alternatively, use Terraform to provision users:
```bash
make tf-init
make tf-apply
```

### 3. Authentication (Automatic)

The test framework **automatically handles authentication** using browser automation!

**Option A: Automatic (Default)**

Just run the tests - authentication happens automatically:

```bash
python tests/integration/run_tests.py
```

The framework will:
1. Check if session cookies exist in environment
2. If not, launch browser and login users automatically
3. Extract session cookies
4. Run tests with authenticated sessions

**Option B: Pre-fetch Cookies (Faster)**

Get cookies once and reuse them:

```bash
# Automatic login (headless)
python tests/integration/run_tests.py --get-cookies

# OR with visible browser (for debugging)
python tests/integration/run_tests.py --get-cookies --headless=no

# OR use standalone script
python tests/integration/auth_helper.py

# This creates .env.test.local with cookies
export $(cat .env.test.local | xargs)

# Now tests run faster (skip browser automation)
python tests/integration/run_tests.py
```

**Option C: Manual (If automation fails)**

```bash
# Login manually, extract cookies, then:
export ALICE_SESSION_COOKIE="<cookie-value>"
export BOB_SESSION_COOKIE="<cookie-value>"
export CHARLIE_SESSION_COOKIE="<cookie-value>"
```

## Running Tests

### Quick Start - Python Test Runner

```bash
cd /Users/to108637/DevProjects/topaz-poc/webapp

# Run all tests (automatic authentication)
python tests/integration/run_tests.py

# Run specific scenarios
python tests/integration/run_tests.py alice        # Alice's workflow
python tests/integration/run_tests.py bob          # Bob's workflow
python tests/integration/run_tests.py sharing      # Document sharing
python tests/integration/run_tests.py auth-failures # Security tests
python tests/integration/run_tests.py public       # Public documents

# Show help
python tests/integration/run_tests.py --help

# Get session cookies
python tests/integration/run_tests.py --get-cookies
```

### Using Pytest Directly

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

# Slow tests only
uv run pytest tests/integration/ -v -m "slow"

# Skip slow tests
uv run pytest tests/integration/ -v -m "not slow"
```

## Test Scenarios Overview

### 1. Alice's Workflow (`test_scenario_alice.py`)

Tests Alice's complete journey:
- ✅ Create private documents
- ✅ Create public announcements
- ✅ List owned documents
- ✅ Update document content
- ✅ Delete documents
- ✅ Create folders
- ✅ Create nested folder structures
- ✅ Create documents in folders
- ✅ Share documents with read permission
- ✅ Share documents with write permission
- ✅ View document shares
- ✅ Complete project workflow

**Example:**
```bash
uv run pytest tests/integration/test_scenario_alice.py::test_alice_complete_project_workflow -v -s
```

### 2. Bob's Workflow (`test_scenario_bob.py`)

Tests Bob's typical user interactions:
- ✅ Create own documents
- ✅ Read own documents
- ✅ Update own documents
- ✅ Delete own documents
- ✅ Create folders
- ✅ List accessible documents
- ✅ Complete daily workflow

### 3. Sharing Scenarios (`test_scenario_sharing.py`)

Tests document sharing functionality:
- ✅ Alice shares with Bob (read permission)
- ✅ Bob reads shared document
- ✅ Bob cannot modify read-only share
- ✅ Alice shares with write permission
- ✅ Bob can now modify document
- ✅ View all shares for a document
- ✅ Share with multiple users
- ✅ Prevent duplicate shares (409 conflict)
- ✅ Share non-existent document (404)
- ✅ Share with non-existent user (404)
- ✅ Complete sharing lifecycle

### 4. Authorization Failures (`test_scenario_authorization_failures.py`)

Tests security - what users CANNOT do:
- ❌ Bob cannot read Alice's private documents
- ❌ Bob cannot update Alice's documents
- ❌ Bob cannot delete Alice's documents
- ❌ Bob cannot share Alice's documents
- ❌ Bob cannot access Alice's folders
- ❌ Bob cannot delete Alice's folders
- ❌ Bob cannot modify Alice's folders
- ❌ Bob cannot delete shared document with read permission
- ✅ Bob only sees accessible documents in lists
- ✅ Comprehensive denial workflow

### 5. Public Documents (`test_scenario_public_documents.py`)

Tests public document accessibility:
- ✅ Alice creates public documents
- ✅ Bob reads public documents
- ✅ Public documents appear in everyone's lists
- ❌ Bob cannot modify Alice's public documents
- ❌ Bob cannot delete Alice's public documents
- ✅ Alice makes private document public
- ✅ Alice makes public document private
- ✅ Multiple users create public documents
- ✅ Complete public document lifecycle

## Expected Results

### Success Scenarios

Tests that should **PASS** (green ✓):
- Users can create their own resources
- Users can read/modify/delete their own resources
- Users can read public documents
- Users can access shared documents (with correct permissions)
- Document sharing works correctly
- Folder hierarchies work

### Failure Scenarios

Tests that verify **DENIAL** (still pass, but test that operations fail):
- Users cannot access others' private resources
- Users cannot modify/delete resources they don't own
- Users cannot share resources they don't own
- Authorization is properly enforced

## Troubleshooting

### Services Not Running

```
Error: Webapp is not running at http://localhost:8000
```

**Solution:**
```bash
make up
make check-health
```

### Session Cookie Expired

```
Error: ALICE_SESSION_COOKIE not set
```

**Solution:**
1. Login again in browser
2. Extract new session cookie
3. Re-export environment variable

### Tests Skip with "Cookie Not Set"

Pytest will skip tests if cookies are not set. Set all three:
```bash
export ALICE_SESSION_COOKIE="..."
export BOB_SESSION_COOKIE="..."
export CHARLIE_SESSION_COOKIE="..."
```

### Authorization Failures (403)

If legitimate operations return 403:
1. Check Topaz is running: `curl http://localhost:8282/health`
2. Check Topaz policies are loaded
3. Review policy files in `policies/` directory
4. Check Topaz logs: `make logs-topaz`

### Database Conflicts

If tests fail with constraint violations:
1. Reset database: `make db-downgrade && make db-upgrade`
2. Or restart services: `make down && make up`

## Continuous Integration

### Running in CI/CD

```yaml
# .github/workflows/integration-tests.yml
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

      - name: Run integration tests
        env:
          ALICE_SESSION_COOKIE: ${{ secrets.ALICE_SESSION_COOKIE }}
          BOB_SESSION_COOKIE: ${{ secrets.BOB_SESSION_COOKIE }}
          CHARLIE_SESSION_COOKIE: ${{ secrets.CHARLIE_SESSION_COOKIE }}
        run: |
          cd webapp
          uv run pytest tests/integration/ -v

      - name: Cleanup
        run: docker-compose down
```

## Test Coverage

Current integration test coverage:

| Feature | Tested | Test File |
|---------|--------|-----------|
| Document CRUD | ✅ | `test_scenario_alice.py`, `test_scenario_bob.py` |
| Folder CRUD | ✅ | `test_scenario_alice.py`, `test_scenario_bob.py` |
| Document Sharing | ✅ | `test_scenario_sharing.py` |
| Authorization Enforcement | ✅ | `test_scenario_authorization_failures.py` |
| Public Documents | ✅ | `test_scenario_public_documents.py` |
| Nested Folders | ✅ | `test_scenario_alice.py` |
| Multi-user Workflows | ✅ | All test files |
| OIDC Authentication | 🔶 | Manual (requires browser) |
| Location-based Authorization | ⏳ | TODO |
| Admin Operations | ⏳ | TODO |

## Adding New Tests

### Template for New Scenario Test

```python
from __future__ import annotations

import pytest
from tests.integration.conftest import AuthenticatedClient


def test_new_scenario(alice_client: AuthenticatedClient):
    """
    Scenario: Description
    Given: Preconditions
    When: Actions
    Then: Expected results
    """
    # Create resource
    response = alice_client.post("/api/resource", json={"data": "value"})
    assert response.status_code == 201

    # Verify result
    data = response.json()
    assert data["field"] == "expected"
```

### Running New Tests

```bash
uv run pytest tests/integration/test_new_scenario.py -v
```

## Maintenance

### Updating Test Users

If user IDs change in Authentik:
1. Get new user IDs from Authentik admin panel
2. Update `conftest.py` test_users fixture
3. Update test files with correct user IDs

### Cleaning Test Data

Tests create data in the database. To clean:

```bash
# Reset database
make db-downgrade
make db-upgrade

# Or restart everything
make clean
make setup
```

## Support

For issues or questions:
1. Check service logs: `make logs`
2. Check Topaz authorization logs: `make logs-topaz`
3. Verify all services healthy: `make check-health`
4. Review test output with `-v -s` flags for detailed output
