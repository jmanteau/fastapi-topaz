"""Shared policy path utilities used by dependencies and codegen."""
from __future__ import annotations


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


def _resolve_policy_path(root: str, method: str, path: str) -> str:
    """
    Build a full policy path from root, HTTP method, and URL path.

    Args:
        root: Policy path root (e.g., "myapp")
        method: HTTP method (e.g., "GET", "POST")
        path: URL path pattern (e.g., "/documents/{id}")

    Returns:
        Full policy path (e.g., "myapp.GET.documents.__id")
    """
    heuristic = _policy_path_heuristic(path)
    return f"{root}.{method}{heuristic}"
