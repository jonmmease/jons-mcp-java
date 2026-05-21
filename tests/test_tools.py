"""Public MCP tool contract tests with fake manager/client objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jons_mcp_java.manager import ClientStatus
from jons_mcp_java.server import _ManagerHolder
from jons_mcp_java.tools import diagnostics, document_symbols, hover, workspace_symbols
from jons_mcp_java.tools.navigation import definition


class FakeClient:
    def __init__(self, response: Any = None):
        self.response = response
        self.opened: list[Path] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def ensure_file_open(self, path: Path) -> bool:
        self.opened.append(path)
        return True

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        return self.response


class FakeManager:
    def __init__(self, workspace_root: Path, status: ClientStatus):
        self.workspace_root = workspace_root
        self.status = status
        self.lookup_paths: list[Path] = []
        self.waiter_created = False

    async def get_client_for_file_with_status(self, path: Path) -> ClientStatus:
        self.lookup_paths.append(path)
        return self.status

    def get_initialized_client(self) -> ClientStatus:
        return self.status

    def create_diagnostics_waiter(self, path: Path) -> object:
        self.waiter_created = True
        return object()

    def cancel_diagnostics_waiter(self, path: Path, future: object) -> None:
        return None

    async def wait_for_diagnostics(self, path: Path, future: object) -> list[dict[str, Any]]:
        return [{"message": "fresh", "range": {"start": {"line": 1, "character": 2}}}]

    def get_diagnostics(self, path: Path) -> list[dict[str, Any]]:
        return []

    def get_all_diagnostics(self) -> dict[str, list[dict[str, Any]]]:
        return {}


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "repo"
    src = workspace / "src"
    src.mkdir(parents=True)
    java_file = src / "Main.java"
    java_file.write_text("class Main {}\n", encoding="utf-8")
    return workspace, java_file


@pytest.mark.asyncio
async def test_navigation_tool_validates_position_before_manager_lookup(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    manager = FakeManager(workspace, ClientStatus(None, "error", "unused"))
    _ManagerHolder.instance = manager  # type: ignore[assignment]

    result = await hover(str(java_file), -1, 0)

    assert result["status"] == "error"
    assert result["error"]["type"] == "invalid_position"
    assert manager.lookup_paths == []


@pytest.mark.asyncio
async def test_file_tool_rejects_outside_workspace_before_client_lookup(
    tmp_path: Path,
) -> None:
    workspace, _java_file = make_workspace(tmp_path)
    outside = tmp_path / "Outside.java"
    outside.write_text("class Outside {}\n", encoding="utf-8")
    manager = FakeManager(workspace, ClientStatus(None, "error", "unused"))
    _ManagerHolder.instance = manager  # type: ignore[assignment]

    result = await document_symbols(str(outside))

    assert result["status"] == "error"
    assert result["error"]["type"] == "path_outside_workspace"
    assert manager.lookup_paths == []


@pytest.mark.asyncio
async def test_file_tool_returns_initializing_status(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    status = ClientStatus(
        None,
        "initializing",
        "Starting project initialization; please retry shortly.",
        project=str(workspace),
    )
    _ManagerHolder.instance = FakeManager(workspace, status)  # type: ignore[assignment]

    result = await document_symbols(str(java_file))

    assert result == {
        "status": "initializing",
        "message": status.message,
        "project": str(workspace),
    }


@pytest.mark.asyncio
async def test_file_tool_returns_startup_failure(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    status = ClientStatus(
        None,
        "error",
        "JDT.LS not found",
        project=str(workspace),
        error_type="project_startup_failed",
    )
    _ManagerHolder.instance = FakeManager(workspace, status)  # type: ignore[assignment]

    result = await document_symbols(str(java_file))

    assert result["status"] == "error"
    assert result["error"]["type"] == "project_startup_failed"


@pytest.mark.asyncio
async def test_definition_success_preserves_locations_and_marks_workspace(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            "uri": java_file.resolve().as_uri(),
            "range": {
                "start": {"line": 3, "character": 4},
                "end": {"line": 3, "character": 8},
            },
        }
    )
    status = ClientStatus(client, "ready", "ready", project=str(workspace))
    _ManagerHolder.instance = FakeManager(workspace, status)  # type: ignore[assignment]

    result = await definition("src/Main.java", 1, 2)

    assert result["locations"][0]["path"] == str(java_file.resolve())
    assert result["locations"][0]["in_workspace"] is True
    assert client.opened == [java_file.resolve()]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_public_manager_method(tmp_path: Path) -> None:
    workspace, _java_file = make_workspace(tmp_path)
    client = FakeClient([])
    status = ClientStatus(client, "ready", "ready", project=str(workspace))
    _ManagerHolder.instance = FakeManager(workspace, status)  # type: ignore[assignment]

    result = await workspace_symbols("Main")

    assert result == {"symbols": []}
    assert client.requests[0][0] == "workspace/symbol"


@pytest.mark.asyncio
async def test_diagnostics_waits_after_document_notification(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient()
    status = ClientStatus(client, "ready", "ready", project=str(workspace))
    manager = FakeManager(workspace, status)
    _ManagerHolder.instance = manager  # type: ignore[assignment]

    result = await diagnostics(str(java_file))

    assert manager.waiter_created is True
    assert result["diagnostics"][0]["message"] == "fresh"
