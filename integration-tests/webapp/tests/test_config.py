from __future__ import annotations

import os
from unittest.mock import patch

from app.config import Settings


def test_settings_default_values():
    """Settings should have sensible defaults."""
    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql://webapp:webapp_pass@postgres/webapp_db"
    assert settings.oidc_issuer == "http://localhost:9000/application/o/webapp/"
    assert settings.oidc_client_id == "webapp-client"
    assert settings.oidc_redirect_uri == "http://localhost:8000/auth/callback"
    assert settings.topaz_url == "http://localhost:8282"
    assert settings.location_api_url == "http://localhost:8001"
    assert settings.debug is False
    assert settings.secret_key == "change-me-in-production"


def test_settings_from_environment_variables():
    """Settings should override defaults from environment variables."""
    with patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://custom:pass@localhost/custom_db",
            "OIDC_ISSUER": "https://custom-issuer.com/",
            "OIDC_CLIENT_ID": "custom-client",
            "OIDC_CLIENT_SECRET": "custom-secret",
            "TOPAZ_URL": "https://custom-topaz.com",
            "DEBUG": "true",
            "SECRET_KEY": "custom-secret-key",
        },
        clear=False,
    ):
        settings = Settings(_env_file=None)

        assert settings.database_url == "postgresql://custom:pass@localhost/custom_db"
        assert settings.oidc_issuer == "https://custom-issuer.com/"
        assert settings.oidc_client_id == "custom-client"
        assert settings.oidc_client_secret == "custom-secret"
        assert settings.topaz_url == "https://custom-topaz.com"
        assert settings.debug is True
        assert settings.secret_key == "custom-secret-key"


def test_settings_topaz_configuration():
    """Settings should handle Topaz configuration correctly."""
    with patch.dict(
        os.environ,
        {
            "TOPAZ_TENANT_ID": "tenant-123",
            "TOPAZ_API_KEY": "api-key-456",
            "TOPAZ_POLICY_ROOT": "custom-policy",
            "TOPAZ_POLICY_INSTANCE_NAME": "custom-instance",
            "TOPAZ_POLICY_INSTANCE_LABEL": "custom-label",
        },
        clear=False,
    ):
        settings = Settings(_env_file=None)

        assert settings.topaz_tenant_id == "tenant-123"
        assert settings.topaz_api_key == "api-key-456"
        assert settings.topaz_policy_root == "custom-policy"
        assert settings.topaz_policy_instance_name == "custom-instance"
        assert settings.topaz_policy_instance_label == "custom-label"


def test_settings_location_api_url():
    """Settings should configure location API URL."""
    with patch.dict(
        os.environ,
        {"LOCATION_API_URL": "http://custom-location:9999"},
        clear=False,
    ):
        settings = Settings(_env_file=None)

        assert settings.location_api_url == "http://custom-location:9999"


def test_settings_extra_fields_ignored():
    """Settings should ignore extra environment variables."""
    with patch.dict(
        os.environ,
        {"UNKNOWN_FIELD": "some-value", "ANOTHER_UNKNOWN": "another-value"},
        clear=False,
    ):
        settings = Settings(_env_file=None)
        # Should not raise validation error due to extra="ignore"
        assert hasattr(settings, "database_url")


def test_settings_oidc_redirect_uri():
    """Settings should handle OIDC redirect URI."""
    with patch.dict(
        os.environ,
        {"OIDC_REDIRECT_URI": "https://app.example.com/auth/callback"},
        clear=False,
    ):
        settings = Settings(_env_file=None)

        assert settings.oidc_redirect_uri == "https://app.example.com/auth/callback"
