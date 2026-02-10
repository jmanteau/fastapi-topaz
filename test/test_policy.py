"""Tests for fastapi_topaz._policy module."""
from fastapi_topaz._policy import (
    _policy_path_heuristic,
    _resolve_policy_path,
    normalize_hyphens,
)


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
