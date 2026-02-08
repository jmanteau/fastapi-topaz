"""Tests for fastapi_topaz._policy module."""
from fastapi_topaz._policy import _policy_path_heuristic, _resolve_policy_path


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
