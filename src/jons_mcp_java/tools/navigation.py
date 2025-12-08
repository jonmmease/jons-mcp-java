"""Navigation tools: definition, references, implementation, type_definition."""

from pathlib import Path

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DEFINITION,
    LSP_TEXT_DOCUMENT_IMPLEMENTATION,
    LSP_TEXT_DOCUMENT_REFERENCES,
    LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
)
from jons_mcp_java.server import manager, mcp
from jons_mcp_java.utils import format_locations, path_to_uri


@mcp.tool()
async def definition(
    file_path: str,
    line: int,
    character: int,
) -> dict:
    """
    Navigate to the definition of a symbol at the given position.

    Args:
        file_path: Absolute path to the Java file
        line: 0-indexed line number
        character: 0-indexed character position

    Returns:
        Dictionary with 'locations' array or 'status'/'message' if initializing
    """
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    # Get client with status feedback
    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    # Ensure file is open
    await client.ensure_file_open(file_path)

    # Make LSP request
    response = await client.request(
        LSP_TEXT_DOCUMENT_DEFINITION,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }
    )

    return format_locations(response)


@mcp.tool()
async def references(
    file_path: str,
    line: int,
    character: int,
    include_declaration: bool = True,
) -> dict:
    """
    Find all references to the symbol at the given position.

    Args:
        file_path: Absolute path to the Java file
        line: 0-indexed line number
        character: 0-indexed character position
        include_declaration: Whether to include the declaration in results

    Returns:
        Dictionary with 'locations' array or 'status'/'message' if initializing
    """
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    await client.ensure_file_open(file_path)

    response = await client.request(
        LSP_TEXT_DOCUMENT_REFERENCES,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": include_declaration}
        }
    )

    return format_locations(response)


@mcp.tool()
async def implementation(
    file_path: str,
    line: int,
    character: int,
) -> dict:
    """
    Find implementations of an interface or abstract method.

    Args:
        file_path: Absolute path to the Java file
        line: 0-indexed line number
        character: 0-indexed character position

    Returns:
        Dictionary with 'locations' array or 'status'/'message' if initializing
    """
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    await client.ensure_file_open(file_path)

    response = await client.request(
        LSP_TEXT_DOCUMENT_IMPLEMENTATION,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }
    )

    return format_locations(response)


@mcp.tool()
async def type_definition(
    file_path: str,
    line: int,
    character: int,
) -> dict:
    """
    Navigate to the type definition of a symbol at the given position.

    Args:
        file_path: Absolute path to the Java file
        line: 0-indexed line number
        character: 0-indexed character position

    Returns:
        Dictionary with 'locations' array or 'status'/'message' if initializing
    """
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    await client.ensure_file_open(file_path)

    response = await client.request(
        LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }
    )

    return format_locations(response)
