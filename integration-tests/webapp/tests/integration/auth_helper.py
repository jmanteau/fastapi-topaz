from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx


class OIDCAuthenticator:
    """
    HTTP-based OIDC authentication without browser.

    Uses direct HTTP requests to follow the OIDC authorization code flow
    and obtain session cookies.
    """

    def __init__(
        self,
        webapp_url: str = "http://localhost:8000",
        authentik_url: str = "http://localhost:9000",
        debug: bool = False,
    ):
        self.webapp_url = webapp_url
        self.authentik_url = authentik_url
        self.debug = debug

    def _debug(self, message: str) -> None:
        """Print debug message if debug mode is enabled."""
        if self.debug:
            print(f"  [DEBUG] {message}")

    def _normalize_url(self, url: str) -> str:
        """Replace internal Docker hostnames with localhost equivalents."""
        # The webapp inside Docker redirects to authentik-server:9000 (internal hostname)
        # but our test client runs outside Docker and needs localhost:9000
        return re.sub(
            r"http://authentik-server:(\d+)",
            self.authentik_url,
            url,
        )

    def login_user(self, email: str, password: str, timeout: float = 30.0) -> str | None:
        """
        Login using Authentik's flow executor API.

        Follows the proper flow: GET challenge -> POST response -> GET next challenge
        """
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            try:
                print(f"  -> Logging in {email}")
                self._debug("Starting authentication flow")

                # Step 1: Start at webapp login to get redirected to Authentik
                self._debug(f"GET {self.webapp_url}/login")
                resp1 = client.get(f"{self.webapp_url}/login", follow_redirects=True)
                self._debug(f"Response: {resp1.status_code}")
                self._debug(f"Final URL: {resp1.url}")

                # Normalize URL (replace internal Docker hostnames)
                current_url = self._normalize_url(str(resp1.url))
                self._debug(f"Normalized URL: {current_url}")

                if "/if/flow/" not in current_url and "/flows/executor/" not in current_url:
                    self._debug("No Authentik flow found")
                    print("  x No Authentik flow found")
                    return None

                # Determine flow slug and query params
                if "/if/flow/" in current_url:
                    flow_slug = current_url.split("/if/flow/")[1].split("/")[0].split("?")[0]
                    query_params = ""
                    if "?" in current_url:
                        query_part = current_url.split("?", 1)[1]
                        query_params = f"?{query_part}"
                else:
                    flow_slug = current_url.split("/flows/executor/")[1].split("/")[0].split("?")[0]
                    query_params = ""

                self._debug(f"Flow slug: {flow_slug}")

                # Step 2: GET initial challenge from API
                api_url = f"{self.authentik_url}/api/v3/flows/executor/{flow_slug}/"
                if query_params:
                    api_url = f"{api_url}{query_params}"

                self._debug(f"GET initial challenge: {api_url}")
                challenge1 = client.get(api_url)

                if challenge1.status_code != 200:
                    print(f"  x Failed to get challenge: {challenge1.status_code}")
                    return None

                self._debug(f"Challenge 1 component: {challenge1.json().get('component')}")

                # Step 3: POST username (identification stage)
                self._debug("POST username")
                client.post(
                    api_url,
                    json={"component": "ak-stage-identification", "uid_field": email},
                    headers={"Content-Type": "application/json"},
                )

                # Step 4: GET next challenge (password stage)
                challenge2 = client.get(api_url)
                if challenge2.status_code != 200:
                    print(f"  x Failed to get password challenge: {challenge2.status_code}")
                    return None

                self._debug(f"Challenge 2 component: {challenge2.json().get('component')}")

                # Step 5: POST password
                client.post(
                    api_url,
                    json={"component": "ak-stage-password", "password": password},
                    headers={"Content-Type": "application/json"},
                )

                # Step 6: GET final response (should be redirect)
                final_resp = client.get(api_url)

                if final_resp.status_code == 302:
                    location = final_resp.headers.get("Location", "/")
                    final_resp = client.get(
                        f"{self.authentik_url}{location}", follow_redirects=True
                    )

                if final_resp.status_code == 200:
                    final_data = final_resp.json()
                    component = final_data.get("component")
                    self._debug(f"Final component: {component}")

                    if component == "xak-flow-redirect":
                        parsed_url = urlparse(current_url)
                        query_params_dict = parse_qs(parsed_url.query)
                        next_url = query_params_dict.get("next", ["/"])[0]
                        next_url = unquote(next_url)

                        if not next_url.startswith("http"):
                            oauth_url = f"{self.authentik_url}{next_url}"
                        else:
                            oauth_url = self._normalize_url(next_url)

                        self._debug(f"Following OAuth authorization: {oauth_url}")

                        oauth_resp = client.get(oauth_url, follow_redirects=True)
                        self._debug(f"OAuth response: {oauth_resp.status_code}, URL: {oauth_resp.url}")
                        self._debug(f"Cookies: {list(client.cookies.jar)}")

                        # After callback, the webapp overwrites the session cookie
                        # with the real authenticated session
                        if self.webapp_url in str(oauth_resp.url):
                            session_cookie = client.cookies.get("session")
                            if session_cookie:
                                print("  v Login successful")
                                return session_cookie

                print("  x Login failed")
                return None

            except Exception as e:
                print(f"  x Login error: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                return None

    def get_all_user_cookies(
        self, test_users: dict[str, dict[str, Any]]
    ) -> dict[str, str]:
        """Login all test users and return their cookies."""
        cookies = {}
        for username, user_info in test_users.items():
            print(f"Logging in {username} ({user_info['email']})...")
            cookie = self.login_user(user_info["email"], user_info["password"])
            if cookie:
                cookies[username] = cookie
                print(f"  v {username} cookie obtained")
            else:
                print(f"  x {username} login failed")
                cookies[username] = None
        return cookies

    def check_services(self) -> dict[str, bool]:
        """Check if required services are running."""
        services = {}
        try:
            response = httpx.get(f"{self.webapp_url}/health", timeout=5.0)
            services["webapp"] = response.status_code == 200
        except Exception:
            services["webapp"] = False
        try:
            response = httpx.get(f"{self.authentik_url}/-/health/ready/", timeout=5.0)
            services["authentik"] = response.status_code == 200
        except Exception:
            services["authentik"] = False
        return services


def load_cookies_from_env() -> dict[str, str]:
    """Load cookies from environment variables."""
    return {
        "alice": os.getenv("ALICE_SESSION_COOKIE", ""),
        "bob": os.getenv("BOB_SESSION_COOKIE", ""),
        "charlie": os.getenv("CHARLIE_SESSION_COOKIE", ""),
    }


def save_cookies_to_env(cookies: dict[str, str], env_file: str = ".env.test.local") -> None:
    """Save cookies to environment file."""
    with open(env_file, "w") as f:
        for username, cookie in cookies.items():
            if cookie:
                env_var = f"{username.upper()}_SESSION_COOKIE"
                f.write(f'{env_var}="{cookie}"\n')
    print(f"\nCookies saved to {env_file}")
    print(f"To use: export $(cat {env_file} | xargs)")


if __name__ == "__main__":
    """Standalone script to get session cookies."""
    import sys

    debug = "--debug" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python tests/integration/auth_helper.py [--debug]")
        print("\nOptions:")
        print("  --debug    Enable debug output (shows detailed HTTP flow)")
        sys.exit(0)

    auth = OIDCAuthenticator(debug=debug)

    print("Checking services...")
    services = auth.check_services()
    for service, status in services.items():
        print(f"  {'v' if status else 'x'} {service}")

    if not all(services.values()):
        print("\nNot all services are running! Start with: make up")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Authenticating test users (HTTP-only, no browser)")
    print("=" * 50 + "\n")

    test_users = {
        "alice": {"email": "alice@example.com", "password": "password"},
        "bob": {"email": "bob@example.com", "password": "password"},
        "charlie": {"email": "charlie@example.com", "password": "password"},
    }

    cookies = auth.get_all_user_cookies(test_users)

    success_count = sum(1 for c in cookies.values() if c)
    print("\n" + "=" * 50)
    for username, cookie in cookies.items():
        if cookie:
            print(f"v {username.upper():10} {cookie[:40]}...")
        else:
            print(f"x {username.upper():10} Failed")

    if success_count > 0:
        print(f"\nv {success_count}/3 users authenticated!")
        save_cookies_to_env(cookies)
    else:
        print("\nNo cookies obtained. Run: make tf-apply")
        sys.exit(1)
