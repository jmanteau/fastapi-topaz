"""
Integration Test: fastapi-topaz 1.2.x features against real Topaz and Authentik

1. Frontend routes (app.frontend) are authorized by TopazMiddleware
2. Mounts are authorized against their own prefix-only policy
3. annotate_openapi stamps prefixed policy paths into /openapi.json
4. check_relations(batch=True) matches per-relation checks
5. expose_deny_reason names the evaluated policy in 403 bodies
6. TopazConfig.health(ping=True) reports a reachable authorizer
"""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import AuthenticatedClient


@pytest.fixture(scope="module")
def health(base_url: str) -> dict:
    return httpx.get(f"{base_url}/health", timeout=10.0).json()


@pytest.fixture(scope="module")
def anon(base_url: str):
    with httpx.Client(base_url=base_url, follow_redirects=False, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="module")
def openapi(base_url: str) -> dict:
    return httpx.get(f"{base_url}/openapi.json", timeout=10.0).json()


def test_frontend_route_is_authorized(health, anon, alice_client: AuthenticatedClient):
    """Frontend routes are matched outside app.routes; the middleware must still check them."""
    if not health["frontend"]:
        pytest.skip(f"FastAPI {health['fastapi']} has no app.frontend()")

    assert anon.get("/app/app.js").status_code == 401

    response = alice_client.get("/app/app.js")
    assert response.status_code == 200
    assert "frontend ok" in response.text


def test_mount_is_authorized(anon, alice_client: AuthenticatedClient):
    """/files is not excluded: anonymous is rejected, webapp.GET.files allows Alice."""
    assert anon.get("/files/hello.txt").status_code == 401

    response = alice_client.get("/files/hello.txt")
    assert response.status_code == 200
    assert "authorized mount" in response.text


def test_mount_uses_its_own_policy(alice_client: AuthenticatedClient):
    """webapp.GET.restricted denies everyone, so an authenticated user gets 403 too."""
    response = alice_client.get("/restricted/secret.txt")
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Forbidden",
        "policy": "webapp.GET.restricted",
        "source": "middleware",
    }


@pytest.mark.parametrize(
    ("method", "path", "policy", "source"),
    [
        ("get", "/api/folders/{id}", "webapp.GET.api.folders.__id", "explicit"),
        ("post", "/api/folders", "webapp.POST.api.folders", "explicit"),
        ("get", "/api/documents", "webapp.defaults.authenticated", "default"),
        ("post", "/api/shares", "webapp.defaults.authenticated", "group"),
    ],
)
def test_openapi_annotations_include_router_prefix(openapi, method, path, policy, source):
    """Routes from prefixed routers are annotated with the prefixed policy path."""
    operation = openapi["paths"][path][method]
    assert operation["x-authz-policy"] == policy
    assert operation["x-authz-source"] == source


def test_batch_check_relations_matches_per_relation(
    alice_client: AuthenticatedClient, bob_client: AuthenticatedClient
):
    """?batch=true (one Topaz call) returns the same permissions as one call per relation."""
    created = alice_client.post(
        "/api/documents",
        json={"name": "Batch Check.txt", "content": "x", "is_public": False},
    )
    assert created.status_code == 201
    doc_id = created.json()["id"]

    per_relation = alice_client.get(f"/api/documents/{doc_id}/permissions")
    batched = alice_client.get(f"/api/documents/{doc_id}/permissions?batch=true")
    assert per_relation.status_code == batched.status_code == 200
    assert batched.json() == per_relation.json()
    assert batched.json()["can_read"] is True
    assert batched.json()["can_delete"] is True

    # Any authenticated user may ask for their own permissions; Bob has none here
    bob_per_relation = bob_client.get(f"/api/documents/{doc_id}/permissions").json()
    bob_batched = bob_client.get(f"/api/documents/{doc_id}/permissions?batch=true").json()
    assert bob_batched == bob_per_relation
    assert not any(bob_batched[k] for k in ("can_read", "can_write", "can_delete", "can_share"))


def test_health_reports_reachable_authorizer(health):
    """/health embeds TopazConfig.health(ping=True)."""
    topaz = health["topaz"]
    assert topaz["healthy"] is True
    assert topaz["ping"] == {"ok": True, "error": None}
    assert topaz["circuit_breaker"]["state"] == "closed"
