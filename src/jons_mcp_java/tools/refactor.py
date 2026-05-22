"""Refactoring preview tools."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_PREPARE_RENAME,
    LSP_TEXT_DOCUMENT_RENAME,
)
from jons_mcp_java.schemas import RenamePreviewError, RenamePreviewResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    error_response,
    exception_response,
    prepare_file_tool,
    validate_position,
)
from jons_mcp_java.utils import normalize_rename_preview, public_position_to_lsp


@mcp.tool()
async def preview_rename(
    file_path: str,
    line: int,
    character: int,
    new_name: str,
) -> RenamePreviewResult | RenamePreviewError | dict[str, Any]:
    """Preview a symbol rename across the project without writing files."""
    position_error = validate_position(line, character)
    if position_error is not None:
        return position_error
    if not isinstance(new_name, str) or not new_name:
        return error_response("invalid_name", "new_name must be a non-empty string.")

    context, error = await prepare_file_tool(file_path)
    if error is not None or context is None:
        return error or {}

    position = public_position_to_lsp(line, character)
    params = {
        "textDocument": {"uri": context.resolved.uri},
        "position": position,
    }

    try:
        try:
            prepare_result = await context.client.request(
                LSP_TEXT_DOCUMENT_PREPARE_RENAME,
                params,
            )
            if not prepare_result:
                return RenamePreviewError(error="Symbol cannot be renamed")
        except Exception:
            pass

        response = await context.client.request(
            LSP_TEXT_DOCUMENT_RENAME,
            {**params, "newName": new_name},
        )
    except Exception as exc:
        return exception_response(
            exc,
            path=str(context.resolved.path),
            project=context.project,
        )

    if not response:
        return RenamePreviewError(error="Rename failed")
    if not isinstance(response, dict):
        return RenamePreviewError(error="Rename failed")

    try:
        return normalize_rename_preview(response, context.manager.workspace_root)
    except (TypeError, ValidationError):
        return RenamePreviewError(error="Rename returned unsupported edit shape")
