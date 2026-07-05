from importlib.metadata import PackageNotFoundError, version
from typing import Any

from aserto.client import AuthorizerOptions, Identity, IdentityType, ResourceContext

try:
    __version__ = version("fastapi-topaz")
except PackageNotFoundError:  # editable/dev install without metadata
    __version__ = "0.0.0.dev0"

from ._defaults import Obj
from ._policy import normalize_hyphens
from .audit import AuditEvent, AuditLogger
from .cache import DecisionCache
from .circuit_breaker import CircuitBreaker, CircuitState, CircuitStatus
from .config import HierarchyResult, PolicyGroup, TopazConfig
from .connection_pool import ConnectionPool, PoolStatus
from .dependencies import (
    filter_authorized_resources,
    get_authorized_resource,
    require_policy_allowed,
    require_policy_auto,
    require_rebac_allowed,
    require_rebac_hierarchy,
)
from .middleware import SkipMiddleware, TopazMiddleware, skip_middleware
from .observability import OTelTracing, PrometheusMetrics

# Deprecated aliases served lazily so importing them emits a warning
_DEPRECATED_DEFAULTS = (
    "AuthorizationError",
    "IdentityMapper",
    "StringMapper",
    "ObjectMapper",
    "ResourceMapper",
)


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED_DEFAULTS:
        import warnings

        warnings.warn(
            f"fastapi_topaz.{name} is deprecated and will be removed in 2.0",
            DeprecationWarning,
            stacklevel=2,
        )
        from . import _defaults

        return getattr(_defaults, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Metadata
    "__version__",
    # Core
    "DecisionCache",
    "HierarchyResult",
    "PolicyGroup",
    "TopazConfig",
    "AuthorizationError",
    # Policy utilities
    "normalize_hyphens",
    # Aserto client re-exports
    "AuthorizerOptions",
    "Identity",
    "IdentityType",
    "ResourceContext",
    # Type aliases
    "IdentityMapper",
    "Obj",
    "ObjectMapper",
    "ResourceMapper",
    "StringMapper",
    # Dependencies
    "filter_authorized_resources",
    "get_authorized_resource",
    "require_policy_allowed",
    "require_policy_auto",
    "require_rebac_allowed",
    "require_rebac_hierarchy",
    # Middleware
    "TopazMiddleware",
    "skip_middleware",
    "SkipMiddleware",
    # Circuit Breaker
    "CircuitBreaker",
    "CircuitState",
    "CircuitStatus",
    # Connection Pool
    "ConnectionPool",
    "PoolStatus",
    # Audit Logging
    "AuditLogger",
    "AuditEvent",
    # Observability
    "PrometheusMetrics",
    "OTelTracing",
]
