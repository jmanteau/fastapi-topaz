"""Tests for fastapi_topaz._policy module."""
import os
import tempfile
from pathlib import Path

from fastapi_topaz._policy import (
    _compile_policy_groups,
    _policy_path_heuristic,
    _resolve_policy_path,
    normalize_hyphens,
    scan_policy_files,
)
from fastapi_topaz.config import PolicyGroup


class TestPolicyPathHeuristic:
    """Tests for _policy_path_heuristic function."""

    def test_root_path(self):
        """Test that "/" returns empty string."""
        assert _policy_path_heuristic("/") == ""

    def test_simple_path(self):
        """Test that "/docs" returns ".docs"."""
        assert _policy_path_heuristic("/docs") == ".docs"

    def test_path_with_parameter(self):
        """Test that "/docs/{id}" returns ".docs.__id"."""
        assert _policy_path_heuristic("/docs/{id}") == ".docs.__id"

    def test_nested_path_with_parameters(self):
        """Test that "/users/{uid}/items/{iid}" returns ".users.__uid.items.__iid"."""
        assert _policy_path_heuristic("/users/{uid}/items/{iid}") == ".users.__uid.items.__iid"


class TestResolvePolicyPath:
    """Tests for _resolve_policy_path function."""

    def test_full_policy_path(self):
        """Test that "myapp" + "GET" + "/docs/{id}" returns "myapp.GET.docs.__id"."""
        result = _resolve_policy_path("myapp", "GET", "/docs/{id}")
        assert result == "myapp.GET.docs.__id"

    def test_root_path_resolution(self):
        """Test policy path resolution with root path."""
        result = _resolve_policy_path("myapp", "POST", "/")
        assert result == "myapp.POST"

    def test_method_variations(self):
        """Test policy path resolution with different HTTP methods."""
        assert _resolve_policy_path("api", "GET", "/users") == "api.GET.users"
        assert _resolve_policy_path("api", "POST", "/users") == "api.POST.users"
        assert _resolve_policy_path("api", "PUT", "/users/{id}") == "api.PUT.users.__id"

    def test_normalizer_none_by_default(self):
        """No normalizer by default, path unchanged."""
        result = _resolve_policy_path("app", "GET", "/aircraft-programs")
        assert result == "app.GET.aircraft-programs"

    def test_normalizer_replaces_hyphens(self):
        """/aircraft-programs becomes app.GET.aircraft_programs with normalizer."""
        result = _resolve_policy_path(
            "app", "GET", "/aircraft-programs",
            policy_path_normalizer=normalize_hyphens,
        )
        assert result == "app.GET.aircraft_programs"

    def test_normalizer_preserves_params(self):
        """/user-docs/{user-id} with normalizer handles both hyphens and params."""
        result = _resolve_policy_path(
            "app", "GET", "/user-docs/{user-id}",
            policy_path_normalizer=normalize_hyphens,
        )
        assert result == "app.GET.user_docs.__user_id"


class TestNormalizeHyphens:
    """Tests for the normalize_hyphens built-in normalizer."""

    def test_replaces_hyphens(self):
        """Should replace all hyphens with underscores."""
        assert normalize_hyphens("app.GET.aircraft-programs") == "app.GET.aircraft_programs"

    def test_no_hyphens(self):
        """Should return unchanged string when no hyphens present."""
        assert normalize_hyphens("app.GET.documents") == "app.GET.documents"

    def test_multiple_hyphens(self):
        """Should replace all hyphens in the path."""
        assert normalize_hyphens("app.GET.my-long-path-name") == "app.GET.my_long_path_name"

    def test_preserves_dots_and_underscores(self):
        """Should not modify dots or existing underscores."""
        assert normalize_hyphens("app.GET.my_path.__param-name") == "app.GET.my_path.__param_name"


class TestScanPolicyFiles:
    """Tests for scan_policy_files function."""

    def test_scan_policy_files_basic(self):
        """Should scan rego files and return policy paths."""
        import tempfile
        from pathlib import Path

        from fastapi_topaz._policy import scan_policy_files

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test rego files
            p1 = Path(tmpdir) / "myapp/GET/docs.rego"
            p1.parent.mkdir(parents=True, exist_ok=True)
            p1.write_text("package myapp.GET.docs\n")

            p2 = Path(tmpdir) / "myapp/POST/docs.rego"
            p2.parent.mkdir(parents=True, exist_ok=True)
            p2.write_text("package myapp.POST.docs\n")

            result = scan_policy_files(tmpdir)
            assert result == {"myapp.GET.docs", "myapp.POST.docs"}

    def test_scan_policy_files_nested(self):
        """Should handle deeply nested directories."""
        import tempfile
        from pathlib import Path

        from fastapi_topaz._policy import scan_policy_files

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            p = Path(tmpdir) / "admin/users.rego"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("package admin.users\n")

            result = scan_policy_files(tmpdir)
            assert result == {"admin.users"}

    def test_scan_policy_files_empty_dir(self):
        """Should return empty set for directory with no rego files."""
        import tempfile

        from fastapi_topaz._policy import scan_policy_files

        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_policy_files(tmpdir)
            assert result == set()

    def test_scan_policy_files_missing_dir(self):
        """Should return empty set when directory does not exist."""
        result = scan_policy_files("/nonexistent/directory/path")
        assert result == set()

    def test_scan_policy_files_none_input(self):
        """scan_policy_files(None) returns empty set."""
        result = scan_policy_files(None)
        assert result == set()

    def test_scan_policy_files_symlink_escape(self):
        """Symlinks pointing outside the policies dir are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            policies_dir = Path(tmpdir) / "policies"
            policies_dir.mkdir()

            # Create a rego file outside the policies dir
            outside_dir = Path(tmpdir) / "outside"
            outside_dir.mkdir()
            outside_file = outside_dir / "secret.rego"
            outside_file.write_text("package secret\n")

            # Create a symlink inside policies dir pointing outside
            symlink_path = policies_dir / "escape.rego"
            try:
                os.symlink(outside_file, symlink_path)
            except OSError:
                # Symlinks may not be supported on all platforms
                return

            result = scan_policy_files(policies_dir)
            # The symlinked file should be skipped
            assert "escape" not in result


class TestCompilePolicyGroups:
    """Tests for _compile_policy_groups."""

    def test_compile_valid_groups(self):
        """Valid groups compile without error."""
        groups = [
            PolicyGroup(url_pattern=r"^/admin/", policy_path="app.admin"),
            PolicyGroup(url_pattern=r"^/api/v\d+/", policy_path="app.api"),
        ]
        compiled = _compile_policy_groups(groups)
        assert len(compiled) == 2
        assert compiled[0][1] == "app.admin"
        assert compiled[1][1] == "app.api"

    def test_compile_invalid_regex_raises(self):
        """Invalid regex raises ValueError."""
        groups = [PolicyGroup(url_pattern="(?P<bad", policy_path="app.bad")]
        import pytest
        with pytest.raises(ValueError, match="Invalid regex"):
            _compile_policy_groups(groups)

    def test_compile_empty_groups(self):
        """Empty group list returns empty list."""
        assert _compile_policy_groups([]) == []
