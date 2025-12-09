"""Symbol tools: document_symbols, workspace_symbols."""

from pathlib import Path

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    LSP_WORKSPACE_SYMBOL,
)
from jons_mcp_java.server import get_manager, mcp
from jons_mcp_java.utils import format_symbol, path_to_uri


@mcp.tool()
async def document_symbols(
    file_path: str,
) -> dict:
    """
    Get all symbols defined in a Java file.

    Args:
        file_path: Absolute path to the Java file

    Returns:
        Dictionary with 'symbols' array or 'status'/'message' if initializing
    """
    manager = get_manager()
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    await client.ensure_file_open(file_path)

    response = await client.request(
        LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
        }
    )

    if response is None:
        return {"symbols": []}

    # Response is either DocumentSymbol[] or SymbolInformation[]
    symbols = [format_symbol(sym) for sym in response]
    return {"symbols": symbols}


@mcp.tool()
async def workspace_symbols(
    query: str,
    file_path: str | None = None,
) -> dict:
    """
    Search for symbols in the workspace.

    Args:
        query: Search query string (symbol name or pattern)
        file_path: Optional file path to determine which project to search

    Returns:
        Dictionary with 'symbols' array or 'status'/'message' if initializing
    """
    manager = get_manager()
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    # If file_path provided, use that project; otherwise use first available
    if file_path:
        client, status = await manager.get_client_for_file_with_status(Path(file_path))
    else:
        # Get any initialized client
        for project in manager._projects.values():
            if project.client and project.client.is_initialized:
                client = project.client
                status = "ready"
                break
        else:
            return {
                "status": "error",
                "message": "No initialized projects. Provide a file_path to start initialization."
            }

    if client is None:
        return {"status": "initializing", "message": status}

    response = await client.request(
        LSP_WORKSPACE_SYMBOL,
        {
            "query": query,
        }
    )

    if response is None:
        return {"symbols": []}

    # Response is SymbolInformation[]
    symbols = [format_symbol(sym) for sym in response]
    return {"symbols": symbols}
