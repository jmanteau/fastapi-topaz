from __future__ import annotations

import os
from collections.abc import Generator

import httpx
import pytest

from tests.auth_helper import OIDCAuthenticator, load_cookies_from_env


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the webapp."""
    return os.getenv("WEBAPP_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def authentik_url() -> str:
    """Authentik URL."""
    return os.getenv("AUTHENTIK_URL", "http://localhost:9000")


@pytest.fixture(scope="session")
def test_users():
    """Test users credentials."""
    return {
        "alice": {"email": "alice@example.com", "password": "password"},
        "bob": {"email": "bob@example.com", "password": "password"},
        "charlie": {"email": "charlie@example.com", "password": "password"},
    }


@pytest.fixture(scope="session")
def services_health_check(base_url: str, authentik_url: str):
    """Check that all services are running before tests."""
    print("\n" + "=" * 60)
    print("Service Health Check")
    print("=" * 60)

    with httpx.Client(timeout=5.0) as client:
        # Check webapp
        try:
            response = client.get(f"{base_url}/health")
            assert response.status_code == 200, "Webapp is not healthy"
            print(f"✓ Webapp       OK ({base_url})")
        except Exception as e:
            pytest.exit(f"Webapp is not running at {base_url}: {e}")

        # Check Authentik
        try:
            response = client.get(f"{authentik_url}/-/health/ready/")
            assert response.status_code == 200, "Authentik is not healthy"
            print(f"✓ Authentik    OK ({authentik_url})")
        except Exception as e:
            pytest.exit(f"Authentik is not running: {e}")

    print()


@pytest.fixture(scope="session", autouse=True)
def check_services(services_health_check):
    """Auto-check services before test session."""
    pass


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data(base_url: str, session_cookies: dict[str, str]):
    """Clean up all test data before running tests to ensure idempotency."""
    print("\n" + "=" * 60)
    print("Cleaning up test data for idempotency")
    print("=" * 60)

    for username, cookie in session_cookies.items():
        if not cookie:
            continue

        client = httpx.Client(
            cookies={"session": cookie},
            follow_redirects=True,
            timeout=30.0,
        )

        try:
            # Delete all documents for this user
            response = client.get(f"{base_url}/documents/")
            if response.status_code == 200:
                documents = response.json()
                for doc in documents:
                    client.delete(f"{base_url}/documents/{doc['id']}")
                print(f"✓ {username}: deleted {len(documents)} documents")

            # Delete all folders for this user
            response = client.get(f"{base_url}/folders/")
            if response.status_code == 200:
                folders = response.json()
                # Delete in reverse order (children first) to handle nesting
                for folder in reversed(folders):
                    client.delete(f"{base_url}/folders/{folder['id']}")
                print(f"✓ {username}: deleted {len(folders)} folders")
        except Exception as e:
            print(f"⚠ {username}: cleanup error - {e}")
        finally:
            client.close()

    print()
    yield  # Run tests
    # Optional: cleanup after tests too


@pytest.fixture(scope="session")
def session_cookies(
    base_url: str, authentik_url: str, test_users: dict
) -> dict[str, str]:
    """
    Get session cookies for all test users.

    First tries to load from environment variables.
    If not found, automatically logs in users using HTTP requests (no browser).
    """
    # Try to load from environment
    cookies = load_cookies_from_env()

    # If all cookies are present, use them
    if all(cookies.values()):
        print("✓ Using session cookies from environment variables\n")
        return cookies

    # Otherwise, automatically login users via HTTP
    print("⚠ Session cookies not found in environment")
    print("Attempting automatic login via HTTP (no browser)...\n")

    authenticator = OIDCAuthenticator(webapp_url=base_url, authentik_url=authentik_url)

    cookies = authenticator.get_all_user_cookies(test_users)

    # Check if we got all cookies
    missing = [name for name, cookie in cookies.items() if not cookie]
    if missing:
        pytest.exit(
            f"\n❌ Failed to get cookies for: {', '.join(missing)}\n"
            f"Make sure:\n"
            f"  1. Users exist in Authentik (run: make tf-apply)\n"
            f"  2. Credentials are correct (default: password)\n"
            f"  3. Services are properly configured\n\n"
            f"You can also set cookies manually:\n"
            f"  export ALICE_SESSION_COOKIE='...'\n"
            f"  export BOB_SESSION_COOKIE='...'\n"
            f"  export CHARLIE_SESSION_COOKIE='...'\n\n"
            f"Or run: python tests/auth_helper.py"
        )

    print("\n✓ Successfully obtained all session cookies\n")
    return cookies


class AuthenticatedClient:
    """HTTP client with authentication session."""

    def __init__(self, base_url: str, session_cookie: str):
        self.base_url = base_url
        self.client = httpx.Client(
            cookies={"session": session_cookie},
            follow_redirects=True,
            timeout=30.0,
        )

    def get(self, path: str, **kwargs):
        """GET request."""
        return self.client.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path: str, **kwargs):
        """POST request."""
        return self.client.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path: str, **kwargs):
        """PUT request."""
        return self.client.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path: str, **kwargs):
        """DELETE request."""
        return self.client.delete(f"{self.base_url}{path}", **kwargs)

    def close(self):
        """Close client."""
        self.client.close()


@pytest.fixture
def alice_client(
    base_url: str, session_cookies: dict[str, str]
) -> Generator[AuthenticatedClient, None, None]:
    """Authenticated client for Alice."""
    if not session_cookies.get("alice"):
        pytest.skip("Alice session cookie not available")

    client = AuthenticatedClient(base_url, session_cookies["alice"])
    yield client
    client.close()


@pytest.fixture
def bob_client(
    base_url: str, session_cookies: dict[str, str]
) -> Generator[AuthenticatedClient, None, None]:
    """Authenticated client for Bob."""
    if not session_cookies.get("bob"):
        pytest.skip("Bob session cookie not available")

    client = AuthenticatedClient(base_url, session_cookies["bob"])
    yield client
    client.close()


@pytest.fixture
def charlie_client(
    base_url: str, session_cookies: dict[str, str]
) -> Generator[AuthenticatedClient, None, None]:
    """Authenticated client for Charlie."""
    if not session_cookies.get("charlie"):
        pytest.skip("Charlie session cookie not available")

    client = AuthenticatedClient(base_url, session_cookies["charlie"])
    yield client
    client.close()
