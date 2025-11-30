from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://webapp:webapp_pass@postgres/webapp_db"

    # OIDC (Authentik)
    oidc_issuer: str = "http://localhost:9000/application/o/webapp/"
    oidc_client_id: str = "webapp-client"
    oidc_client_secret: str = "change-me"
    oidc_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Topaz
    topaz_url: str = "localhost:8282"
    topaz_ca_cert: str = ""  # Path to CA certificate for TLS
    topaz_tenant_id: str = ""
    topaz_api_key: str = ""
    topaz_policy_root: str = "webapp"
    topaz_policy_instance_name: str = "webapp"
    topaz_policy_instance_label: str = "webapp"

    # Mock Location API
    location_api_url: str = "http://localhost:8001"

    # App settings
    debug: bool = False
    secret_key: str = "change-me-in-production"


settings = Settings()
