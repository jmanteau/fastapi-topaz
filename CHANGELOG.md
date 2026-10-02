# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CircuitBreaker.admit()` returns an `Admission` ticket (exported from the package root) to pass back to `record_success`, `record_failure` and `release_probe`; `should_allow_request()` still works and returns a bool
- `PolicyDiff.skipped` and the `"skipped"` value for `RouteResolution.resolution_source`, for routes `TopazMiddleware` does not authorize

### Fixed

- Circuit breaker: in half-open state only calls admitted as probes for the current half-open period free probe slots and decide recovery. A slow call admitted while closed, or a late probe from an earlier half-open period, could free the current probe's slot (letting more than `half_open_max_requests` through) and count toward `success_threshold`, closing the circuit on stale evidence. Calls without a ticket keep the previous behavior
- `get_authorized_resource` awaits fetchers that are objects with an async `__call__`, and awaitables returned by sync wrappers such as `lambda r: fetch(r)`; the endpoint previously received an un-awaited coroutine and the 404 for a missing resource was skipped
- `annotate_openapi`, `generate_rights_matrix`, `policy-diff` and the `check` CLI command now report routes `TopazMiddleware` never checks as `skipped`, instead of as authorized by the resolution chain. That covers `@skip_middleware`, `Depends(SkipMiddleware)` at route or router level (frontend routes included), and the installed middleware's `exclude_paths` and `exclude_methods`, with `exclude_paths` matched against route templates. Skipped operations get `x-authz-source: skipped` and no `x-authz-policy`. `policy-diff` no longer reports a skipped route as missing

- `require_policy_auto` now includes `include_router()` prefixes on FastAPI 0.137+; it previously checked the un-prefixed route path (e.g. `myapp.POST` instead of `myapp.POST.api.folders` for a router included under `/api/folders`). When the route path cannot be resolved it fails with 500 instead of falling back to the un-prefixed path
- Dependencies (`require_policy_allowed`, `require_policy_auto`, `require_rebac_allowed`, `get_authorized_resource`, `filter_authorized_resources`, `require_rebac_hierarchy`) now return 503 when the authorizer call fails and the circuit breaker gives no fallback decision (for example `INVALID_ARGUMENT` for a missing policy, or any error without a breaker); the error previously escaped as an unhandled 500. With `expose_deny_reason=True` the body names the policy, source and error type

