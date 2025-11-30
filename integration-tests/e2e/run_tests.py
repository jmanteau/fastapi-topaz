#!/usr/bin/env python3
"""
Integration Test Runner

Runs integration tests against the full application stack with automatic
service health checks and HTTP-based authentication (no browser required).

Usage:
    python run_tests.py                 # Run all tests
    python run_tests.py alice           # Run Alice's workflow tests
    python run_tests.py bob             # Run Bob's workflow tests
    python run_tests.py sharing         # Run sharing scenarios
    python run_tests.py auth-failures   # Run authorization failure tests
    python run_tests.py public          # Run public document tests
    python run_tests.py --get-cookies   # Get session cookies
    python run_tests.py --help          # Show help
"""

from __future__ import annotations

import subprocess
import sys

import httpx


def check_services() -> bool:
    """Check if required services are running."""
    print("\n" + "=" * 60)
    print("Checking Services")
    print("=" * 60)

    services = {
        "Webapp": "http://localhost:8000/health",
        "Authentik": "http://localhost:9000/-/health/ready/",
    }

    all_ok = True
    for name, url in services.items():
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code == 200:
                print(f"✓ {name:15} OK")
            else:
                print(f"✗ {name:15} FAILED (status {response.status_code})")
                all_ok = False
        except Exception as e:
            print(f"✗ {name:15} FAILED ({e})")
            all_ok = False

    return all_ok


def run_pytest(test_path: str = "", extra_args: list[str] | None = None) -> int:
    """Run pytest with given arguments."""
    args = ["uv", "run", "pytest", "-v"]

    if test_path:
        args.append(test_path)

    if extra_args:
        args.extend(extra_args)

    return subprocess.call(args)


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print(__doc__)
        print("\nAvailable test scenarios:")
        print("  alice            Alice's workflow tests")
        print("  bob              Bob's workflow tests")
        print("  sharing          Document sharing scenarios")
        print("  auth-failures    Authorization failure tests (security)")
        print("  public           Public document scenarios")
        print("\nOptions:")
        print("  --get-cookies    Get session cookies using HTTP auth")
        print("  --debug          Enable debug output (shows HTTP flow)")
        print("  --setup          Show setup instructions")
        print("  -v               Verbose output")
        print("  -s               Show print statements")
        print("  -x               Stop on first failure")
        print("  -k EXPRESSION    Run tests matching expression")
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        show_setup()
        return 0

    if len(sys.argv) > 1 and sys.argv[1] == "--get-cookies":
        return get_cookies()

    # Check services
    if not check_services():
        print("\n❌ Some services are not running!")
        print("Start services with: make up")
        print("Or: docker-compose up -d")
        return 1

    # Determine which tests to run
    test_path = ""
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
        test_files = {
            "alice": "tests/test_scenario_alice.py",
            "bob": "tests/test_scenario_bob.py",
            "sharing": "tests/test_scenario_sharing.py",
            "auth-failures": "tests/test_scenario_authorization_failures.py",
            "failures": "tests/test_scenario_authorization_failures.py",
            "public": "tests/test_scenario_public_documents.py",
        }

        if scenario in test_files:
            test_path = test_files[scenario]
            print(f"\n▶ Running {scenario} tests...")
        elif scenario.startswith("-"):
            # It's a pytest option
            pass
        else:
            print(f"Unknown scenario: {scenario}")
            print("Use --help to see available scenarios")
            return 1
    else:
        test_path = "tests/"
        print("\n▶ Running all integration tests...")

    # Run tests
    print("=" * 60)
    print()

    exit_code = run_pytest(test_path, sys.argv[2:] if len(sys.argv) > 2 else None)

    print()
    if exit_code == 0:
        print("✓ Tests passed!")
    else:
        print("✗ Tests failed")

    return exit_code


def show_setup():
    """Show setup instructions."""
    print("""
========================================
Integration Test Setup Guide
========================================

1. Start all services:
   $ cd /Users/to108637/DevProjects/topaz-poc
   $ make up

2. Create test users in Authentik:
   $ make tf-init
   $ make tf-apply

   This creates:
   - alice@example.com (password: password)
   - bob@example.com (password: password)
   - charlie@example.com (password: password)

3. Install test dependencies:
   $ cd integration-tests
   $ uv pip install -e .

4. Run tests (automatic HTTP-based authentication):
   $ python run_tests.py

   OR get cookies once and reuse:
   $ python run_tests.py --get-cookies
   $ export $(cat .env.test | xargs)
   $ python run_tests.py  # Much faster!

Key Features:
✓ HTTP-only authentication (no browser needed!)
✓ Automatic service health checks
✓ Smart cookie caching
✓ 49 integration tests covering all workflows

For detailed documentation:
   $ cat README.md
""")


def get_cookies():
    """Get session cookies using HTTP authentication."""
    from tests.auth_helper import OIDCAuthenticator, save_cookies_to_env

    # Check for debug flag
    debug = "--debug" in sys.argv

    print("\n" + "=" * 60)
    print("Getting Session Cookies (HTTP-only, no browser)")
    if debug:
        print("Debug mode enabled")
    print("=" * 60)

    # Check services
    if not check_services():
        print("\n❌ Services not running!")
        return 1

    auth = OIDCAuthenticator(debug=debug)

    test_users = {
        "alice": {"email": "alice@example.com", "password": "password"},
        "bob": {"email": "bob@example.com", "password": "password"},
        "charlie": {"email": "charlie@example.com", "password": "password"},
    }

    print("\n▶ Authenticating users via HTTP...\n")

    cookies = auth.get_all_user_cookies(test_users)

    # Show results
    print("\n" + "=" * 60)
    print("Results")
    print("=" * 60)

    success = True
    for username, cookie in cookies.items():
        if cookie:
            print(f"✓ {username.upper():10} {cookie[:40]}...")
        else:
            print(f"✗ {username.upper():10} Failed")
            success = False

    if success:
        print("\n✓ All cookies obtained successfully!")
        save_cookies_to_env(cookies)
        print("\nTo use in tests:")
        print("  export $(cat .env.test | xargs)")
        print("  python run_tests.py")
    else:
        print("\n❌ Failed to get some cookies")
        print("Check that:")
        print("  - Users exist in Authentik (run: make tf-apply)")
        print("  - Credentials are correct")
        print("  - Services are properly configured")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
