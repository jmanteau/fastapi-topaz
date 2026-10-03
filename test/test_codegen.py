"""
Tests for policy generation and validation.

The codegen module generates Rego policy skeletons from FastAPI routes and
validates existing policies against route definitions. Useful for bootstrapping
policies and detecting drift.

Test organization:
- TestScanRoutes: Route scanning and policy path generation
- TestGeneratePolicies: Rego policy file generation
- TestPolicyDiff: Comparing routes against existing policies
- TestFrontendAndMountRoutes: Frontend routes and mounts in scans and diffs
- TestSkippedRoutes: Routes TopazMiddleware skips are reported as skipped
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi import APIRouter, Depends, FastAPI

from fastapi_topaz import (
    PolicyGroup,
    SkipMiddleware,
    TopazConfig,
    TopazMiddleware,
    normalize_hyphens,
    skip_middleware,
)
from fastapi_topaz._routes import FrontendMatchError, iter_frontend_paths
from fastapi_topaz.codegen import (
    PolicyTemplate,
    annotate_openapi,
    generate_policies,
    generate_rights_matrix,
    policy_diff,
    scan_routes,
)

requires_frontend = pytest.mark.skipif(
    not hasattr(FastAPI, "frontend"), reason="FastAPI without frontend routes"
)


# Docs routes are scanned by default; these fixtures count only app routes
NO_DOCS = {"openapi_url": None, "docs_url": None, "redoc_url": None}


@pytest.fixture
def sample_app():
    """Sample FastAPI app with CRUD routes for testing policy generation."""
    app = FastAPI(**NO_DOCS)

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

    def test_includes_routes_from_included_routers(self, config):
        app = FastAPI(**NO_DOCS)
        router = APIRouter(prefix="/folders")

        @router.get("/{folder_id}")
        def get_folder(folder_id: int):
            return {}

        app.include_router(router)

        routes = scan_routes(app, config.policy_path_root)
        assert [(r["method"], r["path"], r["policy_path"]) for r in routes] == [
            ("GET", "/folders/{folder_id}", "myapp.GET.folders.__folder_id")
        ]


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

    def test_existing_file_kept_unless_overwrite(self, sample_app, config, tmp_path):
        policies = generate_policies(sample_app, config, output_dir=tmp_path)
        target = tmp_path / f"{next(iter(policies)).replace('.', '/')}.rego"
        target.write_text("# custom policy\n")

        generate_policies(sample_app, config, output_dir=tmp_path)
        assert target.read_text() == "# custom policy\n"

        generate_policies(sample_app, config, output_dir=tmp_path, overwrite=True)
        assert target.read_text() == policies[next(iter(policies))]

    def test_custom_template(self, sample_app, config):
        template = PolicyTemplate(
            default_decision=True,
            include_comments=False,
        )
        policies = generate_policies(sample_app, config, template=template)

        for content in policies.values():
            assert "default allowed = true" in content


class TestFrontendAndMountRoutes:
    """Frontend routes and mounts are authorized by the middleware, so they must be scanned."""

    @pytest.fixture
    def dist(self, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        return tmp_path

    @requires_frontend
    def test_scans_frontend_routes(self, config, dist):
        app = FastAPI(**NO_DOCS)
        app.frontend("/app", directory=dist)
        router = APIRouter()
        router.frontend("/", directory=dist)
        app.include_router(router, prefix="/ui")
        inner = APIRouter()
        inner.frontend("/ui", directory=dist)
        outer = APIRouter()
        outer.include_router(inner, prefix="/in")
        app.include_router(outer, prefix="/out")

        routes = scan_routes(app, config.policy_path_root)
        assert [(r["method"], r["path"], r["policy_path"]) for r in routes] == [
            ("GET", "/app", "myapp.GET.app"),
            ("GET", "/ui", "myapp.GET.ui"),
            ("GET", "/out/in/ui", "myapp.GET.out.in.ui"),
        ]

    @requires_frontend
    def test_policy_diff_reports_missing_frontend_policy(self, config, dist):
        app = FastAPI(**NO_DOCS)
        app.frontend("/app", directory=dist)

        with tempfile.TemporaryDirectory() as tmpdir:
            diff = policy_diff(app, config, tmpdir)
        assert "myapp.GET.app" in [m.policy_path for m in diff.missing]

    @requires_frontend
    def test_frontend_layout_change_fails_loudly(self, dist, monkeypatch):
        from fastapi.routing import APIRouter as FastAPIRouter

        app = FastAPI(**NO_DOCS)
        app.frontend("/app", directory=dist)
        monkeypatch.delattr(FastAPIRouter, "_iter_low_priority_routes")

        with pytest.raises(FrontendMatchError):
            iter_frontend_paths(app)

    def test_scans_mount_for_every_authorized_method(self, config):
        app = FastAPI(**NO_DOCS)
        app.mount("/sub", FastAPI())

        routes = scan_routes(app, config.policy_path_root)
        assert sorted((r["method"], r["path"]) for r in routes) == [
            ("DELETE", "/sub"),
            ("GET", "/sub"),
            ("PATCH", "/sub"),
            ("POST", "/sub"),
            ("PUT", "/sub"),
        ]

    def test_skips_websocket_routes(self, config):
        app = FastAPI(**NO_DOCS)

        @app.websocket("/ws")
        async def ws(websocket):
            pass

        assert scan_routes(app, config.policy_path_root) == []


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


class TestAnnotateOpenapi:
    """annotate_openapi() writes x-authz-policy extensions into the schema."""

    def test_annotations_appear_in_openapi_schema(self, sample_app, config):
        count = annotate_openapi(sample_app, config)
        assert count == 5

        schema = sample_app.openapi()
        get_docs = schema["paths"]["/documents"]["get"]
        assert get_docs["x-authz-policy"] == "myapp.GET.documents"
        assert get_docs["x-authz-source"] == "generated"
        get_doc = schema["paths"]["/documents/{id}"]["get"]
        assert get_doc["x-authz-policy"] == "myapp.GET.documents.__id"

    def test_resolution_sources(self, sample_app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            explicit_path = Path(tmpdir) / "myapp/GET/documents.rego"
            explicit_path.parent.mkdir(parents=True, exist_ok=True)
            explicit_path.write_text("package myapp.GET.documents\n")

            config.policy_groups = [
                PolicyGroup(url_pattern=r"^/documents/\{id\}$", policy_path="myapp.admin")
            ]
            config.default_policy = "myapp.defaults.open"

            annotate_openapi(sample_app, config, policies_dir=tmpdir)

            schema = sample_app.openapi()
            get_docs = schema["paths"]["/documents"]["get"]
            assert get_docs["x-authz-policy"] == "myapp.GET.documents"
            assert get_docs["x-authz-source"] == "explicit"

            get_doc = schema["paths"]["/documents/{id}"]["get"]
            assert get_doc["x-authz-policy"] == "myapp.admin"
            assert get_doc["x-authz-source"] == "group"

            post_docs = schema["paths"]["/documents"]["post"]
            assert post_docs["x-authz-policy"] == "myapp.defaults.open"
            assert post_docs["x-authz-source"] == "default"

    def test_existing_openapi_extra_preserved(self, config):
        app = FastAPI()

        @app.get("/items", openapi_extra={"x-custom": "kept"})
        def list_items():
            return []

        count = annotate_openapi(app, config)
        assert count == 1

        schema = app.openapi()
        operation = schema["paths"]["/items"]["get"]
        assert operation["x-custom"] == "kept"
        assert operation["x-authz-policy"] == "myapp.GET.items"

    def test_annotates_routes_from_included_routers(self, config):
        app = FastAPI()
        router = APIRouter(prefix="/folders")

        @router.get("/{folder_id}")
        def get_folder(folder_id: int):
            return {}

        app.include_router(router)

        assert annotate_openapi(app, config) == 1
        operation = app.openapi()["paths"]["/folders/{folder_id}"]["get"]
        assert operation["x-authz-policy"] == "myapp.GET.folders.__folder_id"
        assert operation["x-authz-source"] == "generated"

    def test_router_included_twice_never_gets_other_prefix_policy(self, config):
        app = FastAPI()
        router = APIRouter()

        @router.get("/items")
        def items():
            return []

        app.include_router(router, prefix="/a")
        app.include_router(router, prefix="/b")
        assert annotate_openapi(app, config) == 2

        # Adding a route makes FastAPI >= 0.137 rebuild included route contexts
        # from the original routes
        @router.get("/later")
        def later():
            return []

        paths = app.openapi()["paths"]
        assert paths["/a/items"]["get"].get("x-authz-policy") in (None, "myapp.GET.a.items")
        assert paths["/b/items"]["get"].get("x-authz-policy") in (None, "myapp.GET.b.items")

    def test_excluded_routes_not_annotated(self, sample_app, config):
        annotate_openapi(sample_app, config)
        for route in sample_app.routes:
            if getattr(route, "path", None) == "/openapi.json":
                assert getattr(route, "openapi_extra", None) is None


def _write_policy(root: Path, policy_path: str) -> None:
    path = root / f"{policy_path.replace('.', '/')}.rego"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"package {policy_path}\n")


class TestPolicyDiffFirstGroupDecides:
    """Regression: policy_diff fell through to later groups or the default
    when the first matching group had no file; the middleware never does."""

    def test_first_group_without_file_is_missing(self, config, tmp_path):
        app = FastAPI(**NO_DOCS)

        @app.get("/admin/jobs")
        def jobs():
            return []

        config.policy_groups = [
            PolicyGroup(url_pattern=r"^/admin/", policy_path="myapp.admin_strict"),
            PolicyGroup(url_pattern=r"^/admin/", policy_path="myapp.admin_loose"),
        ]
        config.default_policy = "myapp.defaults.open"
        _write_policy(tmp_path, "myapp.admin_loose")
        _write_policy(tmp_path, "myapp.defaults.open")

        diff = policy_diff(app, config, tmp_path)

        assert [m.policy_path for m in diff.missing] == ["myapp.GET.admin.jobs"]
        assert diff.group_covered == []
        assert "myapp.GET.admin.jobs" not in diff.default_covered

    def test_first_group_with_file_is_covered(self, config, tmp_path):
        app = FastAPI(**NO_DOCS)

        @app.get("/admin/jobs")
        def jobs():
            return []

        config.policy_groups = [
            PolicyGroup(url_pattern=r"^/admin/", policy_path="myapp.admin_strict"),
        ]
        _write_policy(tmp_path, "myapp.admin_strict")

        diff = policy_diff(app, config, tmp_path)

        assert diff.group_covered == ["myapp.GET.admin.jobs"]


class TestDocsRoutesScannedByDefault:
    """Codegen lists docs routes because the middleware authorizes them."""

    def test_docs_routes_listed(self, config):
        routes = scan_routes(FastAPI(), config.policy_path_root)
        pairs = {(r["method"], r["path"]) for r in routes}
        assert ("GET", "/docs") in pairs
        assert ("GET", "/openapi.json") in pairs

    def test_explicit_exclude_still_works(self, config):
        routes = scan_routes(FastAPI(), config.policy_path_root, exclude_paths={"/docs"})
        pairs = {(r["method"], r["path"]) for r in routes}
        assert ("GET", "/docs") not in pairs
        assert ("GET", "/openapi.json") in pairs


class TestTypedPathParams:
    """Regression: {x:path} produced a ':' in the policy path and package line."""

    def test_converter_stripped_from_policy_path_and_package(self, config):
        app = FastAPI(**NO_DOCS)

        @app.get("/files/{name:path}")
        def get_file(name: str):
            return {}

        @app.get("/items/{id:int}")
        def get_item(id: int):
            return {}

        policies = generate_policies(app, config)

        assert "myapp.GET.files.__name" in policies
        assert "myapp.GET.items.__id" in policies
        for path, rego in policies.items():
            assert ":" not in path
            assert ":" not in rego.splitlines()[0]
        assert "input.resource.name" in policies["myapp.GET.files.__name"]

    def test_untyped_param_unchanged(self, config):
        assert config.policy_path_for("GET", "/items/{id}") == "myapp.GET.items.__id"


class TestSkeletonsSkipCoveredRoutes:
    """Regression: skeletons for group/default-covered routes were dead
    per-route files that could replace stricter shared policies."""

    def _app(self):
        app = FastAPI(**NO_DOCS)

        @app.get("/admin/jobs")
        def jobs():
            return []

        @app.get("/public")
        def public():
            return []

        return app

    def test_group_covered_route_gets_no_skeleton(self, config):
        config.policy_groups = [PolicyGroup(url_pattern=r"^/admin/", policy_path="myapp.admin")]

        policies = generate_policies(self._app(), config)

        assert "myapp.GET.admin.jobs" not in policies
        # An uncovered route still gets one, and the check policy is always generated
        assert "myapp.GET.public" in policies
        assert "myapp.check" in policies

    def test_default_covered_route_gets_no_skeleton(self, config):
        config.default_policy = "myapp.defaults.open"

        policies = generate_policies(self._app(), config)

        assert set(policies) == {"myapp.check"}


class TestAnnotateOpenapiPerMethod:
    """One route object with several methods can resolve differently per method."""

    def _app(self):
        app = FastAPI()

        @app.api_route("/items", methods=["POST", "GET"])
        def items():
            return []

        return app

    def test_differing_methods_written_as_sorted_maps(self, config, tmp_path):
        app = self._app()
        _write_policy(tmp_path, "myapp.GET.items")
        config.default_policy = "myapp.defaults.open"

        annotate_openapi(app, config, policies_dir=tmp_path)

        op = app.openapi()["paths"]["/items"]["get"]
        assert op["x-authz-policy"] == {"GET": "myapp.GET.items", "POST": "myapp.defaults.open"}
        assert op["x-authz-source"] == {"GET": "explicit", "POST": "default"}
        assert list(op["x-authz-policy"]) == ["GET", "POST"]

    def test_agreeing_methods_written_as_strings(self, config):
        app = self._app()
        config.default_policy = "myapp.defaults.open"

        annotate_openapi(app, config)

        op = app.openapi()["paths"]["/items"]["post"]
        assert op["x-authz-policy"] == "myapp.defaults.open"
        assert op["x-authz-source"] == "default"


class TestSkippedRoutes:
    """Routes TopazMiddleware never checks are reported as skipped, not as authorized."""

    @pytest.fixture
    def app(self, config):
        app = FastAPI()
        # Docs routes are scanned, so exclude them like a real app would
        app.add_middleware(
            TopazMiddleware,
            config=config,
            exclude_paths=[r"^/$", r"^/static/.*", r"^/docs", r"^/redoc$", r"^/openapi\.json$"],
        )

        @app.get("/")
        def home():
            return {}

        @app.get("/health")
        @skip_middleware
        def health():
            return {}

        @app.get("/documents")
        def documents():
            return []

        public = APIRouter()

        @public.get("/info")
        def info():
            return {}

        app.include_router(public, prefix="/public", dependencies=[Depends(SkipMiddleware)])
        app.mount("/static", FastAPI())
        return app

    @staticmethod
    def _skipped(routes) -> dict[tuple[str, str], str | None]:
        return {(r["method"], r["path"]): r["skipped"] for r in routes}

    def test_scan_routes_reports_skip_reasons(self, app, config):
        skipped = self._skipped(scan_routes(app, config.policy_path_root))
        assert skipped[("GET", "/")] == "exclude_paths"
        assert skipped[("GET", "/health")] == "marker"
        assert skipped[("GET", "/public/info")] == "marker"
        assert skipped[("GET", "/static")] == "exclude_paths"
        assert skipped[("GET", "/documents")] is None
        for docs_path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            assert skipped[("GET", docs_path)] == "exclude_paths"

    def test_markers_apply_without_middleware(self, config):
        app = FastAPI(**NO_DOCS)

        @app.get("/health")
        @skip_middleware
        def health():
            return {}

        @app.get("/")
        def home():
            return {}

        skipped = self._skipped(scan_routes(app, config.policy_path_root))
        assert skipped == {("GET", "/health"): "marker", ("GET", "/"): None}

    def test_custom_exclude_methods(self, config):
        app = FastAPI(**NO_DOCS)
        app.add_middleware(TopazMiddleware, config=config, exclude_methods=["GET"])

        @app.get("/items")
        def read():
            return []

        @app.post("/items")
        def create():
            return {}

        skipped = self._skipped(scan_routes(app, config.policy_path_root))
        assert skipped == {("GET", "/items"): "exclude_methods", ("POST", "/items"): None}

    def test_rights_matrix_marks_skipped(self, app, config):
        config.default_policy = "myapp.defaults.authenticated"
        by_route = {(r.method, r.route_pattern): r for r in generate_rights_matrix(app, config)}
        health = by_route[("GET", "/health")]
        assert health.resolution_source == "skipped"
        assert health.resolved_policy_path == ""
        assert health.specific_policy_path == "myapp.GET.health"
        assert by_route[("GET", "/documents")].resolution_source == "default"

    def test_openapi_skipped_routes_have_no_policy(self, app, config):
        config.default_policy = "myapp.defaults.authenticated"
        annotate_openapi(app, config)
        paths = app.openapi()["paths"]
        for path in ("/", "/health", "/public/info"):
            assert paths[path]["get"]["x-authz-source"] == "skipped"
            assert "x-authz-policy" not in paths[path]["get"]
        assert paths["/documents"]["get"]["x-authz-policy"] == "myapp.defaults.authenticated"

    def test_policy_diff_lists_skipped_not_missing(self, app, config):
        with tempfile.TemporaryDirectory() as tmpdir:
            # A policy kept for a skipped route is still referenced, not orphaned
            (Path(tmpdir) / "myapp" / "GET").mkdir(parents=True)
            (Path(tmpdir) / "myapp" / "GET" / "health.rego").write_text(
                "package myapp.GET.health\n"
            )
            diff = policy_diff(app, config, tmpdir)

        missing = [m.policy_path for m in diff.missing]
        assert "myapp.GET.health" in diff.skipped
        assert "myapp.GET" in diff.skipped
        assert "myapp.GET.public.info" in diff.skipped
        assert "myapp.GET.static" in diff.skipped
        assert "myapp.GET.health" not in missing + diff.valid
        assert "myapp.GET.health" not in diff.orphaned
        # Only the authorized route is missing (plus the ReBAC myapp.check policy)
        assert sorted(missing) == ["myapp.GET.documents", "myapp.check"]

    @requires_frontend
    def test_frontend_in_skipped_router(self, config, tmp_path):
        (tmp_path / "index.html").write_text("<html></html>")
        app = FastAPI(**NO_DOCS)
        public = APIRouter()
        public.frontend("/", directory=tmp_path)
        app.include_router(public, prefix="/public", dependencies=[Depends(SkipMiddleware)])
        app.frontend("/app", directory=tmp_path)

        skipped = self._skipped(scan_routes(app, config.policy_path_root))
        assert skipped == {("GET", "/public"): "marker", ("GET", "/app"): None}
