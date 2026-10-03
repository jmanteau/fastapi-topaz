"""
Tests for CLI commands.

The CLI provides commands for policy generation, validation, and documentation.
Commands are designed to work with any FastAPI application via module:attribute syntax.

Test organization:
- TestImportApp: Dynamic app importing from module:attribute strings
- TestGeneratePolicies: generate-policies command behavior
- TestPolicyDiff: policy-diff command for detecting drift
- TestPolicyMap: policy-map command for route documentation
- TestMainCLI: Main entry point and argument parsing
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI

from fastapi_topaz.cli import (
    cmd_check,
    cmd_generate_policies,
    cmd_generate_rights_matrix,
    cmd_policy_diff,
    cmd_policy_map,
    import_app,
    main,
)


@dataclass
class MockArgs:
    """Mock argparse.Namespace for testing CLI commands."""

    app: str
    output: str | None = None
    config: str | None = None
    root: str | None = None
    dry_run: bool = False
    overwrite: bool = False
    policies: str | None = None
    strict: bool = False
    format: str = "text"
    method: str = "GET"
    path: str = "/"
    live: bool = False
    identity: str | None = None


# Sample FastAPI app code for dynamic import testing
TEST_APP_CODE = """
from fastapi import FastAPI
app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

@app.get("/items")
def list_items():
    return []

@app.post("/items")
def create_item():
    return {}

@app.get("/items/{id}")
def get_item(id: int):
    return {}
"""


ROUTER_APP_CODE = """
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter(prefix="/folders")

@router.get("/{folder_id}")
def get_folder(folder_id: int):
    return {}

