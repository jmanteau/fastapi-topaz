from __future__ import annotations

import os
import re
from typing import Any

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

    def login_user(self, email: str, password: str, timeout: float = 30.0) -> str | None:
        """
        Login user via OIDC flow using HTTP requests only.

        Args:
            email: User email
            password: User password
            timeout: Request timeout in seconds

        Returns:
            Session cookie value or None if login fails
        """
        # Create session to maintain cookies across requests
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            try:
                # Step 1: Start OIDC flow by accessing /login
                print(f"  → Starting OIDC flow for {email}")
                login_response = client.get(f"{self.webapp_url}/login")

                # Should redirect to Authentik authorization endpoint
                # The redirect should give us the authorization URL

                # Step 2: Get the authorization URL from response
                auth_url = str(login_response.url)

                if self.authentik_url not in auth_url:
                    print(f"  ✗ Expected redirect to Authentik, got: {auth_url}")
                    return None

                # Step 3: Submit credentials to Authentik
                # Parse the flow executor URL to get flow slug
                print("  → Submitting credentials to Authentik")

                # Authentik uses a flow executor, we need to POST to the flow API
                # The flow is typically at /flows/executor/{slug}/
                flow_match = re.search(r"/flows/executor/([^/]+)/", auth_url)
                if not flow_match:
                    print(f"  ✗ Could not find flow slug in URL: {auth_url}")
                    return None

                flow_slug = flow_match.group(1)
                flow_url = f"{self.authentik_url}/flows/executor/{flow_slug}/"

                # Get the flow page to extract CSRF token
                flow_page = client.get(flow_url)

                # Authentik uses a flow executor API
                # We need to POST to the API endpoint
                api_url = f"{self.authentik_url}/api/v3/flows/executor/{flow_slug}/"

                # First, identify stage (username)
                identify_response = client.post(
                    api_url,
                    json={"uid_field": email},
                    headers={"Content-Type": "application/json"},
                )

                if identify_response.status_code != 200:
                    print(
                        f"  ✗ Identify stage failed: {identify_response.status_code}"
                    )
                    return None

                # Second, password stage
                password_response = client.post(
                    api_url,
                    json={"password": password},
                    headers={"Content-Type": "application/json"},
                )

                if password_response.status_code != 200:
                    print(f"  ✗ Password stage failed: {password_response.status_code}")
                    return None

                # Step 4: Handle the OAuth callback
                # The response should contain a redirect to the callback URL
                result = password_response.json()

                if result.get("type") == "redirect":
                    callback_url = result.get("to")
                    print("  → Following callback redirect")

                    # Follow the redirect to complete OAuth flow
                    callback_response = client.get(callback_url)

                    # This should set the session cookie and redirect to webapp
                    # Check if we're back at the webapp
                    if self.webapp_url in str(callback_response.url):
                        # Extract session cookie
                        cookies = client.cookies
                        session_cookie = cookies.get("session")

                        if session_cookie:
                            print("  ✓ Login successful")
                            return session_cookie

                print("  ✗ No session cookie obtained")
                return None

            except httpx.TimeoutException:
                print(f"  ✗ Request timeout for {email}")
                return None
            except Exception as e:
                print(f"  ✗ Login failed: {e}")
                return None

    def login_user_simple(
        self, email: str, password: str, timeout: float = 30.0
    ) -> str | None:
        """
        Login using Authentik's flow executor API.

        Follows the proper flow: GET challenge → POST response → GET next challenge
        """
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            try:
                print(f"  → Logging in {email}")
                self._debug("Starting authentication flow")

                # Step 1: Start at webapp login to get redirected to Authentik
                self._debug(f"GET {self.webapp_url}/login")
                resp1 = client.get(f"{self.webapp_url}/login", follow_redirects=True)
                self._debug(f"Response: {resp1.status_code}")
                self._debug(f"Final URL: {resp1.url}")
                self._debug(f"Cookies: {list(client.cookies.keys())}")

                # Extract flow information from URL
                current_url = str(resp1.url)

                if "/if/flow/" not in current_url and "/flows/executor/" not in current_url:
                    self._debug("No Authentik flow found")
                    print("  ✗ No Authentik flow found")
                    return None

                # Determine flow slug and query params
                if "/if/flow/" in current_url:
                    flow_slug = current_url.split("/if/flow/")[1].split("/")[0].split("?")[0]
                    # Extract query params if present
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
                self._debug(f"Challenge response: {challenge1.status_code}")

                if challenge1.status_code != 200:
                    print(f"  ✗ Failed to get challenge: {challenge1.status_code}")
                    return None

                challenge1_data = challenge1.json()
                self._debug(f"Challenge 1 component: {challenge1_data.get('component')}")

                # Step 3: POST username (identification stage)
                self._debug("POST username")
                username_resp = client.post(
                    api_url,
                    json={
                        "component": "ak-stage-identification",
                        "uid_field": email
                    },
                    headers={"Content-Type": "application/json"},
                )
                self._debug(f"Username POST: {username_resp.status_code}")

                # Step 4: GET next challenge (password stage)
                self._debug("GET password challenge")
                challenge2 = client.get(api_url)
                self._debug(f"Challenge 2 response: {challenge2.status_code}")

                if challenge2.status_code != 200:
                    print(f"  ✗ Failed to get password challenge: {challenge2.status_code}")
                    return None

                challenge2_data = challenge2.json()
                self._debug(f"Challenge 2 component: {challenge2_data.get('component')}")

                # Step 5: POST password
                self._debug("POST password")
                password_resp = client.post(
                    api_url,
                    json={
                        "component": "ak-stage-password",
                        "password": password
                    },
                    headers={"Content-Type": "application/json"},
                )
                self._debug(f"Password POST: {password_resp.status_code}")

                # Step 6: GET final response (should be redirect)
                self._debug("GET final response")
                final_resp = client.get(api_url)
                self._debug(f"Final response: {final_resp.status_code}")

                if final_resp.status_code == 302:
                    # Follow redirect
                    location = final_resp.headers.get("Location", "/")
                    self._debug(f"Following 302 to: {location}")
                    final_resp = client.get(f"{self.authentik_url}{location}", follow_redirects=True)
                    self._debug(f"After redirect: {final_resp.status_code}, URL: {final_resp.url}")

                if final_resp.status_code == 200:
                    final_data = final_resp.json()
                    component = final_data.get("component")
                    self._debug(f"Final component: {component}")

                    if component == "xak-flow-redirect":
                        # Extract the OAuth callback URL from query params
                        # The "next" parameter contains the OAuth authorization endpoint
                        from urllib.parse import parse_qs, unquote, urlparse

                        parsed_url = urlparse(current_url)
                        query_params_dict = parse_qs(parsed_url.query)
                        next_url = query_params_dict.get("next", ["/"])[0]
                        next_url = unquote(next_url)  # URL decode

                        self._debug(f"Next URL from query: {next_url}")

                        # Build full OAuth authorization URL
                        if not next_url.startswith("http"):
                            oauth_url = f"{self.authentik_url}{next_url}"
                        else:
                            oauth_url = next_url

                        self._debug(f"Following OAuth authorization: {oauth_url}")

                        # Follow OAuth authorization - this will redirect back to webapp
                        oauth_resp = client.get(oauth_url, follow_redirects=True)
                        self._debug(f"OAuth response: {oauth_resp.status_code}, URL: {oauth_resp.url}")
                        self._debug(f"Cookies: {list(client.cookies.keys())}")

                        # Check if we're back at webapp
                        if self.webapp_url in str(oauth_resp.url):
                            session_cookie = client.cookies.get("session")

                            if session_cookie and "_state_authentik_" not in session_cookie:
                                print("  ✓ Login successful")
                                self._debug(f"Session cookie: {session_cookie[:40]}...")
                                return session_cookie
                            self._debug("Session cookie check failed")
                            self._debug(f"All cookies: {dict(client.cookies)}")

                print("  ✗ Login failed")
                return None

            except Exception as e:
                print(f"  ✗ Login error: {e}")
                if self.debug:
                    import traceback
                    traceback.print_exc()
                return None

    def get_all_user_cookies(
        self, test_users: dict[str, dict[str, Any]]
    ) -> dict[str, str]:
        """
        Login all test users and return their cookies.

        Args:
            test_users: Dict of username -> {email, password}

        Returns:
            Dict of username -> session_cookie
        """
        cookies = {}

        for username, user_info in test_users.items():
            print(f"Logging in {username} ({user_info['email']})...")

            cookie = self.login_user_simple(user_info["email"], user_info["password"])

            if cookie:
                cookies[username] = cookie
                print(f"  ✓ {username} cookie obtained")
            else:
                print(f"  ✗ {username} login failed")
                cookies[username] = None

        return cookies

    def check_services(self) -> dict[str, bool]:
        """Check if required services are running."""
        services = {}

        # Check webapp
        try:
            response = httpx.get(f"{self.webapp_url}/health", timeout=5.0)
            services["webapp"] = response.status_code == 200
        except Exception:
            services["webapp"] = False

        # Check Authentik
        try:
            response = httpx.get(f"{self.authentik_url}/-/health/ready/", timeout=5.0)
            services["authentik"] = response.status_code == 200
        except Exception:
            services["authentik"] = False

        return services


