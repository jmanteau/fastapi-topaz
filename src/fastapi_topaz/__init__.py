from aserto.client import AuthorizerOptions, Identity, IdentityType, ResourceContext

from ._defaults import (
    AuthorizationError,
    IdentityMapper,
    Obj,
    ObjectMapper,
    ResourceMapper,
    StringMapper,
)
from ._policy import normalize_hyphens
from .audit import AuditEvent, AuditLogger
from .cache import DecisionCache
from .circuit_breaker import CircuitBreaker, CircuitState, CircuitStatus
from .config import HierarchyResult, TopazConfig
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

__all__ = [
    # Core
    "DecisionCache",
    "HierarchyResult",
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