- Policy generation, `policy-diff`, the rights matrix and the `check` CLI command now include frontend routes (one `GET` entry per mount path) and mounts (one entry each for `GET`, `POST`, `PUT`, `PATCH`, `DELETE`), which the middleware already authorizes; previously `policy-diff` reported them in sync while the middleware denied them at runtime
- `TopazMiddleware` now fails closed with 403 for any breakage in FastAPI's private frontend matching internals, not only a missing matcher; other changes previously produced a 500
- With a root frontend (`app.frontend("/")`), requests FastAPI answers with a trailing-slash redirect are no longer checked against the frontend policy, so a deny no longer replaces the redirect with a 403
- The circuit breaker no longer locks up in half-open: a successful probe now frees its slot, so with the defaults (`success_threshold=2`, `half_open_max_requests=1`) the second probe is allowed and the circuit closes. A probe that is cancelled or fails with a non-failure gRPC code (e.g. `INVALID_ARGUMENT`) also frees its slot instead of forcing the fallback forever
- A decision-cache write error (e.g. `OSError` from a custom backend) in `check_decision` or batched `check_relations` now propagates and fails closed; previously it counted as a breaker failure and could serve a stale cached allow over a fresh deny
- `generate_policies` and `fastapi-topaz generate-policies` no longer overwrite existing `.rego` files. Behavior change: existing files are skipped (the CLI prints `SKIP`) unless you pass `overwrite=True` / `--overwrite`, which the docs already described
- Decision cache keys now hash a JSON list of identity type, identity value, policy instance, policy path, decision and resource context; previously `:`-joined fields could collide (e.g. `("a:b", "c")` and `("a", "b:c")`), and identities of different types with the same value, or configs with different policy instances sharing one cache, could read each other's decisions. The stale fallback cache is scoped the same way
- `DecisionCache` with `max_size` below 10 no longer grows without bound (eviction removed `max_size // 10 == 0` entries); `max_size < 1` now raises `ValueError`
- `require_rebac_hierarchy([])` and `TopazConfig.check_hierarchy(request, [])` now raise `ValueError`; an empty hierarchy previously allowed every request
- `get_authorized_resource` now authorizes before calling the fetcher, so a denied request returns 403 whether or not the resource exists (previously a 404 revealed which IDs exist); an allowed request for a missing resource returns 404. Async fetchers are awaited and sync fetchers run in the threadpool instead of blocking the event loop
- An audit handler that raises, or an event whose resource context JSON cannot serialize, no longer turns an authorization decision into a 500; the error is logged and the response is unchanged. `AuditEvent.to_json()` stringifies unsupported values
- Audit events redact `identity.value` for `IDENTITY_TYPE_JWT` identities, and `include_request_headers` also redacts `proxy-authorization`, `x-api-key`, `x-auth-token` and `x-csrf-token`. DEBUG logs in the dependencies no longer include the identity value
- Two `PrometheusMetrics` instances on one registry with the same prefix and different label options now raise `ValueError` at construction, naming the metric and both label sets; previously the second instance reused collectors with the wrong labels and failed on every request
- `policy_diff` resolves a route by the first matching policy group only, like the middleware: a missing file for that group reports the route missing instead of falling through to a later group or the default policy
- Typed path parameters (`{path:path}`, `{id:int}`) no longer leave the converter in policy paths and generated `package` lines (`myapp.GET.files.__path`, not `__path:path`), and codegen reads their names correctly
- `generate_policies` no longer writes skeletons for routes covered by a policy group or `default_policy`; the middleware never evaluates such a file, and an `allowed` skeleton could hide that the effective policy is different. `{root}.check` is still generated
- `annotate_openapi` writes `x-authz-policy` / `x-authz-source` as `{method: value}` maps when a route's methods resolve differently (previously the first method won), and skips non-API routes
- The `fastapi-topaz` console script adds the working directory to `sys.path`, so `--app myapp:app` finds `./myapp.py`
- `fastapi-topaz policy-map` accepts `--config` and uses its `policy_path_root` and `policy_path_normalizer`
- `from fastapi_topaz import *` no longer emits `DeprecationWarning`s: deprecated aliases are removed from `__all__` (they remain importable by name)
- `AuthorizationError` can be raised through `contextlib.contextmanager` and other code that sets `__traceback__`; it was a frozen dataclass and raised `FrozenInstanceError`
- `require_rebac_allowed` and `get_authorized_resource` with a static `object_id=""`, an id source of `"static:"`, and `TopazConfig(max_concurrent_checks=0)` now raise `ValueError` at construction
- `MockTopazConfig` supports `check_relations(batch=True)`, and `install_mock` patches the batched path, so batched checks no longer reach the real authorizer in tests
- `ConnectionPool.close()` no longer closes connections still held by callers; they are closed when released. `health_check_interval`, `health_check_timeout`, `retry_on_failure` and `max_retries` are documented as having no effect

### Changed

- Documented that on FastAPI 0.137+ `annotate_openapi` must run after routes are added to routers already passed to `include_router()`
- Breaking for custom cache backends: `CacheBackend.get` and `CacheBackend.set` (and `DecisionCache.get`/`set`) take keyword-only `identity_type` and `policy_instance` arguments, which the library passes on every call; add them (or `**kwargs`) to custom backends. Existing cache entries are not reused after upgrading because the key format changed
- Path parameters no longer override trusted resource context: the policy resource context is merged as path params, then static `resource_context`, then `resource_context_provider`, so a provider's `tenant_id` wins over a `/tenants/{tenant_id}` URL value. Applies to dependencies, the middleware and `is_allowed`
- Codegen no longer excludes the docs routes (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) by default, since the middleware authorizes them; `scan_routes`, `generate_policies`, `policy_diff` and the rights matrix now list them. Disable them on the app or pass `exclude_paths` to `scan_routes` to leave them out
- `install_mock` also patches `identity_provider`: tests get `MockTopazConfig.identity_returns` as an `IDENTITY_TYPE_SUB` identity (or an unauthenticated identity for `None`) instead of the config's own provider
- CLI commands exit with code 2 instead of 1 when the app or config cannot be imported
- The integration-test webapp runs on current FastAPI again (it was pinned below 0.122), and its image takes a `FASTAPI_SPEC` build argument to test other route layouts

### Removed

- `ConnectionPool`, `PoolStatus` and `TopazConfig(connection_pool=...)`, deprecated in 1.2.0. They had no effect: authorization checks share one gRPC channel per `TopazConfig`. Delete the argument

### Deprecated

- The `TopazMiddleware(on_error=...)` default changes from `"deny"` (403) to `"unavailable"` (503) in 2.0, to match the dependencies; pass `on_error="deny"` to keep today's behavior

## [1.2.1] - 2026-10-01

### Fixed

- `TopazMiddleware` now authorizes FastAPI frontend routes (`app.frontend()` / `router.frontend()`), which FastAPI matches outside `app.routes`; previously they were passed through unchecked as if they were 404s. They use a prefix-only policy path from the mount path (e.g. `myapp.GET.app`), like mounts, and honor router-level `SkipMiddleware`. If FastAPI's private frontend matching internals change, the middleware fails closed with 403 for requests that match no regular route
- `annotate_openapi` no longer writes annotations onto the original route of an included router: a router included under several prefixes could get another prefix's `x-authz-policy` after FastAPI rebuilt its route contexts. An unrecognized FastAPI route context layout now logs a warning instead of silently dropping annotations

