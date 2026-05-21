"""Shared helpers for public MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jons_mcp_java.client import JdtlsClient
from jons_mcp_java.exceptions import JdtlsError, LspRequestError
from jons_mcp_java.manager import ClientStatus, JdtlsClientManager
from jons_mcp_java.paths import PathValidationError, ResolvedPath, resolve_user_path
from jons_mcp_java.server import get_manager


@dataclass(frozen=True)
class FileToolContext:
    """Resolved state needed by file-backed tools."""

    manager: JdtlsClientManager
    client: JdtlsClient
    resolved: ResolvedPath
    project: str


def error_response(
    error_type: str,
    message: str,
    *,
    path: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "type": error_type,
        "message": message,
    }
    if path is not None:
        error["path"] = path
    if project is not None:
        error["project"] = project
    return {"status": "error", "error": error}


def manager_or_error() -> tuple[JdtlsClientManager | None, dict[str, Any] | None]:
    manager = get_manager()
    if manager is None:
        return None, error_response("server_not_initialized", "Server not initialized.")
    return manager, None


def validate_position(line: int, character: int) -> dict[str, Any] | None:
    if not isinstance(line, int) or line < 0:
        return error_response(
            "invalid_position",
            "line must be a non-negative integer.",
        )
    if not isinstance(character, int) or character < 0:
        return error_response(
            "invalid_position",
            "character must be a non-negative integer.",
        )
    return None


async def prepare_file_tool(
    file_path: str,
    *,
    open_file: bool = True,
) -> tuple[FileToolContext | None, dict[str, Any] | None]:
    manager, error = manager_or_error()
    if error is not None or manager is None:
        return None, error

    try:
        resolved = resolve_user_path(file_path, manager.workspace_root, must_exist=True)
    except PathValidationError as exc:
        return None, error_response(exc.error_type, exc.message, path=exc.path)

    status = await manager.get_client_for_file_with_status(resolved.path)
    if status.status == "initializing":
        return None, {
            "status": "initializing",
            "message": status.message,
            "project": status.project,
        }

    if status.status != "ready" or status.client is None:
        return None, _client_status_error(status, str(resolved.path))

    if open_file:
        try:
            await status.client.ensure_file_open(resolved.path)
        except FileNotFoundError:
            return None, error_response(
                "path_not_found",
                "Path does not exist.",
                path=file_path,
                project=status.project,
            )
        except (JdtlsError, OSError) as exc:
            return None, exception_response(exc, path=str(resolved.path), project=status.project)

    return (
        FileToolContext(
            manager=manager,
            client=status.client,
            resolved=resolved,
            project=status.project or "",
        ),
        None,
    )


def _client_status_error(status: ClientStatus, path: str | None = None) -> dict[str, Any]:
    return error_response(
        status.error_type or status.status,
        status.message,
        path=path,
        project=status.project,
    )


def exception_response(
    exc: Exception,
    *,
    path: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    if isinstance(exc, LspRequestError):
        return error_response(
            "lsp_request_failed",
            str(exc),
            path=path,
            project=project,
        )
    if isinstance(exc, JdtlsError):
        return error_response(
            exc.__class__.__name__,
            str(exc),
            path=path,
            project=project,
        )
    return error_response(
        "tool_failed",
        str(exc) or exc.__class__.__name__,
        path=path,
        project=project,
    )


def workspace_path_or_error(
    manager: JdtlsClientManager,
    file_path: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        resolved = resolve_user_path(file_path, manager.workspace_root, must_exist=True)
    except PathValidationError as exc:
        return None, error_response(exc.error_type, exc.message, path=exc.path)
    return resolved.path, None