app.include_router(router)
"""


@pytest.fixture
def temp_app_module(tmp_path):
    """Create a temporary module with a FastAPI app."""
    module_dir = tmp_path / "testmod"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text("")
    (module_dir / "main.py").write_text(TEST_APP_CODE)

    # Add to path
    sys.path.insert(0, str(tmp_path))
    yield "testmod.main:app"
    sys.path.remove(str(tmp_path))


class TestImportApp:
    """Dynamic FastAPI app importing from module:attribute strings."""

    def test_import_valid_app(self, temp_app_module):
        app = import_app(temp_app_module)
        assert isinstance(app, FastAPI)

    def test_import_invalid_format(self):
        with pytest.raises(SystemExit):
            import_app("invalid_format_no_colon")

    def test_import_nonexistent_module(self):
        with pytest.raises(SystemExit):
            import_app("nonexistent.module:app")


class TestGeneratePolicies:
    """generate-policies command: creates Rego policy skeletons from routes."""

    def test_generates_policies(self, temp_app_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MockArgs(app=temp_app_module, output=tmpdir, root="testapp")
            result = cmd_generate_policies(args)
            assert result == 0

            # Check files were created
            output_path = Path(tmpdir)
            rego_files = list(output_path.rglob("*.rego"))
            assert len(rego_files) > 0

    def test_existing_files_skipped_without_overwrite(self, temp_app_module, tmp_path, capsys):
        args = MockArgs(app=temp_app_module, output=str(tmp_path), root="testapp")
        cmd_generate_policies(args)
        target = next(tmp_path.rglob("*.rego"))
        generated = target.read_text()
        target.write_text("# custom policy\n")
        capsys.readouterr()

        assert cmd_generate_policies(args) == 0
        assert target.read_text() == "# custom policy\n"
        assert "SKIP" in capsys.readouterr().out

        args.overwrite = True
        assert cmd_generate_policies(args) == 0
        assert target.read_text() == generated
        assert "SKIP" not in capsys.readouterr().out

    def test_dry_run(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp", dry_run=True)
        result = cmd_generate_policies(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Would generate" in captured.out


class TestPolicyDiff:
    """policy-diff command: compares routes against existing policies."""

    def test_detects_missing(self, temp_app_module, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            args = MockArgs(app=temp_app_module, policies=tmpdir, root="testapp")
            result = cmd_policy_diff(args)
            # Should return 1 due to missing policies
            assert result == 1

            captured = capsys.readouterr()
            assert "Missing policies" in captured.out

    def test_all_valid(self, temp_app_module, capsys):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Generate policies first
            gen_args = MockArgs(app=temp_app_module, output=tmpdir, root="testapp")
            cmd_generate_policies(gen_args)

            # Now diff
            args = MockArgs(app=temp_app_module, policies=tmpdir, root="testapp")
            result = cmd_policy_diff(args)
            assert result == 0

            captured = capsys.readouterr()
            assert "All policies are in sync" in captured.out


class TestPolicyMap:
    """policy-map command: generates route-to-policy mapping documentation."""

    def test_text_format(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp", format="text")
        result = cmd_policy_map(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "/items" in captured.out
        assert "testapp.GET.items" in captured.out

    def test_markdown_format(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp", format="markdown")
        result = cmd_policy_map(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "| Route |" in captured.out
        assert "| /items |" in captured.out


class TestGenerateRightsMatrix:
    """generate-rights-matrix command: resolves every route through the chain."""

    def test_summary_without_output(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp")
        result = cmd_generate_rights_matrix(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Rights matrix: 3 routes" in captured.out
        assert "generated: 3" in captured.out
        assert "Written to" not in captured.out

    def test_writes_markdown_output(self, temp_app_module, capsys, tmp_path):
        output_file = tmp_path / "matrix.md"
        args = MockArgs(app=temp_app_module, root="testapp", output=str(output_file))
        result = cmd_generate_rights_matrix(args)
        assert result == 0

        captured = capsys.readouterr()
        assert f"Written to {output_file}" in captured.out

        content = output_file.read_text()
        assert "# Rights Matrix — testapp" in content
        assert "| GET | /items | testapp.GET.items | generated | N |" in content
        assert "Total routes: 3" in content

    def test_explicit_policies_counted(self, temp_app_module, capsys, tmp_path):
        policies_dir = tmp_path / "policies"
        gen_args = MockArgs(app=temp_app_module, output=str(policies_dir), root="testapp")
        cmd_generate_policies(gen_args)
        capsys.readouterr()

        args = MockArgs(app=temp_app_module, root="testapp", policies=str(policies_dir))
        result = cmd_generate_rights_matrix(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "explicit: 3" in captured.out

    def test_main_entry_point(self, temp_app_module, capsys):
        with patch(
            "sys.argv",
            [
                "fastapi-topaz",
                "generate-rights-matrix",
                "--app",
                temp_app_module,
                "--root",
                "testapp",
            ],
        ):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        assert "Rights matrix: 3 routes" in captured.out


class TestMainCLI:
    """Main CLI entry point and argument parsing."""

    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["fastapi-topaz"]):
            result = main()
            assert result == 1

    def test_generate_command(self, temp_app_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "sys.argv",
                [
                    "fastapi-topaz",
                    "generate-policies",
                    "--app",
                    temp_app_module,
                    "--output",
                    tmpdir,
                    "--root",
                    "test",
                ],
            ):
                result = main()
                assert result == 0


class TestCheckCommand:
    """check command: resolves the policy for a concrete method + URL."""

    def test_offline_generated_resolution(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp", method="GET", path="/items/7")
        result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Route:    GET /items/{id}" in captured.out
        assert "Policy:   testapp.GET.items.__id" in captured.out
        assert "Source:   generated" in captured.out
        assert "'id': '7'" in captured.out

    def test_offline_explicit_resolution(self, temp_app_module, capsys, tmp_path):
        policies_dir = tmp_path / "policies"
        gen_args = MockArgs(app=temp_app_module, output=str(policies_dir), root="testapp")
        cmd_generate_policies(gen_args)
        capsys.readouterr()

        args = MockArgs(
            app=temp_app_module,
            root="testapp",
            method="GET",
            path="/items",
            policies=str(policies_dir),
        )
        result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Policy:   testapp.GET.items" in captured.out
        assert "Source:   explicit" in captured.out

    def test_resolves_included_router_route(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "routerapp.py").write_text(ROUTER_APP_CODE)
        monkeypatch.syspath_prepend(str(tmp_path))

        args = MockArgs(app="routerapp:app", root="testapp", method="GET", path="/folders/7")
        result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Route:    GET /folders/{folder_id}" in captured.out
        assert "Policy:   testapp.GET.folders.__folder_id" in captured.out
        assert "'folder_id': '7'" in captured.out

    @pytest.mark.skipif(not hasattr(FastAPI, "frontend"), reason="FastAPI without frontend routes")
    def test_resolves_frontend_route(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "dist").mkdir()
        (tmp_path / "frontendapp.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            f"app.frontend('/app', directory={str(tmp_path / 'dist')!r})\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        args = MockArgs(app="frontendapp:app", root="testapp", method="GET", path="/app/x.js")
        result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Route:    GET /app" in captured.out
        assert "Policy:   testapp.GET.app" in captured.out

    def test_resolves_mount(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "mountapp.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\napp.mount('/sub', FastAPI())\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        args = MockArgs(app="mountapp:app", root="testapp", method="GET", path="/sub/x")
        result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Policy:   testapp.GET.sub" in captured.out

    def test_unmatched_route_errors(self, temp_app_module, capsys):
        args = MockArgs(app=temp_app_module, root="testapp", method="GET", path="/nonexistent")
        result = cmd_check(args)
        assert result == 2

        captured = capsys.readouterr()
        assert "no route matches GET /nonexistent" in captured.out

    def test_live_allowed(self, temp_app_module, capsys):
        from unittest.mock import AsyncMock

        args = MockArgs(
            app=temp_app_module,
            root="testapp",
            method="GET",
            path="/items/7",
            live=True,
            identity="user-1",
        )
        with patch(
            "fastapi_topaz._client.SharedAuthorizerClient.decisions",
            new=AsyncMock(return_value={"allowed": True}),
        ) as mock_decisions:
            result = cmd_check(args)
        assert result == 0

        captured = capsys.readouterr()
        assert "Decision: allowed" in captured.out
        kwargs = mock_decisions.call_args.kwargs
        assert kwargs["policy_path"] == "testapp.GET.items.__id"
        assert kwargs["identity"].value == "user-1"
        assert kwargs["resource_context"] == {"id": "7"}

    def test_live_denied(self, temp_app_module, capsys):
        from unittest.mock import AsyncMock

        args = MockArgs(app=temp_app_module, root="testapp", method="GET", path="/items", live=True)
        with patch(
            "fastapi_topaz._client.SharedAuthorizerClient.decisions",
            new=AsyncMock(return_value={"allowed": False}),
        ):
            result = cmd_check(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Decision: denied" in captured.out

    def test_live_error(self, temp_app_module, capsys):
        from unittest.mock import AsyncMock

        args = MockArgs(app=temp_app_module, root="testapp", method="GET", path="/items", live=True)
        with patch(
            "fastapi_topaz._client.SharedAuthorizerClient.decisions",
            new=AsyncMock(side_effect=ConnectionError("unreachable")),
        ):
            result = cmd_check(args)
        assert result == 2

        captured = capsys.readouterr()
        assert "authorizer call failed" in captured.out
        assert "ConnectionError" in captured.out

    def test_main_entry_point(self, temp_app_module, capsys):
        with patch(
            "sys.argv",
            [
                "fastapi-topaz",
                "check",
                "--app",
                temp_app_module,
                "--method",
                "GET",
                "--path",
                "/items",
                "--root",
                "testapp",
            ],
        ):
            result = main()
            assert result == 0

        captured = capsys.readouterr()
        assert "Policy:   testapp.GET.items" in captured.out


CONFIG_MODULE_CODE = '''
from aserto.client import AuthorizerOptions, Identity, IdentityType
from fastapi_topaz import PolicyGroup, TopazConfig

config = TopazConfig(
    authorizer_options=AuthorizerOptions(url="localhost:8282"),
    policy_path_root="cfgapp",
    identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_NONE, value=""),
    policy_instance_name="cfgapp",
    default_policy="cfgapp.defaults.open",
    policy_groups=[PolicyGroup(url_pattern=r"^/items$", policy_path="cfgapp.items")],
)
'''


@pytest.fixture
def temp_config_module(tmp_path):
    """Module exposing both an app and a TopazConfig with a resolution chain."""
    module_dir = tmp_path / "cfgmod"
    module_dir.mkdir()
    (module_dir / "__init__.py").write_text("")
    (module_dir / "main.py").write_text(TEST_APP_CODE + CONFIG_MODULE_CODE)

    sys.path.insert(0, str(tmp_path))
    yield "cfgmod.main"
    sys.path.remove(str(tmp_path))


class TestImportConfig:
    """Dynamic TopazConfig importing from module:attribute strings."""

    def test_import_valid_config(self, temp_config_module):
        from fastapi_topaz.cli import import_config

        config = import_config(f"{temp_config_module}:config")
        assert config.policy_path_root == "cfgapp"

    def test_import_invalid_config_exits(self):
        from fastapi_topaz.cli import import_config

        with pytest.raises(SystemExit):
            import_config("nonexistent.module:config")

    def test_command_uses_explicit_config(self, temp_config_module, capsys):
        args = MockArgs(
            app=f"{temp_config_module}:app",
            config=f"{temp_config_module}:config",
            path="/items",
        )
        result = cmd_check(args)
        captured = capsys.readouterr()

        assert result == 0
        # /items matches the config's PolicyGroup
        assert "cfgapp.items" in captured.out
        assert "group" in captured.out


class TestPolicyDiffVerboseOutput:
    """policy-diff prints orphaned, group-covered, and default-covered sections."""

    def test_group_default_and_orphan_sections(self, temp_config_module, capsys, tmp_path):
        policies = tmp_path / "policies"
        policies.mkdir()
        (policies / "cfgapp.items.rego").write_text("package cfgapp.items\nallowed := false\n")
        (policies / "cfgapp.defaults.open.rego").write_text(
            "package cfgapp.defaults.open\nallowed := true\n"
        )
        (policies / "cfgapp.stray.rego").write_text("package cfgapp.stray\nallowed := false\n")

        args = MockArgs(
            app=f"{temp_config_module}:app",
            config=f"{temp_config_module}:config",
            policies=str(policies),
        )
        result = cmd_policy_diff(args)
        captured = capsys.readouterr()

        assert result == 0
        assert "Orphaned policies (1)" in captured.out
        assert "cfgapp.stray" in captured.out
        assert "Covered by policy group" in captured.out
        assert "Covered by default policy" in captured.out


class TestCliReviewFixes:
    """CLI regressions: cwd imports, import exit codes, policy-map --config."""

    def test_main_imports_app_from_cwd(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "cwd_app_mod.py").write_text(TEST_APP_CODE)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "path", [p for p in sys.path if p not in ("", str(tmp_path))])
        monkeypatch.setattr(
            sys, "argv", ["fastapi-topaz", "policy-map", "--app", "cwd_app_mod:app"]
        )

        assert main() == 0
        assert "app.GET.items" in capsys.readouterr().out

    def test_import_app_failure_exits_2(self):
        with pytest.raises(SystemExit) as exc:
            import_app("nonexistent.module:app")
        assert exc.value.code == 2

    def test_import_config_failure_exits_2(self):
        from fastapi_topaz.cli import import_config

        with pytest.raises(SystemExit) as exc:
            import_config("nonexistent.module:config")
        assert exc.value.code == 2

    def test_policy_map_uses_config_normalizer(self, tmp_path, capsys):
        module_dir = tmp_path / "pmapmod"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "main.py").write_text(
            "from aserto.client import AuthorizerOptions, Identity, IdentityType\n"
            "from fastapi import FastAPI\n"
            "from fastapi_topaz import TopazConfig, normalize_hyphens\n"
            "app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)\n"
            "@app.get('/aircraft-programs')\n"
            "def programs():\n"
            "    return []\n"
            "config = TopazConfig(\n"
            "    authorizer_options=AuthorizerOptions(url='localhost:8282'),\n"
            "    policy_path_root='cfg',\n"
            "    identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_NONE, value=''),\n"
            "    policy_instance_name='cfg',\n"
            "    policy_path_normalizer=normalize_hyphens,\n"
            ")\n"
        )
        sys.path.insert(0, str(tmp_path))
        try:
            args = MockArgs(app="pmapmod.main:app", config="pmapmod.main:config")
            assert cmd_policy_map(args) == 0
        finally:
            sys.path.remove(str(tmp_path))

        out = capsys.readouterr().out
        assert "cfg.GET.aircraft_programs" in out
        assert "cfg.GET.aircraft-programs" not in out


SKIP_APP_CODE = """
from fastapi import FastAPI
from fastapi_topaz import TopazMiddleware, TopazConfig, skip_middleware
from aserto.client import AuthorizerOptions, Identity, IdentityType