### Changed

- Documented the excluded FastAPI 0.137.0 and 0.137.1 releases in the requirements
- CI now also tests the lowest supported FastAPI (0.100)

## [1.2.0] - 2026-10-01

### Added

- 2026-07-06: `CacheBackend` protocol: structural interface for pluggable decision cache backends (e.g. Redis); any object with `get`/`set`/`clear`/`size` can be passed as `TopazConfig(decision_cache=...)`; exported from the package root
- 2026-07-06: `DecisionCache.invalidate(identity_value=..., policy_path=..., object_id=...)` and `TopazConfig.invalidate_cache(...)`: selective decision invalidation (AND of provided criteria) for permission changes; the stale fallback cache is always cleared entirely
- 2026-07-06: `check_relations(..., batch=True)`: opt-in single-RPC evaluation of multiple relations against the `{root}.check` policy (one rule per relation name); per-relation caching, circuit-breaker fallback, metrics, and audit events preserved
- 2026-07-06: `TopazConfig.health(ping=False)`: readiness helper returning circuit-breaker status, cache size, and an optional authorizer Info-RPC reachability probe (via new `SharedAuthorizerClient.info()`)
- 2026-07-06: `annotate_openapi(app, config, policies_dir=None)`: stamps each route's resolved policy path into the OpenAPI schema as `x-authz-policy` / `x-authz-source` extensions; exported from the package root
- 2026-07-06: `fastapi-topaz check --app ... --method GET --path /documents/1`: CLI command resolving which policy guards a concrete URL, with `--live` evaluation against the authorizer (exit 0 allowed / 1 denied / 2 error)
- 2026-07-06: `TopazConfig(expose_deny_reason=True)`: structured 403 bodies including the evaluated policy path and check source (dev/debug only; leaks policy structure)
- 2026-07-06: Test coverage for previously untested paths: `SharedAuthorizerClient.decisions()` request construction, OpenTelemetry span attributes/status (via `opentelemetry-sdk` in dev extras), and the `generate-rights-matrix` CLI command
- `TopazConfig(insecure=...)`: first-class plaintext (non-TLS) gRPC channel option for local development, replacing ad-hoc monkey-patching
- `fastapi_topaz.__version__` exposing the installed package version
- `TopazConfig(check_timeout=...)`: gRPC deadline in seconds applied to each authorization call (default 5.0), so a hung Topaz no longer hangs requests forever
- `TopazMiddleware(on_error=...)`: opt-in `"unavailable"` mode returns 503 instead of the fail-closed 403 default when the authorization check itself fails
- `CircuitBreaker(failure_grpc_codes=...)`: set of gRPC status codes treated as failures (default: UNAVAILABLE, DEADLINE_EXCEEDED, UNKNOWN, INTERNAL, RESOURCE_EXHAUSTED); policy errors such as INVALID_ARGUMENT do not trip the breaker
- `AuditLogger.log_decision(reason=...)`: optional reason field forwarded to the audit event
- GitHub Actions CI workflow running lint, typecheck, and tests across Python 3.9-3.13 on pushes to main and pull requests
- `AuditLogger(include_request_headers=True)` now works: request headers are included in audit events with `authorization` and `cookie` values redacted
- `AuditLogger(log_skipped=True)` now works: excluded routes and methods emit `authorization.middleware.skipped` events at `level_skipped`
- Circuit-breaker metrics auto-wiring: when `metrics` and `circuit_breaker` are both configured and no user `on_state_change` callback is set, circuit transitions and the state gauge are recorded automatically
- Cache-size gauge: `check_decision` updates `topaz_cache_size` after each cached decision when `metrics` and `decision_cache` are configured
- `DecisionCache.size()`: current number of cached entries

### Changed

- Denied authorization responses from dependencies now return a generic `"Forbidden"` detail (matching the middleware) instead of leaking the policy path, relation, or denied hierarchy level; the details remain in DEBUG logs and audit events
- Per-request dependency log lines (check/result/granted/denied) moved from INFO/WARNING to DEBUG; the audit logger is the structured record for decisions
- Middleware caches route matches for static paths (no path parameters), skipping the per-request route scan
- `policy_groups` and `default_policy` are validated on every assignment, not only at construction
- Decision-cache and stale-cache keys use a shared helper with JSON-based context serialization stable across nested-dict key ordering
- Audit events are now emitted from `check_decision` for all sources (middleware, dependency, manual), so dependency and manual checks are audited too; previously only the middleware emitted decision events
- `AuditLogger(include_resource_context=...)` now defaults to `False`: resource context often carries user data (emails, names, document attributes) that should not land in logs unreviewed; set it to `True` explicitly to restore the previous behavior
- Documented that the audit `client_ip` field trusts `x-forwarded-for` / `x-real-ip` headers, which are client-spoofable without a trusted reverse proxy
- FastAPI 0.137.0 and 0.137.1 are excluded from the supported range: they store included routers as a tree but lack the `fastapi.routing.iter_route_contexts()` API needed to walk it

