# How-To: Test Authorization

This guide shows how to test routes protected by fastapi-topaz.

## Using `dependency_overrides`

FastAPI's built-in mechanism for mocking dependencies:

```python
from fastapi.testclient import TestClient
from myapp.main import app
from myapp.auth import topaz_config
from fastapi_topaz import require_policy_allowed

# Create a mock that always allows
def mock_always_allow():
    return None

# Override the dependency
app.dependency_overrides[
    require_policy_allowed(topaz_config, "myapp.GET.documents")
] = mock_always_allow

# Test passes without Topaz running
client = TestClient(app)
response = client.get("/documents")
assert response.status_code == 200

# Clean up
app.dependency_overrides.clear()
```

## Testing Denied Access

```python
from fastapi import HTTPException

def mock_always_deny():
    raise HTTPException(status_code=403, detail="Access denied")

app.dependency_overrides[
    require_policy_allowed(topaz_config, "myapp.GET.documents")
] = mock_always_deny

response = client.get("/documents")
assert response.status_code == 403
```

## Pytest Fixtures

Create reusable fixtures:

```python
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from myapp.main import app
from myapp.auth import topaz_config
from fastapi_topaz import require_policy_allowed, require_rebac_allowed


@pytest.fixture
def client():
    """Test client with no auth overrides."""
    return TestClient(app)


@pytest.fixture
def authed_client():
    """Test client that bypasses all authorization."""
    # Store all dependencies to override
    deps_to_mock = [
        require_policy_allowed(topaz_config, "myapp.GET.documents"),
        require_policy_allowed(topaz_config, "myapp.POST.documents"),
        require_rebac_allowed(topaz_config, "document", "can_read"),
        require_rebac_allowed(topaz_config, "document", "can_write"),
    ]

    for dep in deps_to_mock:
        app.dependency_overrides[dep] = lambda: None

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def denied_client():
    """Test client that denies all authorization."""
    def deny():
        raise HTTPException(status_code=403, detail="Access denied")

    deps_to_mock = [
        require_policy_allowed(topaz_config, "myapp.GET.documents"),
        require_rebac_allowed(topaz_config, "document", "can_read"),
    ]

    for dep in deps_to_mock:
        app.dependency_overrides[dep] = deny

    yield TestClient(app)

    app.dependency_overrides.clear()


# Usage in tests
def test_list_documents_when_authorized(authed_client):
    response = authed_client.get("/documents")
    assert response.status_code == 200


def test_list_documents_when_denied(denied_client):
    response = denied_client.get("/documents")
    assert response.status_code == 403
```

## Mocking the Authorizer Client

For more control, mock at the client level:

```python
from unittest.mock import Mock, patch
from fastapi_topaz import TopazConfig

@pytest.fixture
def mock_authorizer():
    """Mock the Topaz authorizer client."""
    mock_client = Mock()
    mock_client.decisions.return_value = {"allowed": True}

    with patch.object(TopazConfig, "create_client", return_value=mock_client):
        yield mock_client


def test_authorization_with_mock_client(client, mock_authorizer):
    response = client.get("/documents", headers={"X-User-ID": "alice"})
    assert response.status_code == 200

    # Verify the policy was checked
    mock_authorizer.decisions.assert_called_once()


def test_authorization_denied(client, mock_authorizer):
    mock_authorizer.decisions.return_value = {"allowed": False}

    response = client.get("/documents", headers={"X-User-ID": "alice"})
    assert response.status_code == 403
```

## Integration Testing with Topaz

For integration tests with a real Topaz instance:

```python
import pytest
import subprocess
import time

@pytest.fixture(scope="session")
def topaz_instance():
    """Start Topaz container for integration tests."""
    # Start Topaz
    subprocess.run([
        "docker", "run", "-d",
        "--name", "topaz-test",
        "-p", "8282:8282",
        "ghcr.io/aserto-dev/topaz:latest",
        "run"
    ], check=True)

    # Wait for it to be ready
    time.sleep(5)

    yield

    # Cleanup
    subprocess.run(["docker", "rm", "-f", "topaz-test"])


def test_real_authorization(topaz_instance, client):
    """Test against real Topaz instance."""
    response = client.get("/documents", headers={"X-User-ID": "alice"})
    # Result depends on your actual policies
    assert response.status_code in [200, 403]
```

## Testing Resource Context

Verify the correct context is passed to policies:

```python
def test_resource_context_includes_path_params(mock_authorizer):
    client.get("/documents/123", headers={"X-User-ID": "alice"})

    # Check what was passed to the authorizer
    call_args = mock_authorizer.decisions.call_args
    resource_context = call_args.kwargs.get("resource_context", {})

    assert resource_context.get("id") == "123"
    assert resource_context.get("object_type") == "document"
```

## Test Structure

Recommended structure for projects with authorization:

```
tests/
  unit/                  # Fast, mocked tests
    test_config.py
    test_auth.py
    test_models.py
  integration/           # Full stack tests
    conftest.py
    test_scenarios.py
```

| Test Type | Speed | Services | Purpose |
|-----------|-------|----------|---------|
| Unit | < 1s | None | Component testing |
| Integration | ~10s | All (Docker) | Workflow testing |

Run unit tests for fast feedback during development. Run integration tests before commits.

## See Also

- [FastAPI Testing Documentation](https://fastapi.tiangolo.com/tutorial/testing/)
- [API Reference](../reference/api.md)
