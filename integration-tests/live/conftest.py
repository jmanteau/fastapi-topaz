"""Fixtures for live-Topaz integration tests.

These tests exercise fastapi_topaz against the real Topaz authorizer from the
integration docker stack (gRPC TLS on localhost:8282). The whole session is
skipped with a clear reason when docker, the TLS certs, or Topaz itself are
unavailable. Set LIVE_TOPAZ_NO_START=1 to forbid the suite from starting the
container itself (used to verify the clean-skip path).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import aserto.authorizer.v2 as authorizer_pb
import aserto.authorizer.v2.api as api
import aserto.client.resource_context as res_ctx
import grpc
import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType, ResourceContext
from fastapi import Request

from fastapi_topaz import TopazConfig

INT_DIR = Path(__file__).resolve().parents[1]
CA_CERT = INT_DIR / "infra" / "certs" / "ca.crt"
AUTHORIZER_URL = "localhost:8282"
AUTH_POLICY = "webapp.defaults.authenticated"
POLICY_INSTANCE = "webapp"
READY_TIMEOUT = 60.0

SUB_HEADER = "x-test-sub"


# ---------------------------------------------------------------------------
# Topaz readiness
# ---------------------------------------------------------------------------


def _probe_decision_sync(timeout: float = 5.0) -> bool:
    """One real Is() call over TLS gRPC; returns the 'allowed' decision.

    Uses the sync gRPC API so it can be called from sync fixtures and from
    within async tests (asyncio.run is unavailable inside a running loop).
    """
    channel = grpc.secure_channel(
        AUTHORIZER_URL, grpc.ssl_channel_credentials(CA_CERT.read_bytes())
    )
    try:
        stub = authorizer_pb.AuthorizerStub(channel)
        response = stub.Is(
            authorizer_pb.IsRequest(
                policy_context=api.PolicyContext(path=AUTH_POLICY, decisions=["allowed"]),
                identity_context=api.IdentityContext(
                    identity="warmup", type=IdentityType.IDENTITY_TYPE_MANUAL
                ),
                resource_context=res_ctx.serialize_resource_context(
                    {"current_user": {"sub": "warmup"}}
                ),
                policy_instance=api.PolicyInstance(
                    name=POLICY_INSTANCE, instance_label=POLICY_INSTANCE
                ),
            ),
            timeout=timeout,
        )
        return any(getattr(d, "is") for d in response.decisions if d.decision == "allowed")
    finally:
        channel.close()


def _wait_topaz_ready(timeout: float = READY_TIMEOUT) -> None:
    """Wait until Topaz serves real decisions over gRPC.

    Port 9494 exposes a gRPC (not HTTP) health service, and it turns green
    before the OPA bundle finishes loading anyway, so readiness is a real
    warm-up decision probe retried while the authorizer is UNAVAILABLE.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            if _probe_decision_sync():
                return
            last_error = RuntimeError("warm-up probe returned allowed=false")
        except grpc.RpcError as e:
            last_error = e
        time.sleep(1.0)
    raise RuntimeError(f"Topaz not serving decisions after {timeout}s: {last_error}")


# ---------------------------------------------------------------------------
# Session gate and container control
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def compose_cmd() -> list[str]:
    """Resolve the docker compose command, skipping the session if absent."""
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], capture_output=True, check=False)
        if probe.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    pytest.skip("docker compose is not available on this machine")


@pytest.fixture(scope="session", autouse=True)
def topaz_session(compose_cmd: list[str]) -> None:
    """Ensure a ready Topaz for the whole session, or skip cleanly."""
    if not CA_CERT.is_file():
        pytest.skip(f"TLS CA cert not found at {CA_CERT} (run 'make int-certs')")

    if os.environ.get("LIVE_TOPAZ_NO_START") != "1":
        up = subprocess.run(
            [*compose_cmd, "up", "-d", "topaz"],
            cwd=INT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if up.returncode != 0:
            pytest.skip(
                "could not start the topaz container "
                f"(run 'make int-up-topaz' first): {up.stderr.strip()}"
            )

    try:
        _wait_topaz_ready()
    except RuntimeError as e:
        pytest.skip(f"Topaz is not reachable: {e}")


class TopazControl:
    """Stop/start the topaz container to simulate authorizer outages."""

    def __init__(self, compose_cmd: list[str]) -> None:
        self._compose_cmd = compose_cmd
        self.stopped = False

    def _run(self, action: str) -> None:
        subprocess.run(
            [*self._compose_cmd, action, "topaz"],
            cwd=INT_DIR,
            capture_output=True,
            check=True,
        )

    def stop(self) -> None:
        self._run("stop")
        self.stopped = True

    def start(self) -> None:
        self._run("start")
        self.stopped = False

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        _wait_topaz_ready(timeout)

    def restore(self) -> None:
        """Restart topaz and wait for readiness if a test left it stopped."""
        if self.stopped:
            self.start()
            self.wait_ready()


@pytest.fixture(scope="session")
def topaz_control(compose_cmd: list[str], topaz_session: None) -> Any:
    control = TopazControl(compose_cmd)
    yield control
    control.restore()


# ---------------------------------------------------------------------------
# TopazConfig factory and request helper
# ---------------------------------------------------------------------------


def _identity_provider(request: Request) -> Identity:
    sub = request.headers.get(SUB_HEADER)
    if sub:
        return Identity(type=IdentityType.IDENTITY_TYPE_MANUAL, value=sub)
    return Identity(type=IdentityType.IDENTITY_TYPE_NONE)


def _resource_context_provider(request: Request) -> ResourceContext:
    sub = request.headers.get(SUB_HEADER)
    if sub:
        return {"current_user": {"sub": sub}}
    return {}


@pytest.fixture
async def make_config() -> Any:
    """Factory for TopazConfig instances pointed at the live Topaz.

    Created function-scoped (inside the running loop) because TopazConfig
    builds asyncio primitives in __init__. Every created config is closed
    on teardown.
    """
    created: list[TopazConfig] = []

    def _make(**kwargs: Any) -> TopazConfig:
        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url=AUTHORIZER_URL, cert_file_path=str(CA_CERT)),
            policy_path_root="webapp",
            policy_instance_name=POLICY_INSTANCE,
            identity_provider=_identity_provider,
            resource_context_provider=_resource_context_provider,
            **kwargs,
        )
        created.append(config)
        return config

    yield _make
    for config in created:
        await config.close()


@pytest.fixture
def make_request() -> Callable[..., Request]:
    """Build a minimal starlette Request carrying the X-Test-Sub header."""

    def _make(sub: str | None = None) -> Request:
        headers = [(SUB_HEADER.encode(), sub.encode())] if sub else []
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/live-test",
            "headers": headers,
            "query_string": b"",
            "path_params": {},
        }
        return Request(scope)

    return _make