### Deprecated

- `ConnectionPool`: has no effect on authorization calls (they use the shared channel) and will be removed in 2.0; it now closes underlying channels when discarding connections and emits a `DeprecationWarning` on `configure()`
- `TopazConfig.create_client()`: no longer used internally; each call opens a new channel the caller must close; will be removed in 2.0
- `CircuitBreaker.timeout_ms`: has no effect; use `TopazConfig.check_timeout` instead; warns on non-default values and will be removed in 2.0
- `CircuitBreaker.cache_priority`: has no effect; warns when set and will be removed in 2.0
- `fastapi_topaz.AuthorizationError` and the `IdentityMapper`/`StringMapper`/`ObjectMapper`/`ResourceMapper` type aliases: served lazily with a `DeprecationWarning` on import and will be removed in 2.0

### Removed

- Python 3.9 support (end of life since October 2025): `requires-python` is now `>=3.10`
- Dead no-op fixture stubs in `fastapi_topaz.testing` (`pytest_configure`, `mock_topaz_config_fixture`, `allow_all_auth_fixture`, `deny_all_auth_fixture`)
- Ineffective PolicyGroup overlap warning that only probed hardcoded prefixes
- Wall-clock ReDoS probe in `PolicyGroup` pattern compilation: it was flaky under CI jitter and patterns come from the app developer (trusted); plain regex-validity checking remains

### Fixed

- pyproject URLs now point to this project instead of the upstream Topaz repository
- CLI output uses plain text instead of unicode symbols
- Documentation deploy workflow now requires quality checks and tests to pass before deploying
- Circuit breaker now detects gRPC errors (`grpc.RpcError`, including `grpc.aio.AioRpcError`) as failures based on their status code, so the breaker actually trips during Topaz outages; previously the default `failure_exceptions` never matched gRPC errors
- Authorization checks now reuse a single long-lived gRPC channel instead of opening (and never closing) a new secure channel per request, eliminating a channel and file-descriptor leak
- Middleware now logs authorization infrastructure errors with full tracebacks and emits an audit event with `reason="authorizer_error"` instead of silently converting every failure into a 403; identity-provider exceptions are logged instead of being swallowed
- Cache hits now record the actual cached decision in metrics and tracing; previously every cache hit was labeled `decision="denied"` regardless of the cached value
- Middleware authorization checks are now attributed to `source="middleware"` in metrics, cache counters, and tracing spans, matching the audit log; previously they were mislabeled as `source="dependency"`
- `scan_routes` (and therefore `generate-policies`, `policy-diff`, and `generate-rights-matrix`) now applies the configured `policy_path_normalizer`, so generated policies match what the runtime evaluates instead of drifting on e.g. hyphenated paths
- `policy_diff` no longer reports `default_policy` and `PolicyGroup` policy files as orphaned, so a correctly configured resolution chain passes `policy-diff --strict`
- `TopazConfig` and `ConnectionPool` now create their asyncio primitives lazily on first use instead of at construction, fixing "attached to a different loop" errors on Python 3.9 when the config is created at module import time
- Dependencies now raise 500 on unresolvable or empty object IDs (missing path param, header, or query param) instead of silently checking against `object_id=""` in Topaz
- Creating a second `PrometheusMetrics` instance no longer crashes with a duplicate-registration error; existing collectors are reused from the registry
- `SkipMiddleware` is now detected anywhere in a route's resolved dependency tree (including nested sub-dependencies), so router-level skips work across FastAPI versions that do not merge router dependencies into `route.dependencies`
- Routes registered via `include_router` are seen correctly on FastAPI >= 0.137, which stopped flattening included routers into `app.routes`: the middleware now resolves the route template (not the concrete URL) for the policy path and honors router-level `SkipMiddleware`, and `scan_routes` (`generate-policies`, `policy-diff`, `generate-rights-matrix`), `annotate_openapi`, and `fastapi-topaz check` no longer silently omit router routes

## [1.1.0] - 2026-02-13

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

[Unreleased]: https://github.com/jmanteau/fastapi-topaz/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/jmanteau/fastapi-topaz/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/jmanteau/fastapi-topaz/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jmanteau/fastapi-topaz/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v1.0.1
[1.0.0]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v1.0.0
[0.1.0]: https://github.com/jmanteau/fastapi-topaz/releases/tag/v0.1.0
