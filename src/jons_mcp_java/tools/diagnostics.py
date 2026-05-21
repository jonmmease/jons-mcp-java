"""Diagnostics tool."""

from typing import Any

from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    error_response,
    exception_response,
    manager_or_error,
    workspace_path_or_error,
)
from jons_mcp_java.utils import uri_to_path


@mcp.tool()
async def diagnostics(file_path: str | None = None) -> dict[str, Any]:
    """Get diagnostics for a file or all initialized projects."""
    manager, error = manager_or_error()
    if error is not None or manager is None:
        return error or {}

    if file_path:
        path, path_error = workspace_path_or_error(manager, file_path)
        if path_error is not None or path is None:
            return path_error or {}

        status = await manager.get_client_for_file_with_status(path)
        if status.status == "initializing":
            return {
                "status": "initializing",
                "message": status.message,
                "project": status.project,
            }
        if status.status != "ready" or status.client is None:
            return error_response(
                status.error_type or status.status,
                status.message,
                path=str(path),
                project=status.project,
            )

        waiter = manager.create_diagnostics_waiter(path)
        try:
            changed = await status.client.ensure_file_open(path)
        except Exception as exc:
            manager.cancel_diagnostics_waiter(path, waiter)
            return exception_response(exc, path=str(path), project=status.project)

        if changed:
            raw_diagnostics = await manager.wait_for_diagnostics(path, waiter)
        else:
            manager.cancel_diagnostics_waiter(path, waiter)
            raw_diagnostics = manager.get_diagnostics(path)

        formatted = _format_diagnostics(str(path), raw_diagnostics)
        return {"diagnostics": formatted}

    all_formatted = []
    for uri, diags in manager.get_all_diagnostics().items():
        try:
            diagnostic_path = str(uri_to_path(uri))
        except ValueError:
            diagnostic_path = uri
        all_formatted.extend(_format_diagnostics(diagnostic_path, diags))

    return {"diagnostics": sorted(all_formatted, key=_diagnostic_sort_key)}


def _format_diagnostics(
    file_path: str,
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Format LSP diagnostics to a user-friendly format."""
    result = []
    for diag in diagnostics:
        range_obj = diag.get("range", {})
        start = range_obj.get("start", {}) if isinstance(range_obj, dict) else {}

        severity = diag.get("severity", 1)
        severity_name = {
            1: "error",
            2: "warning",
            3: "information",
            4: "hint",
        }.get(severity, "unknown")

        result.append(
            {
                "file": file_path,
                "line": start.get("line", 0),
                "character": start.get("character", 0),
                "severity": severity_name,
                "message": diag.get("message", ""),
                "source": diag.get("source", "jdtls"),
                "code": diag.get("code"),
            }
        )

    return sorted(result, key=_diagnostic_sort_key)


def _diagnostic_sort_key(diagnostic: dict[str, Any]) -> tuple[str, int, int, str, str]:
    return (
        str(diagnostic.get("file", "")),
        _safe_int(diagnostic.get("line", 0)),
        _safe_int(diagnostic.get("character", 0)),
        str(diagnostic.get("severity", "")),
        str(diagnostic.get("message", "")),
    )


def _safe_int(value: object) -> int:
    if isinstance(value, int):
        return value
    return 0
