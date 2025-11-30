"""
Tests for policy generation and validation.

The codegen module generates Rego policy skeletons from FastAPI routes and
validates existing policies against route definitions. Useful for bootstrapping
policies and detecting drift.

Test organization:
- TestScanRoutes: Route scanning and policy path generation
- TestGeneratePolicies: Rego policy file generation
- TestPolicyDiff: Comparing routes against existing policies
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import FastAPI

from fastapi_topaz import TopazConfig
from fastapi_topaz.codegen import (
    PolicyTemplate,
    generate_policies,
    policy_diff,
    scan_routes,
)


@pytest.fixture
def sample_app():
    """Sample FastAPI app with CRUD routes for testing policy generation."""
    app = FastAPI()

    @app.get("/documents")
    def list_docs():
        return []

    @app.post("/documents")
    def create_doc():
        return {}

    @app.get("/documents/{id}")
    def get_doc(id: int):
        return {}

    @app.put("/documents/{id}")
    def update_doc(id: int):
        return {}

    @app.delete("/documents/{id}")
    def delete_doc(id: int):
        return {}

    return app


@pytest.fixture
def config():
    """Create a test TopazConfig."""
    return TopazConfig(
        authorizer_options=AuthorizerOptions(url="localhost:8282"),
        policy_path_root="myapp",
        identity_provider=lambda r: Identity(
            type=IdentityType.IDENTITY_TYPE_SUB, value="user"
        ),
        policy_instance_name="test",
    )


class TestScanRoutes:
    """Route scanning extracts policy paths from FastAPI route definitions."""

    def test_scans_all_routes(self, sample_app, config):
        routes = scan_routes(sample_app, config.policy_path_root)
        # Should have 5 routes (GET, POST, GET/{id}, PUT/{id}, DELETE/{id})
        assert len(routes) == 5

    def test_generates_correct_policy_paths(self, sample_app, config):
        routes = scan_routes(sample_app, config.policy_path_root)
        paths = {r["policy_path"] for r in routes}

        assert "myapp.GET.documents" in paths
        assert "myapp.POST.documents" in paths
        assert "myapp.GET.documents.__id" in paths
        assert "myapp.PUT.documents.__id" in paths
        assert "myapp.DELETE.documents.__id" in paths


class TestGeneratePolicies:
    """Rego policy skeleton generation with customizable templates."""

    def test_generates_all_policies(self, sample_app, config):
        policies = generate_policies(sample_app, config)
        # 5 routes + 1 ReBAC check policy
        assert len(policies) == 6

    def test_generates_valid_rego(self, sample_app, config):
        policies = generate_policies(sample_app, config)

        for path, content in policies.items():
            assert f"package {path}" in content
            assert "import rego.v1" in content
            assert "default allowed" in content

    def test_writes_to_output_dir(self, sample_app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            policies = generate_policies(sample_app, config, output_dir=tmpdir)

            output_path = Path(tmpdir)
            assert output_path.exists()
            # Check at least one file was created
            rego_files = list(output_path.rglob("*.rego"))
            assert len(rego_files) == len(policies)

    def test_custom_template(self, sample_app, config):
        template = PolicyTemplate(
            default_decision=True,
            include_comments=False,
        )
        policies = generate_policies(sample_app, config, template=template)

        for content in policies.values():
            assert "default allowed = true" in content


class TestPolicyDiff:
    """Compare routes against existing policies to detect missing or orphaned policies."""

    def test_detects_missing_policies(self, sample_app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            diff = policy_diff(sample_app, config, tmpdir)
            # All policies should be missing
            assert len(diff.missing) == 6  # 5 routes + ReBAC

    def test_detects_valid_policies(self, sample_app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate policies first
            generate_policies(sample_app, config, output_dir=tmpdir)
            # Now diff should show all valid
            diff = policy_diff(sample_app, config, tmpdir)

            assert len(diff.missing) == 0
            assert len(diff.valid) == 6

    def test_detects_orphaned_policies(self, sample_app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate policies
            generate_policies(sample_app, config, output_dir=tmpdir)

            # Add an orphaned policy
            orphan = Path(tmpdir) / "myapp/GET/old_endpoint.rego"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text("package myapp.GET.old_endpoint\n")

            diff = policy_diff(sample_app, config, tmpdir)
            assert "myapp.GET.old_endpoint" in diff.orphaned
