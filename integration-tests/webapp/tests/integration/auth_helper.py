from __future__ import annotations

import os
import time
from typing import Any

from playwright.sync_api import sync_playwright


class AuthenticationHelper:
    """Helper to authenticate users and get session cookies using browser automation."""

    def __init__(
        self,
        webapp_url: str = "http://localhost:8000",
        authentik_url: str = "http://localhost:9000",
        headless: bool = True,
    ):
        self.webapp_url = webapp_url
        self.authentik_url = authentik_url
        self.headless = headless

    def login_user(self, email: str, password: str, timeout: int = 30000) -> str | None:
        """
        Login user via OIDC flow and return session cookie.

        Args:
            email: User email
            password: User password
            timeout: Timeout in milliseconds

        Returns:
            Session cookie value or None if login fails
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()

            try:
                # Navigate to webapp
                page.goto(self.webapp_url, timeout=timeout)

                # Click login button
                page.click('a[href="/login"]', timeout=timeout)

                # Wait for Authentik login page
                page.wait_for_url(f"{self.authentik_url}/**", timeout=timeout)

                # Fill in credentials
                page.fill('input[name="uid_field"]', email)
                page.fill('input[name="password"]', password)

                # Submit form
                page.click('button[type="submit"]', timeout=timeout)

                # Wait for redirect back to webapp
                page.wait_for_url(f"{self.webapp_url}/**", timeout=timeout)

                # Give it a moment to set cookie
                time.sleep(1)

                # Get session cookie
                cookies = context.cookies()
                session_cookie = next((c for c in cookies if c["name"] == "session"), None)

                if session_cookie:
                    return session_cookie["value"]

                return None

            except Exception as e:
                print(f"Login failed for {email}: {e}")
                return None

            finally:
                browser.close()

    def get_all_test_user_cookies(self, test_users: dict[str, dict[str, Any]]) -> dict[str, str]:
        """
        Login all test users and return their session cookies.

        Args:
            test_users: Dict of username -> {email, password}

        Returns:
            Dict of username -> session_cookie
        """
        cookies = {}

        for username, user_info in test_users.items():
            print(f"Logging in {username} ({user_info['email']})...")

            cookie = self.login_user(user_info["email"], user_info["password"])

            if cookie:
                cookies[username] = cookie
                print(f"  ✓ {username} logged in successfully")
            else:
                print(f"  ✗ {username} login failed")
                cookies[username] = None

        return cookies

    def check_services(self) -> dict[str, bool]:
        """Check if required services are running."""
        import httpx

        services = {}

        # Check webapp
        try:
            response = httpx.get(f"{self.webapp_url}/health", timeout=5.0)
            services["webapp"] = response.status_code == 200
        except Exception:
            services["webapp"] = False

        # Check Authentik
        try:
            response = httpx.get(
                f"{self.authentik_url}/-/health/ready/",
                timeout=5.0,
            )
            services["authentik"] = response.status_code == 200
        except Exception:
            services["authentik"] = False

        return services


def save_cookies_to_env(cookies: dict[str, str], env_file: str = ".env.test.local") -> None:
    """Save cookies to environment file."""
    with open(env_file, "w") as f:
        for username, cookie in cookies.items():
            if cookie:
                env_var = f"{username.upper()}_SESSION_COOKIE"
                f.write(f'{env_var}="{cookie}"\n')

    print(f"\nCookies saved to {env_file}")
    print("To use in tests, run:")
    print(f"  export $(cat {env_file} | xargs)")


def load_cookies_from_env() -> dict[str, str]:
    """Load cookies from environment variables."""
    return {
        "alice": os.getenv("ALICE_SESSION_COOKIE", ""),
        "bob": os.getenv("BOB_SESSION_COOKIE", ""),
        "charlie": os.getenv("CHARLIE_SESSION_COOKIE", ""),
    }


if __name__ == "__main__":
    """Standalone script to get session cookies for test users."""
    import sys

    helper = AuthenticationHelper(headless=False)  # Show browser for debugging

    # Check services
    print("Checking services...")
    services = helper.check_services()
    for service, status in services.items():
        status_str = "✓" if status else "✗"
        print(f"  {status_str} {service}")

    if not all(services.values()):
        print("\n❌ Not all services are running!")
        print("Start services with: make up")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Authenticating test users...")
    print("=" * 50)

    test_users = {
        "alice": {"email": "alice@example.com", "password": "password"},
        "bob": {"email": "bob@example.com", "password": "password"},
        "charlie": {"email": "charlie@example.com", "password": "password"},
    }

    cookies = helper.get_all_test_user_cookies(test_users)

    # Print results
    print("\n" + "=" * 50)
    print("Results:")
    print("=" * 50)

    for username, cookie in cookies.items():
        if cookie:
            print(f"✓ {username.upper()}_SESSION_COOKIE={cookie[:20]}...")
        else:
            print(f"✗ {username.upper()} - Failed to get cookie")

    # Save to file
    if any(cookies.values()):
        save_cookies_to_env(cookies)
    else:
        print("\n❌ No cookies obtained. Check that users exist in Authentik.")
        sys.exit(1)
