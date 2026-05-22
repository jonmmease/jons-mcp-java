"""Info tools: symbol_info."""

from typing import Any

from jons_mcp_java.constants import LSP_TEXT_DOCUMENT_HOVER
from jons_mcp_java.schemas import SymbolInfoResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    prepare_file_tool,
    validate_position,
)
from jons_mcp_java.utils import normalize_hover_content, public_position_to_lsp


@mcp.tool()
async def symbol_info(
    file_path: str,
    line: int,
    character: int,
) -> SymbolInfoResult | dict[str, Any]:
    """Get hover information for a symbol at the given position."""
    position_error = validate_position(line, character)
    if position_error is not None:
        return position_error

    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    try:
        response = await context.client.request(
            LSP_TEXT_DOCUMENT_HOVER,
            {
                "textDocument": {"uri": context.resolved.uri},
                "position": public_position_to_lsp(line, character),
            },
        )
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    content, range_obj = normalize_hover_content(response)
    return SymbolInfoResult.model_validate({"content": content, "range": range_obj})
