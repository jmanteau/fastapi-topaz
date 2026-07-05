# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Circuit breaker now detects gRPC errors (`grpc.RpcError`, including `grpc.aio.AioRpcError`) as failures based on their status code, so the breaker actually trips during Topaz outages; previously the default `failure_exceptions` never matched gRPC errors
- Authorization checks now reuse a single long-lived gRPC channel instead of opening (and never closing) a new secure channel per request, eliminating a channel and file-descriptor leak
- Middleware now logs authorization infrastructure errors with full tracebacks and emits an audit event with `reason="authorizer_error"` instead of silently converting every failure into a 403; identity-provider exceptions are logged instead of being swallowed
- Cache hits now record the actual cached decision in metrics and tracing; previously every cache hit was labeled `decision="denied"` regardless of the cached value
- Middleware authorization checks are now attributed to `source="middleware"` in metrics, cache counters, and tracing spans, matching the audit log; previously they were mislabeled as `source="dependency"`
- `scan_routes` (and therefore `generate-policies`, `policy-diff`, and `generate-rights-matrix`) now applies the configured `policy_path_normalizer`, so generated policies match what the runtime evaluates instead of drifting on e.g. hyphenated paths
- `policy_diff` no longer reports `default_policy` and `PolicyGroup` policy files as orphaned, so a correctly configured resolution chain passes `policy-diff --strict`
- `TopazConfig` and `ConnectionPool` now create their asyncio primitives lazily on first use instead of at construction, fixing "attached to a different loop" errors on Python 3.9 when the config is created at module import time

### Added

- `TopazConfig(check_timeout=...)`: gRPC deadline in seconds applied to each authorization call (default 5.0), so a hung Topaz no longer hangs requests forever
- `TopazMiddleware(on_error=...)`: opt-in `"unavailable"` mode returns 503 instead of the fail-closed 403 default when the authorization check itself fails
- `CircuitBreaker(failure_grpc_codes=...)`: set of gRPC status codes treated as failures (default: UNAVAILABLE, DEADLINE_EXCEEDED, UNKNOWN, INTERNAL, RESOURCE_EXHAUSTED); policy errors such as INVALID_ARGUMENT do not trip the breaker
- `AuditLogger.log_decision(reason=...)`: optional reason field forwarded to the audit event
- GitHub Actions CI workflow running lint, typecheck, and tests across Python 3.9-3.13 on pushes to main and pull requests

### Deprecated

- `ConnectionPool`: has no effect on authorization calls (they use the shared channel) and will be removed in 2.0; it now closes underlying channels when discarding connections and emits a `DeprecationWarning` on `configure()`
- `TopazConfig.create_client()`: no longer used internally; each call opens a new channel the caller must close; will be removed in 2.0

## [1.1.0]

### Added

- Policy resolution chain (`PolicyGroup`, `default_policy`, `policies_dir`) so multiple routes can share a single policy instead of requiring one `.rego` file per route
- `generate-rights-matrix` CLI command to visualise which policy each route resolves to, useful for auditing and onboarding
- `policy_resolution_source` in audit events to trace how each authorization decision was routed
- `policy_diff` now understands the resolution chain, avoiding false "missing" reports for routes covered by a group or default policy
- Early validation of `PolicyGroup` regex patterns and startup warnings for missing policy files to catch misconfigurations before they hit production

### Changed

- Integration test webapp now uses the resolution chain, replacing per-route dependency injections with middleware-level policy routing
- E2E / integration Make targets fail fast with clear errors when infrastructure is not running

## [1.0.1] - 2026-02-10

### Added

- `policy_path_normalizer` optional callback on `TopazConfig` to transform generated policy paths (e.g., replace hyphens with underscores for valid Rego identifiers)
- `normalize_hyphens()` built-in normalizer for the common hyphen-to-underscore case

## [1.0.0] - 2026-02-08

### Changed

#### Module Restructuring
- Extracted `TopazConfig`, `HierarchyResult`, and `_resolve_id_source` from `dependencies.py` into new `config.py` module
- Extracted `DecisionCache` and `CacheEntry` from `dependencies.py` into new `cache.py` module
- Extracted shared `_policy_path_heuristic` and `_resolve_policy_path` into new `_policy.py` module, eliminating duplication between `dependencies.py` and `codegen.py`
- `dependencies.py` reduced from ~850 lines to ~19 lines (thin facade re-exporting from new modules)
- All public API re-exports preserved in `__init__.py` - user-facing imports unchanged

