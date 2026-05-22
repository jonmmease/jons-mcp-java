"""Navigation tools: definition, references, implementation, type_definition."""

from typing import Any

from jons_mcp_java.constants import (
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    LSP_TEXT_DOCUMENT_DEFINITION,
    LSP_TEXT_DOCUMENT_IMPLEMENTATION,
    LSP_TEXT_DOCUMENT_REFERENCES,
    LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
)
from jons_mcp_java.schemas import NavigationResult, ReferencesResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    prepare_file_tool,
    validate_pagination,
    validate_position,
)
from jons_mcp_java.utils import (
    apply_pagination,
    normalize_navigation_result,
    normalize_reference_items,
    public_position_to_lsp,
)


async def _navigation_request(
    method: str,
    file_path: str,
    line: int,
    character: int,
    extra_params: dict[str, Any] | None = None,
) -> NavigationResult | dict[str, Any]:
    position_error = validate_position(line, character)
    if position_error is not None:
        return position_error

    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    params: dict[str, Any] = {
        "textDocument": {"uri": context.resolved.uri},
        "position": public_position_to_lsp(line, character),
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

    return normalize_navigation_result(response, context.manager.workspace_root)


@mcp.tool()
async def definition(
    file_path: str,
    line: int,
    character: int,
) -> NavigationResult | dict[str, Any]:
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
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> ReferencesResult | dict[str, Any]:
    """Find all references to the symbol at the given position."""
    position_error = validate_position(line, character)
    if position_error is not None:
        return position_error
    pagination_error = validate_pagination(limit, offset)
    if pagination_error is not None:
        return pagination_error

    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    try:
        response = await context.client.request(
            LSP_TEXT_DOCUMENT_REFERENCES,
            {
                "textDocument": {"uri": context.resolved.uri},
                "position": public_position_to_lsp(line, character),
                "context": {"includeDeclaration": include_declaration},
            },
        )
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    all_items = normalize_reference_items(response, context.manager.workspace_root)
    items, metadata = apply_pagination(all_items, offset, limit)
    return ReferencesResult.model_validate(
        {
            "items": items,
            **metadata,
        }
    )


@mcp.tool()
async def implementation(
    file_path: str,
    line: int,
    character: int,
) -> NavigationResult | dict[str, Any]:
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
) -> NavigationResult | dict[str, Any]:
    """Navigate to the type definition of a symbol at the given position."""
    return await _navigation_request(
        LSP_TEXT_DOCUMENT_TYPE_DEFINITION,
        file_path,
        line,
        character,
    )
