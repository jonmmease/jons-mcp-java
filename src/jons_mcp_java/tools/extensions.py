"""Extension tools for server management."""

from typing import Any

from jons_mcp_java.schemas import RestartServerResult
from jons_mcp_java.server import mcp
from jons_mcp_java.tools.common import manager_or_error, workspace_path_or_error


@mcp.tool()
async def restart_server(file_path: str | None = None) -> RestartServerResult | dict[str, Any]:
    """
    Stop JDT.LS server(s) and clear runtime state.

    Servers restart lazily on the next file-backed tool call.
    """
    manager, error = manager_or_error()
    if error is not None or manager is None:
        return error or {}

    if file_path:
        path, path_error = workspace_path_or_error(manager, file_path)
        if path_error is not None or path is None:
            return path_error or {}
        result = await manager.restart_project_for_file(path)
        if result.get("status") == "success":
            return RestartServerResult.model_validate(result)
        return result

    result = await manager.restart_all()
    if result.get("status") == "success":
        return RestartServerResult.model_validate(result)
    return result
