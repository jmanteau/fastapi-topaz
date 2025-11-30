from __future__ import annotations

import os
from collections.abc import Generator

import httpx
import pytest

from tests.integration.auth_helper import AuthenticationHelper, load_cookies_from_env


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
    with httpx.Client() as client:
        # Check webapp
        try:
            response = client.get(f"{base_url}/health", timeout=5.0)
            assert response.status_code == 200, "Webapp is not healthy"
        except Exception as e:
            pytest.exit(f"Webapp is not running at {base_url}: {e}")

        # Check Authentik
        try:
            response = client.get(f"{authentik_url}/-/health/ready/", timeout=5.0)
            assert response.status_code == 200, "Authentik is not healthy"
        except Exception as e:
            pytest.exit(f"Authentik is not running: {e}")


@pytest.fixture(scope="session", autouse=True)
def check_services(services_health_check):
    """Auto-check services before test session."""
    pass


@pytest.fixture(scope="session")
def session_cookies(
    base_url: str, authentik_url: str, test_users: dict
) -> dict[str, str]:
    """
    Get session cookies for all test users.

    First tries to load from environment variables.
    If not found, automatically logs in users using browser automation.
    """
    # Try to load from environment
    cookies = load_cookies_from_env()

    # If all cookies are present, use them
    if all(cookies.values()):
        print("\n✓ Using session cookies from environment variables")
        return cookies

    # Otherwise, automatically login users
    print("\n⚠ Session cookies not found in environment")
    print("Attempting automatic login with browser automation...")

    helper = AuthenticationHelper(
        webapp_url=base_url,
        authentik_url=authentik_url,
        headless=os.getenv("HEADLESS_BROWSER", "true").lower() == "true",
    )

    cookies = helper.get_all_test_user_cookies(test_users)

    # Check if we got all cookies
    missing = [name for name, cookie in cookies.items() if not cookie]
    if missing:
        pytest.exit(
            f"\n❌ Failed to get cookies for: {', '.join(missing)}\n"
            f"Make sure users exist in Authentik and credentials are correct.\n"
            f"You can also set cookies manually:\n"
            f"  export ALICE_SESSION_COOKIE='...'\n"
            f"  export BOB_SESSION_COOKIE='...'\n"
            f"  export CHARLIE_SESSION_COOKIE='...'"
        )

    print("\n✓ Successfully obtained all session cookies")
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


@pytest.fixture(scope="session")
def playwright_browser():
    """Shared playwright browser for tests that need it."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=os.getenv("HEADLESS_BROWSER", "true").lower() == "true"
        )
        yield browser
        browser.close()
