"""Symbol tools: document_symbols, workspace_symbols."""

from typing import Any

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    LSP_WORKSPACE_SYMBOL,
)
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    manager_or_error,
    prepare_file_tool,
    workspace_path_or_error,
)
from jons_mcp_java.utils import format_symbol


@mcp.tool()
async def document_symbols(file_path: str) -> dict[str, Any]:
    """Get all symbols defined in a Java file."""
    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    try:
        response = await context.client.request(
            LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
            {"textDocument": {"uri": context.resolved.uri}},
        )
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    if response is None:
        return {"symbols": []}

    if not isinstance(response, list):
        return {"symbols": []}

    symbols = [
        format_symbol(sym, workspace_root=context.manager.workspace_root)
        for sym in response
        if isinstance(sym, dict)
    ]
    return {"symbols": symbols}


@mcp.tool()
async def workspace_symbols(
    query: str,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Search for symbols in an initialized project workspace."""
    if not isinstance(query, str):
        return {
            "status": "error",
            "error": {
                "type": "invalid_query",
                "message": "query must be a string.",
            },
        }

    manager, error = manager_or_error()
    if error is not None or manager is None:
        return error or {}

    if file_path:
        path, path_error = workspace_path_or_error(manager, file_path)
        if path_error is not None or path is None:
            return path_error or {}
        status = await manager.get_client_for_file_with_status(path)
    else:
        status = manager.get_initialized_client()

    if status.status == "initializing":
        return {
            "status": "initializing",
            "message": status.message,
            "project": status.project,
        }
    if status.status != "ready" or status.client is None:
        return {
            "status": "error",
            "error": {
                "type": status.error_type or status.status,
                "message": status.message,
                "project": status.project,
            },
        }

    try:
        response = await status.client.request(LSP_WORKSPACE_SYMBOL, {"query": query})
    except Exception as exc:
        return exception_response(exc, project=status.project)

    if response is None or not isinstance(response, list):
        return {"symbols": []}

    symbols = [
        format_symbol(sym, workspace_root=manager.workspace_root)
        for sym in response
        if isinstance(sym, dict)
    ]

    return {"symbols": symbols}