#### TopazConfig Improvements
- Stale cache methods (`_get_stale_cached`, `_set_stale_cached`) are now async with a dedicated `asyncio.Lock` for thread safety
- Semaphore is now eagerly initialized at construction (previously lazy)

#### DecisionCache Improvements
- Added LRU behavior: cache reads re-insert entries to mark them as recently used

#### Middleware Improvements
- `TopazMiddleware` now injects `path_params` into the ASGI scope so `Request.path_params` works correctly in `identity_provider` and `resource_context_provider` callbacks
- Added error logging with exception type and message on authorization check failures

#### Observability Fixes
- Fixed redundant if/else in `OTelTracing.end_auth_span` (both branches were identical) - replaced with a single `span.set_attribute` for denied status
- Reformatted prometheus_client import for readability

#### Integration Test Webapp
- Added `TopazMiddleware` with route exclusions and `@skip_middleware` on health endpoint
- Added `DecisionCache`, `CircuitBreaker`, and `AuditLogger` to Topaz config
- Added async lifecycle management via `asynccontextmanager`
- Switched from `require_policy_allowed` to `require_policy_auto` for auto-generated policy paths
- Replaced `sys.stderr.write` debug logging with proper `logging.debug` calls
- Upgraded Pydantic models to v2 style (`model_config = ConfigDict(from_attributes=True)`)
- Simplified `get_authorized_resource` fetcher signatures (`request` only, removed `db` parameter)

#### Policies
- Replaced monolithic policy files (`displaystate.rego`, `document.rego`, `folder.rego`) with per-route policy files (17 individual `.rego` files matching route patterns, e.g. `GET_api_documents.rego`, `POST_api_documents.rego`)
- Added ReBAC rule to allow `can_read` when document is not found (lets route handler return 404 instead of 403)

#### Documentation
- Rewrote Getting Started tutorial to showcase all 7 authorization patterns: middleware, policy auto, ReBAC, `check_relations`, `get_authorized_resource`, `filter_authorized_resources`, and hierarchy checks
- Tutorial now includes `DecisionCache`, `CircuitBreaker`, and `AuditLogger` setup
- Updated repository URLs from `opcr-io/topaz` to `jmanteau/fastapi-topaz`
- Fixed markdown table formatting in troubleshooting guide

#### Tests
- Added dedicated test files: `test_cache.py`, `test_config.py`, `test_policy.py`
- Updated test imports for relocated modules
- Fixed monkeypatch targets (e.g., `fastapi_topaz.cache` instead of `fastapi_topaz.dependencies`)

## [0.1.0] - 2025-11-30

### Added

#### Core Authorization
- `TopazConfig` - Central configuration for Topaz authorization
- `require_policy_allowed()` - Policy-based authorization dependency
- `require_policy_auto()` - Auto-generated policy paths from routes
- `require_rebac_allowed()` - Relationship-based access control (ReBAC)
- `require_rebac_hierarchy()` - Hierarchical resource authorization
- `get_authorized_resource()` - Fetch and authorize in one call
- `filter_authorized_resources()` - Bulk filtering with concurrent checks

#### Performance & Reliability
- `DecisionCache` - TTL-based decision caching with LRU eviction
- `CircuitBreaker` - Graceful degradation with configurable thresholds
- `ConnectionPool` - Reusable client connections

#### Middleware
- `TopazMiddleware` - Global authorization middleware
- `skip_middleware()` - Decorator to bypass middleware on specific routes

#### Observability
- `AuditLogger` - Structured JSON audit logging
- `PrometheusMetrics` - Authorization metrics (latency, decisions, cache hits)
- `OTelTracing` - OpenTelemetry distributed tracing

#### Developer Experience
- CLI tools for policy generation (`topaz-codegen`)
- Testing utilities for mocking authorization
- Full documentation following Diataxis framework

### Dependencies
- FastAPI >= 0.100.0
- aserto >= 0.32.2
- Python >= 3.9

[Unreleased]: https://github.com/jmanteau/fastapi-topaz/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v1.0.1
[1.0.0]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v1.0.0
[0.1.0]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v0.1.0
