"""Info tools: hover."""

from typing import Any

from jons_mcp_java.constants import LSP_TEXT_DOCUMENT_HOVER
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    prepare_file_tool,
    validate_position,
)


@mcp.tool()
async def hover(
    file_path: str,
    line: int,
    character: int,
) -> dict[str, Any]:
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
                "position": {"line": line, "character": character},
            },
        )
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    if response is None:
        return {"content": None, "message": "No hover information available"}
    if not isinstance(response, dict):
        return {"content": None}

    contents = response.get("contents", {})

    if isinstance(contents, str):
        return {"content": contents}

    if isinstance(contents, dict):
        return {"content": contents.get("value", "")}

    if isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "value" in item:
                    parts.append(item["value"])
                elif "language" in item:
                    lang = item.get("language", "")
                    value = item.get("value", "")
                    parts.append(f"```{lang}\n{value}\n```")
        return {"content": "\n\n".join(parts)}

    return {"content": None}
