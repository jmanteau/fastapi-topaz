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
    cmd_generate_policies,
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


# Sample FastAPI app code for dynamic import testing
TEST_APP_CODE = '''
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
'''


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


class TestMainCLI:
    """Main CLI entry point and argument parsing."""

    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["fastapi-topaz"]):
            result = main()
            assert result == 1

    def test_generate_command(self, temp_app_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("sys.argv", [
                "fastapi-topaz", "generate-policies",
                "--app", temp_app_module,
                "--output", tmpdir,
                "--root", "test",
            ]):
                result = main()
                assert result == 0