def save_cookies_to_env(cookies: dict[str, str], env_file: str = ".env.test") -> None:
    """Save cookies to environment file."""
    with open(env_file, "w") as f:
        for username, cookie in cookies.items():
            if cookie:
                env_var = f"{username.upper()}_SESSION_COOKIE"
                f.write(f'{env_var}="{cookie}"\n')

    print(f"\nCookies saved to {env_file}")
    print("To use:")
    print(f"  export $(cat {env_file} | xargs)")


def load_cookies_from_env() -> dict[str, str]:
    """Load cookies from environment variables."""
    return {
        "alice": os.getenv("ALICE_SESSION_COOKIE", ""),
        "bob": os.getenv("BOB_SESSION_COOKIE", ""),
        "charlie": os.getenv("CHARLIE_SESSION_COOKIE", ""),
    }


if __name__ == "__main__":
    """Standalone script to get session cookies."""
    import sys

    # Check for --debug flag
    debug = "--debug" in sys.argv

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python tests/auth_helper.py [--debug]")
        print("\nOptions:")
        print("  --debug    Enable debug output (shows detailed HTTP flow)")
        print("  --help     Show this help message")
        sys.exit(0)

    auth = OIDCAuthenticator(debug=debug)

    if debug:
        print("\n🔍 DEBUG MODE ENABLED\n")

    # Check services
    print("Checking services...")
    services = auth.check_services()
    for service, status in services.items():
        status_str = "✓" if status else "✗"
        print(f"  {status_str} {service}")

    if not all(services.values()):
        print("\n❌ Not all services are running!")
        print("Start services with: make up")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Authenticating test users (HTTP-only, no browser)")
    if debug:
        print("Debug mode: showing detailed HTTP flow")
    print("=" * 50 + "\n")

    test_users = {
        "alice": {"email": "alice@example.com", "password": "password"},
        "bob": {"email": "bob@example.com", "password": "password"},
        "charlie": {"email": "charlie@example.com", "password": "password"},
    }

    cookies = auth.get_all_user_cookies(test_users)

    # Print results
    print("\n" + "=" * 50)
    print("Results:")
    print("=" * 50)

    success_count = sum(1 for c in cookies.values() if c)

    for username, cookie in cookies.items():
        if cookie:
            print(f"✓ {username.upper():10} {cookie[:40]}...")
        else:
            print(f"✗ {username.upper():10} Failed")

    if success_count > 0:
        print(f"\n✓ {success_count}/3 users authenticated successfully!")
        save_cookies_to_env(cookies)
    else:
        print("\n❌ No cookies obtained.")
        print("Make sure:")
        print("  - Users exist in Authentik (run: make tf-apply)")
        print("  - Credentials are correct")
        print("  - Services are running properly")
        sys.exit(1)
