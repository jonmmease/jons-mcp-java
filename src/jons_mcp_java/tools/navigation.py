"""Navigation tools: definition, references, implementation, type_definition."""

from typing import Any

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DEFINITION,
    LSP_TEXT_DOCUMENT_IMPLEMENTATION,
    LSP_TEXT_DOCUMENT_REFERENCES,
    LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
)
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    prepare_file_tool,
    validate_position,
)
from jons_mcp_java.utils import format_locations


async def _navigation_request(
    method: str,
    file_path: str,
    line: int,
    character: int,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    position_error = validate_position(line, character)
    if position_error is not None:
        return position_error

    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    params: dict[str, Any] = {
        "textDocument": {"uri": context.resolved.uri},
        "position": {"line": line, "character": character},
    }
    if extra_params:
        params.update(extra_params)

    try:
        response = await context.client.request(method, params)
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    return format_locations(response, context.manager.workspace_root)


@mcp.tool()
async def definition(
    file_path: str,
    line: int,
    character: int,
) -> dict[str, Any]:
    """Navigate to the definition of a symbol at the given position."""
    return await _navigation_request(
        LSP_TEXT_DOCUMENT_DEFINITION,
        file_path,
        line,
        character,
    )


@mcp.tool()
async def references(
    file_path: str,
    line: int,
    character: int,
    include_declaration: bool = True,
) -> dict[str, Any]:
    """Find all references to the symbol at the given position."""
    return await _navigation_request(
        LSP_TEXT_DOCUMENT_REFERENCES,
        file_path,
        line,
        character,
        {"context": {"includeDeclaration": include_declaration}},
    )


@mcp.tool()
async def implementation(
    file_path: str,
    line: int,
    character: int,
) -> dict[str, Any]:
    """Find implementations of an interface or abstract method."""
    return await _navigation_request(
        LSP_TEXT_DOCUMENT_IMPLEMENTATION,
        file_path,
        line,
        character,
    )


@mcp.tool()
async def type_definition(
    file_path: str,
    line: int,
    character: int,
) -> dict[str, Any]:
    """Navigate to the type definition of a symbol at the given position."""
    return await _navigation_request(
        LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
        file_path,
        line,
        character,
    )
