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

from fastapi_topaz import PolicyGroup, TopazConfig, normalize_hyphens
from fastapi_topaz.codegen import (
    PolicyTemplate,
    generate_policies,
    generate_rights_matrix,
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
        identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user"),
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

    def test_applies_policy_path_normalizer(self, config):
        """Regression (B3): scan_routes must apply the same normalizer as the runtime."""
        app = FastAPI()

        @app.get("/aircraft-programs")
        def list_programs():
            return []

        routes = scan_routes(app, config.policy_path_root, policy_path_normalizer=normalize_hyphens)
        paths = {r["policy_path"] for r in routes}

        assert "myapp.GET.aircraft_programs" in paths
        assert "myapp.GET.aircraft-programs" not in paths


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


class TestPolicyDiffResolutionChain:
    """Tests for policy_diff with resolution chain features."""

    def test_policy_diff_group_covered(self, sample_app, config):
        """policy_diff marks routes as group_covered when group policy exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create group policy file
            group_path = Path(tmpdir) / "myapp/admin.rego"
            group_path.parent.mkdir(parents=True, exist_ok=True)
            group_path.write_text("package myapp.admin\n")

            # Create config with policy group matching the route templates
            group = PolicyGroup(
                url_pattern=r"^/documents/\{id\}$",
                policy_path="myapp.admin",
            )
            config.policy_groups = [group]

            diff = policy_diff(sample_app, config, tmpdir)

            # GET/PUT/DELETE /documents/{id} match the group pattern
            assert len(diff.group_covered) == 3
            # The group policy itself must not be flagged as orphaned (B4)
            assert diff.orphaned == []

    def test_policy_diff_default_covered(self, sample_app, config):
        """policy_diff marks routes as default_covered when default policy exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create default policy file
            default_path = Path(tmpdir) / "myapp/defaults/open.rego"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text("package myapp.defaults.open\n")

            # Set default policy
            config.default_policy = "myapp.defaults.open"

            diff = policy_diff(sample_app, config, tmpdir)

            # With default policy set and existing, all missing routes
            # should be in default_covered
            assert len(diff.default_covered) > 0
            assert len(diff.missing) == 0  # All covered by default

    def test_policy_diff_missing_no_fallback(self, sample_app, config):
        """Routes without policies are marked missing when no groups or default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            diff = policy_diff(sample_app, config, tmpdir)

            # With no policies, groups, or defaults, all routes are missing
            assert len(diff.missing) == 6  # 5 routes + ReBAC policy

    def test_policy_diff_has_issues_excludes_covered(self, sample_app, config):
        """has_issues returns False when all routes are covered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate all policies
            generate_policies(sample_app, config, output_dir=tmpdir)

            diff = policy_diff(sample_app, config, tmpdir)

            # All policies exist, so no issues
            assert diff.has_issues is False

    def test_policy_diff_orphaned_still_detected(self, sample_app, config):
        """Orphaned policies are detected even with resolution chain."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate policies
            generate_policies(sample_app, config, output_dir=tmpdir)

            # Add orphaned policy
            orphan = Path(tmpdir) / "myapp/GET/orphaned.rego"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text("package myapp.GET.orphaned\n")

            # Set default policy to prevent has_issues from missing
            config.default_policy = "myapp.defaults.fallback"

            diff = policy_diff(sample_app, config, tmpdir)

            assert "myapp.GET.orphaned" in diff.orphaned

    def test_default_policy_not_orphaned(self, sample_app, config):
        """Regression (B4): a configured default_policy file must not be orphaned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            default_path = Path(tmpdir) / "myapp/defaults/open.rego"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text("package myapp.defaults.open\n")

            config.default_policy = "myapp.defaults.open"

            diff = policy_diff(sample_app, config, tmpdir)

            assert diff.orphaned == []

    def test_group_policy_not_orphaned(self, sample_app, config):
        """Regression (B4): a configured PolicyGroup policy file must not be orphaned."""
        with tempfile.TemporaryDirectory() as tmpdir:
            group_path = Path(tmpdir) / "myapp/admin.rego"
            group_path.parent.mkdir(parents=True, exist_ok=True)
            group_path.write_text("package myapp.admin\n")

            config.policy_groups = [
                PolicyGroup(url_pattern=r"^/nonexistent$", policy_path="myapp.admin")
            ]

            diff = policy_diff(sample_app, config, tmpdir)

            assert "myapp.admin" not in diff.orphaned


class TestNormalizerRoundTrip:
    """Regression (B3+B4): generate then diff with a normalizer must be clean."""

    def test_generate_then_diff_with_normalizer(self):
        app = FastAPI()

        @app.get("/aircraft-programs")
        def list_programs():
            return []

        @app.get("/aircraft-programs/{program_id}")
        def get_program(program_id: int):
            return {}

        config = TopazConfig(
            authorizer_options=AuthorizerOptions(url="localhost:8282"),
            policy_path_root="myapp",
            identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_SUB, value="user"),
            policy_instance_name="test",
            policy_path_normalizer=normalize_hyphens,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            policies = generate_policies(app, config, output_dir=tmpdir)
            assert "myapp.GET.aircraft_programs" in policies

            diff = policy_diff(app, config, tmpdir)

            assert diff.missing == []
            assert diff.orphaned == []


class TestGenerateRightsMatrix:
    """Tests for generate_rights_matrix with resolution chain."""

    def test_rights_matrix_all_sources(self, sample_app, config):
        """generate_rights_matrix shows all resolution sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create one explicit policy
            explicit_path = Path(tmpdir) / "myapp/GET/documents.rego"
            explicit_path.parent.mkdir(parents=True, exist_ok=True)
            explicit_path.write_text("package myapp.GET.documents\n")

            # Create group policy
            group_path = Path(tmpdir) / "myapp/admin.rego"
            group_path.parent.mkdir(parents=True, exist_ok=True)
            group_path.write_text("package myapp.admin\n")

            # Create default policy
            default_path = Path(tmpdir) / "myapp/defaults/open.rego"
            default_path.parent.mkdir(parents=True, exist_ok=True)
            default_path.write_text("package myapp.defaults.open\n")

            # Configure resolution chain
            group = PolicyGroup(
                url_pattern=r"^/documents/\d+$",
                policy_path="myapp.admin",
            )
            config.policy_groups = [group]
            config.default_policy = "myapp.defaults.open"

            results = generate_rights_matrix(sample_app, config, policies_dir=tmpdir)

            # Should have one explicit (GET /documents)
            explicit = [r for r in results if r.resolution_source == "explicit"]
            assert len(explicit) >= 1

            # Should have default-covered routes
            default = [r for r in results if r.resolution_source == "default"]
            assert len(default) > 0

    def test_rights_matrix_markdown_output(self, sample_app, config):
        """generate_rights_matrix produces valid Markdown output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "matrix.md"

            generate_rights_matrix(
                sample_app,
                config,
                policies_dir=None,
                output_file=output_file,
            )

            # File should be created
            assert output_file.exists()

            content = output_file.read_text()

            # Should contain expected sections
            assert "# Rights Matrix" in content
            assert "## Summary" in content
            assert "## Routes by Resolution Source" in content
            assert "| Method | Route | Resolved Policy" in content

            # Should have data rows
            assert "GET" in content
            assert "documents" in content
