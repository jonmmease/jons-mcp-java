"""Diagnostics tool."""

from typing import Any

from jons_mcp_java.constants import DEFAULT_LIMIT, DEFAULT_OFFSET
from jons_mcp_java.schemas import DiagnosticsResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import (
    exception_response,
    prepare_file_tool,
    validate_pagination,
)
from jons_mcp_java.utils import apply_pagination, normalize_diagnostics


@mcp.tool()
async def diagnostics(
    file_path: str,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> DiagnosticsResult | dict[str, Any]:
    """Get fresh diagnostics for one Java file."""
    pagination_error = validate_pagination(limit, offset)
    if pagination_error is not None:
        return pagination_error

    context, error = await prepare_file_tool(file_path, open_file=False)
    if error is not None or context is None:
        return error or {}

    waiter = context.manager.create_diagnostics_waiter(context.resolved.path)
    try:
        changed = await context.client.ensure_file_open(context.resolved.path)
    except Exception as exc:
        context.manager.cancel_diagnostics_waiter(context.resolved.path, waiter)
        return exception_response(exc, path=str(context.resolved.path), project=context.project)

    if changed:
        raw_diagnostics = await context.manager.wait_for_diagnostics(
            context.resolved.path,
            waiter,
        )
    else:
        context.manager.cancel_diagnostics_waiter(context.resolved.path, waiter)
        raw_diagnostics = context.manager.get_diagnostics(context.resolved.path)

    all_items = normalize_diagnostics(
        context.resolved.uri,
        raw_diagnostics,
        context.manager.workspace_root,
    )
    items, metadata = apply_pagination(all_items, offset, limit)
    return DiagnosticsResult.model_validate({"items": items, **metadata})
