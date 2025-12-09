"""Info tools: hover."""

from pathlib import Path

from jons_mcp_java.constants import LSP_TEXT_DOCUMENT_HOVER
from jons_mcp_java.server import get_manager, mcp
from jons_mcp_java.utils import path_to_uri


@mcp.tool()
async def hover(
    file_path: str,
    line: int,
    character: int,
) -> dict:
    """
    Get hover information (Javadoc, type info) for a symbol at the given position.

    Args:
        file_path: Absolute path to the Java file
        line: 0-indexed line number
        character: 0-indexed character position

    Returns:
        Dictionary with 'content' (markdown) or 'status'/'message' if initializing
    """
    manager = get_manager()
    if manager is None:
        return {"status": "error", "message": "Server not initialized"}

    client, status = await manager.get_client_for_file_with_status(Path(file_path))

    if client is None:
        return {"status": "initializing", "message": status}

    await client.ensure_file_open(file_path)

    response = await client.request(
        LSP_TEXT_DOCUMENT_HOVER,
        {
            "textDocument": {"uri": path_to_uri(file_path)},
            "position": {"line": line, "character": character}
        }
    )

    if response is None:
        return {"content": None, "message": "No hover information available"}

    # Extract content from hover response
    contents = response.get("contents", {})

    if isinstance(contents, str):
        return {"content": contents}

    if isinstance(contents, dict):
        # MarkupContent
        return {"content": contents.get("value", "")}

    if isinstance(contents, list):
        # Array of MarkedString or MarkupContent
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "value" in item:
                    parts.append(item["value"])
                elif "language" in item:
                    # MarkedString with language
                    lang = item.get("language", "")
                    value = item.get("value", "")
                    parts.append(f"```{lang}\n{value}\n```")
        return {"content": "\n\n".join(parts)}

    return {"content": None}
