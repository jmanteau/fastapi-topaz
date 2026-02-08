from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

import httpx
from fastapi_topaz import IdentityType

from app.topaz_integration import (
    identity_provider,
    resource_context_provider,
)


def test_identity_provider_authenticated_user():
    """identity_provider should return identity with sub when user is authenticated."""
    request = MagicMock()
    request.session = {"user": {"sub": "user-123", "email": "test@example.com"}}

    identity = identity_provider(request)

    assert identity.type == IdentityType.IDENTITY_TYPE_MANUAL
    assert identity.value == "user-123"


def test_identity_provider_no_user_in_session():
    """identity_provider should return NONE identity when no user in session."""
    request = MagicMock()
    request.session = {}

    identity = identity_provider(request)

    assert identity.type == IdentityType.IDENTITY_TYPE_NONE


def test_identity_provider_none_user():
    """identity_provider should return NONE identity when user is None."""
    request = MagicMock()
    request.session = {"user": None}

    identity = identity_provider(request)

    assert identity.type == IdentityType.IDENTITY_TYPE_NONE


def test_resource_context_provider_with_path_params():
    """resource_context_provider should include path parameters in context."""
    request = MagicMock()
    request.path_params = {"id": "123", "folder_id": "456"}
    request.session = {}
    request.url.path = "/api/test"

    context = resource_context_provider(request)

    assert context["id"] == "123"
    assert context["folder_id"] == "456"


def test_resource_context_provider_no_path_params():
    """resource_context_provider should handle missing path_params attribute."""
    request = MagicMock(spec=["session", "url"])
    request.session = {}
    request.url.path = "/api/test"

    context = resource_context_provider(request)

    assert context == {}


def test_resource_context_provider_empty_path_params():
    """resource_context_provider should handle empty path params."""
    request = MagicMock()
    request.path_params = {}
    request.session = {}
    request.url.path = "/api/test"

    context = resource_context_provider(request)

    assert context == {}


def test_resource_context_provider_with_user_location():
    """resource_context_provider should add location data when available."""
    request = MagicMock()
    request.path_params = {"id": "123"}
    request.session = {"user": {"sub": "user-123"}}
    request.url.path = "/api/test"

    location_data = {"country": "US", "region": "CA", "city": "San Francisco"}

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = location_data

    with patch("httpx.get", return_value=mock_response) as mock_get:
        context = resource_context_provider(request)

        assert context["id"] == "123"
        assert context["user_location"] == location_data

        # Verify location API was called correctly
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "params" in call_args.kwargs
        assert call_args.kwargs["params"]["user_id"] == "user-123"
        assert call_args.kwargs["timeout"] == 2.0


def test_resource_context_provider_location_api_failure():
    """resource_context_provider should continue without location on API failure."""
    request = MagicMock()
    request.path_params = {"id": "123"}
    request.session = {"user": {"sub": "user-123"}}
    request.url.path = "/api/test"

    with patch("httpx.get", side_effect=httpx.RequestError("Connection failed")):
        context = resource_context_provider(request)

        # Should have path params but no location
        assert context["id"] == "123"
        assert "user_location" not in context


def test_resource_context_provider_location_api_timeout():
    """resource_context_provider should handle location API timeout."""
    request = MagicMock()
    request.path_params = {}
    request.session = {"user": {"sub": "user-123"}}
    request.url.path = "/api/test"

    with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout")):
        context = resource_context_provider(request)

        assert "user_location" not in context


def test_resource_context_provider_location_api_non_200():
    """resource_context_provider should skip location on non-200 status."""
    request = MagicMock()
    request.path_params = {}
    request.session = {"user": {"sub": "user-123"}}
    request.url.path = "/api/test"

    mock_response = Mock()
    mock_response.status_code = 404

    with patch("httpx.get", return_value=mock_response):
        context = resource_context_provider(request)

        assert "user_location" not in context


def test_resource_context_provider_no_authenticated_user():
    """resource_context_provider should skip location API when no user."""
    request = MagicMock()
    request.path_params = {"id": "123"}
    request.session = {}
    request.url.path = "/api/test"

    with patch("httpx.get") as mock_get:
        context = resource_context_provider(request)

        assert context["id"] == "123"
        assert "user_location" not in context
        mock_get.assert_not_called()


def test_topaz_config_has_decision_cache():
    """topaz_config should be configured with DecisionCache."""
    from app.topaz_integration import topaz_config

    assert topaz_config.decision_cache is not None


def test_topaz_config_has_circuit_breaker():
    """topaz_config should be configured with CircuitBreaker."""
    from app.topaz_integration import topaz_config

    assert topaz_config.circuit_breaker is not None


def test_topaz_config_has_audit_logger():
    """topaz_config should be configured with AuditLogger."""
    from app.topaz_integration import topaz_config

    assert topaz_config.audit_logger is not None
