"""Live tests for TopazMiddleware on_error handling (fix C3), full ASGI stack.

A minimal FastAPI app protected by TopazMiddleware is exercised through
httpx's ASGITransport, with authorization decisions made by the real Topaz
over TLS gRPC. Error paths use a real DEADLINE_EXCEEDED (tiny timeout) or a
real UNAVAILABLE (stopped container).
"""

from __future__ import annotations

from typing import Literal

import httpx
import pytest
from conftest import AUTH_POLICY, SUB_HEADER
from fastapi import FastAPI

from fastapi_topaz import TopazMiddleware


def _make_app(
    config,
    on_error: Literal["deny", "unavailable"] = "deny",
    on_missing_identity: Literal["deny", "anonymous"] = "deny",
) -> FastAPI:
    app = FastAPI()

    @app.get("/resource")
    async def resource():
        return {"ok": True}

    app.add_middleware(
        TopazMiddleware,
        config=config,
        on_missing_identity=on_missing_identity,
        on_error=on_error,
    )
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


async def test_middleware_allow_200(make_config):
    config = make_config(default_policy=AUTH_POLICY)
    async with _client(_make_app(config)) as client:
        response = await client.get("/resource", headers={SUB_HEADER: "alice"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_middleware_deny_403(make_config):
    config = make_config(default_policy=AUTH_POLICY)
    async with _client(_make_app(config, on_missing_identity="anonymous")) as client:
        response = await client.get("/resource")
    assert response.status_code == 403


async def test_on_error_deny_403(make_config):
    config = make_config(default_policy=AUTH_POLICY, check_timeout=0.000001)
    async with _client(_make_app(config, on_error="deny")) as client:
        response = await client.get("/resource", headers={SUB_HEADER: "alice"})
    assert response.status_code == 403


async def test_on_error_unavailable_503(make_config):
    config = make_config(default_policy=AUTH_POLICY, check_timeout=0.000001)
    async with _client(_make_app(config, on_error="unavailable")) as client:
        response = await client.get("/resource", headers={SUB_HEADER: "alice"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Authorization service unavailable"}


@pytest.mark.disruptive
async def test_on_error_503_real_outage(make_config, topaz_control):
    config = make_config(default_policy=AUTH_POLICY, check_timeout=5.0)
    try:
        topaz_control.stop()
        async with _client(_make_app(config, on_error="unavailable")) as client:
            response = await client.get("/resource", headers={SUB_HEADER: "alice"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Authorization service unavailable"}
    finally:
        topaz_control.start()
        topaz_control.wait_ready()
