"""Symbol tools: document_symbols, workspace_symbols."""

from typing import Any

from jons_mcp_java.constants import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    LSP_WORKSPACE_SYMBOL,
)
from jons_mcp_java.schemas import DocumentSymbolsResult, WorkspaceSymbolsResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    error_response,
    exception_response,
    manager_or_error,
    prepare_file_tool,
    validate_pagination,
    workspace_path_or_error,
)
from jons_mcp_java.utils import (
    apply_pagination,
    normalize_document_symbols,
    normalize_workspace_symbols,
)


@mcp.tool()
async def document_symbols(
    file_path: str,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> DocumentSymbolsResult | dict[str, Any]:
    """Get all symbols defined in a Java file."""
    pagination_error = validate_pagination(limit, offset)
    if pagination_error is not None:
        return pagination_error

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

    all_items = normalize_document_symbols(
        response,
        context.resolved.uri,
        context.manager.workspace_root,
    )
    items, metadata = apply_pagination(all_items, offset, limit)
    return DocumentSymbolsResult.model_validate({"items": items, **metadata})


@mcp.tool()
async def workspace_symbols(
    query: str,
    file_path: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> WorkspaceSymbolsResult | dict[str, Any]:
    """Search for symbols in an initialized project workspace."""
    if not isinstance(query, str):
        return error_response("invalid_query", "query must be a string.")

    pagination_error = validate_pagination(limit, offset)
    if pagination_error is not None:
        return pagination_error

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
        return error_response(
            status.error_type or status.status,
            status.message,
            project=status.project,
        )

    try:
        response = await status.client.request(LSP_WORKSPACE_SYMBOL, {"query": query})
    except Exception as exc:
        return exception_response(exc, project=status.project)

    all_items = normalize_workspace_symbols(response, manager.workspace_root)
    items, metadata = apply_pagination(all_items, offset, limit)
    return WorkspaceSymbolsResult.model_validate({"items": items, **metadata})
