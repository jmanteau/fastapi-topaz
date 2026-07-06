"""Shared policy path utilities used by dependencies and codegen."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .config import PolicyGroup

logger = logging.getLogger("fastapi_topaz")


def _policy_path_heuristic(path: str) -> str:
    """
    Convert a URL path to a policy path segment.

    Examples:
        "/" -> ""
        "/documents" -> ".documents"
        "/documents/{id}" -> ".documents.__id"
        "/users/{user_id}/docs/{doc_id}" -> ".users.__user_id.docs.__doc_id"
    """
    if not path or path == "/":
        return ""

    # Remove leading slash and split into segments
    segments = path.strip("/").split("/")
    result_parts: list[str] = []

    for segment in segments:
        if not segment:
            continue
        # Check if it's a path parameter (e.g., {id} or {user_id})
        if segment.startswith("{") and segment.endswith("}"):
            # Convert {param} to __param
            param_name = segment[1:-1]
            result_parts.append(f"__{param_name}")
        else:
            result_parts.append(segment)

    if not result_parts:
        return ""

    return "." + ".".join(result_parts)


def _resolve_policy_path(
    root: str,
    method: str,
    path: str,
    policy_path_normalizer: Callable[[str], str] | None = None,
) -> str:
    """
    Build a full policy path from root, HTTP method, and URL path.

    Args:
        root: Policy path root (e.g., "myapp")
        method: HTTP method (e.g., "GET", "POST")
        path: URL path pattern (e.g., "/documents/{id}")
        policy_path_normalizer: Optional callable to transform the generated
            policy path (e.g., replace hyphens with underscores)

    Returns:
        Full policy path (e.g., "myapp.GET.documents.__id")
    """
    heuristic = _policy_path_heuristic(path)
    result = f"{root}.{method}{heuristic}"
    if policy_path_normalizer is not None:
        result = policy_path_normalizer(result)
    return result


def _compile_policy_groups(
    groups: tuple[PolicyGroup, ...] | list[PolicyGroup],
) -> list[tuple[re.Pattern[str], str]]:
    """Pre-compile PolicyGroup regex patterns.

    Raises :class:`ValueError` on invalid regex. Patterns come from the app
    developer (trusted), so no ReDoS heuristics are applied.
    """
    compiled: list[tuple[re.Pattern[str], str]] = []
    for group in groups:
        try:
            pattern = re.compile(group.url_pattern)
        except re.error as e:
            raise ValueError(
                f"Invalid regex in PolicyGroup url_pattern {group.url_pattern!r}: {e}"
            ) from e
        compiled.append((pattern, group.policy_path))
    return compiled


def scan_policy_files(policies_dir: str | Path | None) -> set[str]:
    """Scan a directory for ``.rego`` files and return the set of policy paths.

    Each ``.rego`` file is converted to a dotted policy path by stripping the
    extension and replacing path separators with dots.

    Example::

        >>> scan_policy_files("policies")
        {"myapp.GET.documents.__id", "myapp.defaults.authenticated", ...}

    Args:
        policies_dir: Root directory to scan (recursively).  ``None`` returns
            an empty set immediately.

    Returns:
        Set of policy path strings.  Returns an empty set when the
        directory does not exist or *policies_dir* is ``None``.
    """
    if policies_dir is None:
        return set()
    policies_path = Path(policies_dir).resolve()
    result: set[str] = set()
    if not policies_path.exists():
        return result
    for rego_file in policies_path.rglob("*.rego"):
        real_file = rego_file.resolve()
        # Verify file stays within policies_dir (prevent symlink escape)
        try:
            real_file.relative_to(policies_path)
        except ValueError:
            logger.warning("Skipping symlink escape: %s -> %s", rego_file, real_file)
            continue
        relative = rego_file.relative_to(policies_path)
        policy_path = str(relative.with_suffix("")).replace("/", ".")
        result.add(policy_path)
    return result


def normalize_hyphens(path: str) -> str:
    """Replace hyphens with underscores in a policy path.

    Useful when REST API paths contain hyphens (e.g., /aircraft-programs)
    that are invalid in Rego identifiers.
    """
    return path.replace("-", "_")
