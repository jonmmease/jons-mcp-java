"""Diagnostics tool."""

from pathlib import Path

from jons_mcp_java.server import manager, mcp
from jons_mcp_java.utils import uri_to_path


@mcp.tool()
async def diagnostics(
    file_path: str | None = None,
) -> dict:
    """
    Get diagnostics (errors, warnings) for a file or all files.

    Args:
        file_path: Optional path to get diagnostics for a specific file.
                  If not provided, returns diagnostics for all files.

    Returns:
        Dictionary with 'diagnostics' array containing formatted diagnostic info
    """
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    if file_path:
        # Get diagnostics for specific file
        raw_diagnostics = manager.get_diagnostics(Path(file_path))
        formatted = _format_diagnostics(file_path, raw_diagnostics)
        return {"diagnostics": formatted}
    else:
        # Get all diagnostics
        all_raw = manager.get_all_diagnostics()
        all_formatted = []
        for uri, diags in all_raw.items():
            try:
                path = str(uri_to_path(uri))
            except ValueError:
                path = uri
            all_formatted.extend(_format_diagnostics(path, diags))

        return {"diagnostics": all_formatted}


def _format_diagnostics(file_path: str, diagnostics: list) -> list[dict]:
    """Format LSP diagnostics to a user-friendly format."""
    result = []
    for diag in diagnostics:
        range_obj = diag.get("range", {})
        start = range_obj.get("start", {})

        severity = diag.get("severity", 1)
        severity_name = {
            1: "error",
            2: "warning",
            3: "information",
            4: "hint",
        }.get(severity, "unknown")

        result.append({
            "file": file_path,
            "line": start.get("line", 0),
            "character": start.get("character", 0),
            "severity": severity_name,
            "message": diag.get("message", ""),
            "source": diag.get("source", "jdtls"),
            "code": diag.get("code"),
        })

    return result