config = TopazConfig(
    authorizer_options=AuthorizerOptions(url="localhost:8282"),
    policy_path_root="testapp",
    identity_provider=lambda r: Identity(type=IdentityType.IDENTITY_TYPE_NONE, value=""),
    policy_instance_name="test",
)
app = FastAPI()
app.add_middleware(TopazMiddleware, config=config, exclude_paths=[r"^/public/.*"])

@app.get("/health")
@skip_middleware
def health():
    return {}

@app.get("/public/info")
def info():
    return {}

@app.get("/items")
def items():
    return []
"""


class TestSkippedRoutesCli:
    """check and policy-diff report routes TopazMiddleware skips."""

    @pytest.fixture
    def skip_app(self, tmp_path, monkeypatch):
        (tmp_path / "skipapp.py").write_text(SKIP_APP_CODE)
        monkeypatch.syspath_prepend(str(tmp_path))
        return "skipapp:app"

    @pytest.mark.parametrize("path", ["/health", "/public/info"])
    def test_check_reports_skipped(self, skip_app, capsys, path):
        result = cmd_check(MockArgs(app=skip_app, root="testapp", method="GET", path=path))
        assert result == 0
        out = capsys.readouterr().out
        assert "Source:   skipped" in out
        assert "not authorized by TopazMiddleware" in out

    def test_check_live_skipped_does_not_evaluate(self, skip_app, capsys):
        from unittest.mock import AsyncMock

        args = MockArgs(app=skip_app, root="testapp", method="GET", path="/health", live=True)
        with patch(
            "fastapi_topaz._client.SharedAuthorizerClient.decisions", new=AsyncMock()
        ) as decisions:
            result = cmd_check(args)
        assert result == 0
        decisions.assert_not_called()
        assert "no live evaluation" in capsys.readouterr().out

    def test_policy_diff_lists_skipped(self, skip_app, capsys, tmp_path):
        result = cmd_policy_diff(MockArgs(app=skip_app, root="testapp", policies=str(tmp_path)))
        out = capsys.readouterr().out
        assert result == 1  # testapp.GET.items is still missing
        assert "Skipped by TopazMiddleware (2):" in out
        assert "testapp.GET.health" in out.split("Skipped by TopazMiddleware")[1]
        missing_section = out.split("Missing policies")[1].split("\n\n")[0]
        assert "testapp.GET.health" not in missing_section
        assert "2 skipped" in out
