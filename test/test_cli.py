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
app = FastAPI()

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
