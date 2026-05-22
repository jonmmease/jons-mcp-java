"""Public MCP tool contract tests with fake manager/client objects."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DEFINITION,
    LSP_TEXT_DOCUMENT_HOVER,
    LSP_TEXT_DOCUMENT_PREPARE_RENAME,
    LSP_TEXT_DOCUMENT_REFERENCES,
    LSP_TEXT_DOCUMENT_RENAME,
    LSP_WORKSPACE_SYMBOL,
)
from jons_mcp_java.manager import ClientStatus
from jons_mcp_java.schemas import (
    DiagnosticsResult,
    DocumentSymbolsResult,
    NavigationResult,
    ReferencesResult,
    RenamePreviewError,
    RenamePreviewResult,
    RestartServerResult,
    SymbolInfoResult,
    WorkspaceSymbolsResult,
)
from jons_mcp_java.server import _ManagerHolder
from jons_mcp_java.tools import (
    definition,
    diagnostics,
    document_symbols,
    preview_rename,
    references,
    restart_server,
    symbol_info,
    workspace_symbols,
)


class FakeClient:
    def __init__(
        self,
        responses: Any = None,
        *,
        open_changed: bool = True,
        open_exception: Exception | None = None,
    ):
        self.responses = responses
        self.open_changed = open_changed
        self.open_exception = open_exception
        self.opened: list[Path] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def ensure_file_open(self, path: Path) -> bool:
        self.opened.append(path)
        if self.open_exception is not None:
            raise self.open_exception
        return self.open_changed

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        self.requests.append((method, params))
        if isinstance(self.responses, dict) and method in self.responses:
            response = self.responses[method]
        else:
            response = self.responses
        if isinstance(response, Exception):
            raise response
        return response


class FakeManager:
    def __init__(self, workspace_root: Path, status: ClientStatus):
        self.workspace_root = workspace_root.resolve()
        self.status = status
        self.lookup_paths: list[Path] = []
        self.waiter_created = False
        self.restart_paths: list[Path] = []
        self.restart_all_called = False

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

    async def wait_for_diagnostics(
        self,
        path: Path,
        future: object,
    ) -> list[dict[str, Any]]:
        return [
            {
                "message": "fresh",
                "severity": 1,
                "range": {
                    "start": {"line": 0, "character": 1},
                    "end": {"line": 0, "character": 6},
                },
            }
        ]

    def get_diagnostics(self, path: Path) -> list[dict[str, Any]]:
        return [
            {
                "message": "cached",
                "severity": 2,
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 4},
                },
            }
        ]

    async def restart_project_for_file(self, path: Path) -> dict[str, Any]:
        self.restart_paths.append(path)
        return {
            "status": "success",
            "message": "Restarted server for project",
            "project": str(self.workspace_root),
            "wasRunning": True,
        }

    async def restart_all(self) -> dict[str, Any]:
        self.restart_all_called = True
        return {
            "status": "success",
            "message": "Restarted 1 server(s)",
            "projects": [str(self.workspace_root)],
        }


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "repo"
    src = workspace / "src"
    src.mkdir(parents=True)
    java_file = src / "Main.java"
    java_file.write_text("class Main {}\n", encoding="utf-8")
    return workspace, java_file


def install_manager(
    workspace: Path,
    client: FakeClient,
    *,
    status: str = "ready",
) -> FakeManager:
    manager = FakeManager(
        workspace,
        ClientStatus(client, status, status, project=str(workspace)),
    )
    _ManagerHolder.instance = manager  # type: ignore[assignment]
    return manager


@pytest.mark.asyncio
async def test_position_tools_validate_one_based_position_before_manager_lookup(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    manager = install_manager(workspace, FakeClient())

    result = await symbol_info(str(java_file), 0, 1)

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error"]["type"] == "invalid_position"
    assert manager.lookup_paths == []


@pytest.mark.asyncio
async def test_definition_uses_one_based_inputs_and_strict_navigation_shape(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            "uri": java_file.resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 1},
                "end": {"line": 0, "character": 5},
            },
        }
    )
    install_manager(workspace, client)

    result = await definition("src/Main.java", 1, 2)

    assert isinstance(result, NavigationResult)
    assert result.totalItems == 1
    assert result.items[0].uri == java_file.resolve().as_uri()
    assert result.items[0].range is not None
    assert result.items[0].range.start.line == 1
    assert result.items[0].range.start.character == 2
    assert result.items[0].inWorkspace is True
    assert client.requests[0] == (
        LSP_TEXT_DOCUMENT_DEFINITION,
        {
            "textDocument": {"uri": java_file.resolve().as_uri()},
            "position": {"line": 0, "character": 1},
        },
    )
    dumped = result.model_dump()
    assert "locations" not in dumped
    assert "line" not in dumped["items"][0]
    assert "in_workspace" not in dumped["items"][0]


@pytest.mark.asyncio
async def test_references_returns_paginated_source_locations(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    other = workspace / "src" / "Other.java"
    other.write_text("class Other {}\n", encoding="utf-8")
    client = FakeClient(
        [
            {
                "uri": other.resolve().as_uri(),
                "range": {
                    "start": {"line": 2, "character": 3},
                    "end": {"line": 2, "character": 7},
                },
            },
            {
                "uri": java_file.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 1},
                    "end": {"line": 0, "character": 5},
                },
            },
        ]
    )
    install_manager(workspace, client)

    result = await references("src/Main.java", 1, 2, limit=1, offset=1)

    assert isinstance(result, ReferencesResult)
    assert result.totalItems == 2
    assert result.offset == 1
    assert result.limit == 1
    assert result.hasMore is False
    assert result.items[0].offset == 1
    assert result.items[0].uri == other.resolve().as_uri()
    assert client.requests[0][0] == LSP_TEXT_DOCUMENT_REFERENCES


@pytest.mark.asyncio
async def test_document_symbols_flatten_and_page_without_legacy_keys(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        [
            {
                "name": "Main",
                "kind": 5,
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 10},
                },
                "selectionRange": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 10},
                },
                "children": [
                    {
                        "name": "run",
                        "kind": 6,
                        "range": {
                            "start": {"line": 1, "character": 2},
                            "end": {"line": 1, "character": 8},
                        },
                    }
                ],
            }
        ]
    )
    install_manager(workspace, client)

    result = await document_symbols(str(java_file), limit=10)

    assert isinstance(result, DocumentSymbolsResult)
    assert result.totalItems == 2
    assert [item.name for item in result.items] == ["Main", "run"]
    assert result.items[1].containerName == "Main"
    assert result.items[0].range is not None
    assert result.items[0].range.start.line == 1
    dumped = result.model_dump()
    assert "symbols" not in dumped
    assert "kind_name" not in dumped["items"][0]


@pytest.mark.asyncio
async def test_workspace_symbols_uses_public_manager_method_and_paginates(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        [
            {
                "name": "Main",
                "kind": 5,
                "containerName": "demo",
                "location": {
                    "uri": java_file.resolve().as_uri(),
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 4},
                    },
                },
            }
        ]
    )
    install_manager(workspace, client)

    result = await workspace_symbols("Main", limit=1)

    assert isinstance(result, WorkspaceSymbolsResult)
    assert result.totalItems == 1
    assert result.items[0].uri == java_file.resolve().as_uri()
    assert result.items[0].containerName == "demo"
    assert client.requests[0][0] == LSP_WORKSPACE_SYMBOL


@pytest.mark.asyncio
async def test_symbol_info_returns_content_and_one_based_range(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            "contents": {"kind": "markdown", "value": "class Main"},
            "range": {
                "start": {"line": 0, "character": 6},
                "end": {"line": 0, "character": 10},
            },
        }
    )
    install_manager(workspace, client)

    result = await symbol_info(str(java_file), 1, 7)

    assert isinstance(result, SymbolInfoResult)
    assert result.content == "class Main"
    assert result.range is not None
    assert result.range.start.line == 1
    assert result.range.start.character == 7
    assert client.requests[0][0] == LSP_TEXT_DOCUMENT_HOVER


@pytest.mark.asyncio
async def test_diagnostics_waits_after_document_notification_and_paginates(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient()
    manager = install_manager(workspace, client)

    result = await diagnostics(str(java_file), limit=1)

    assert isinstance(result, DiagnosticsResult)
    assert manager.waiter_created is True
    assert result.totalItems == 1
    assert result.items[0].message == "fresh"
    assert result.items[0].range is not None
    assert result.items[0].range.start.line == 1
    assert result.items[0].severityName == "error"


@pytest.mark.asyncio
async def test_document_sync_error_fails_closed_before_lsp_request(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(open_exception=OSError("sync failed"))
    install_manager(workspace, client)

    result = await symbol_info(str(java_file), 1, 1)

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error"]["message"] == "sync failed"
    assert client.requests == []


@pytest.mark.asyncio
async def test_preview_rename_normalizes_changes_without_writing_files(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    before = java_file.read_text(encoding="utf-8")
    client = FakeClient(
        {
            LSP_TEXT_DOCUMENT_PREPARE_RENAME: {
                "range": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 10},
                }
            },
            LSP_TEXT_DOCUMENT_RENAME: {
                "changes": {
                    java_file.resolve().as_uri(): [
                        {
                            "range": {
                                "start": {"line": 0, "character": 6},
                                "end": {"line": 0, "character": 10},
                            },
                            "newText": "Renamed",
                        }
                    ]
                }
            },
        }
    )
    install_manager(workspace, client)

    result = await preview_rename(str(java_file), 1, 7, "Renamed")

    assert isinstance(result, RenamePreviewResult)
    assert result.totalEdits == 1
    assert result.edits[0].range.start.line == 1
    assert result.edits[0].range.start.character == 7
    assert result.edits[0].inWorkspace is True
    assert java_file.read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_preview_rename_normalizes_document_changes(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            LSP_TEXT_DOCUMENT_PREPARE_RENAME: {
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": 4},
                }
            },
            LSP_TEXT_DOCUMENT_RENAME: {
                "documentChanges": [
                    {
                        "textDocument": {"uri": java_file.resolve().as_uri()},
                        "edits": [
                            {
                                "range": {
                                    "start": {"line": 1, "character": 0},
                                    "end": {"line": 1, "character": 4},
                                },
                                "newText": "Renamed",
                            }
                        ],
                    }
                ]
            },
        }
    )
    install_manager(workspace, client)

    result = await preview_rename(str(java_file), 1, 1, "Renamed")

    assert isinstance(result, RenamePreviewResult)
    assert result.edits[0].range.start.line == 2
    assert client.requests[0][0] == LSP_TEXT_DOCUMENT_PREPARE_RENAME
    assert client.requests[1][0] == LSP_TEXT_DOCUMENT_RENAME


@pytest.mark.asyncio
async def test_preview_rename_returns_semantic_error_for_empty_result(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            LSP_TEXT_DOCUMENT_PREPARE_RENAME: None,
            LSP_TEXT_DOCUMENT_RENAME: None,
        }
    )
    install_manager(workspace, client)

    result = await preview_rename(str(java_file), 1, 1, "Renamed")

    assert isinstance(result, RenamePreviewError)
    assert result.error == "Symbol cannot be renamed"


@pytest.mark.asyncio
async def test_preview_rename_returns_semantic_error_for_invalid_edit_shape(
    tmp_path: Path,
) -> None:
    workspace, java_file = make_workspace(tmp_path)
    client = FakeClient(
        {
            LSP_TEXT_DOCUMENT_PREPARE_RENAME: {"range": {}},
            LSP_TEXT_DOCUMENT_RENAME: {"unsupported": []},
        }
    )
    install_manager(workspace, client)

    result = await preview_rename(str(java_file), 1, 1, "Renamed")

    assert isinstance(result, RenamePreviewError)
    assert result.error == "Rename returned unsupported edit shape"


@pytest.mark.asyncio
async def test_restart_server_returns_structured_result(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    manager = install_manager(workspace, FakeClient())

    one_project = await restart_server(str(java_file))
    all_projects = await restart_server()

    assert isinstance(one_project, RestartServerResult)
    assert one_project.wasRunning is True
    assert manager.restart_paths == [java_file.resolve()]
    assert isinstance(all_projects, RestartServerResult)
    assert all_projects.projects == [str(workspace.resolve())]
    assert manager.restart_all_called is True


@pytest.mark.parametrize(
    "call_tool",
    [
        pytest.param(lambda path: definition(path, 1, 1), id="definition"),
        pytest.param(lambda path: references(path, 1, 1), id="references"),
        pytest.param(lambda path: document_symbols(path), id="document_symbols"),
        pytest.param(lambda path: diagnostics(path), id="diagnostics"),
        pytest.param(lambda path: symbol_info(path, 1, 1), id="symbol_info"),
        pytest.param(lambda path: preview_rename(path, 1, 1, "Renamed"), id="preview_rename"),
        pytest.param(lambda path: restart_server(path), id="restart_server"),
        pytest.param(lambda path: workspace_symbols("Main", file_path=path), id="workspace_symbols"),
    ],
)
@pytest.mark.asyncio
async def test_file_taking_tools_reject_outside_workspace_before_client_lookup(
    tmp_path: Path,
    call_tool: Callable[[str], Awaitable[Any]],
) -> None:
    workspace, _java_file = make_workspace(tmp_path)
    outside = tmp_path / "Outside.java"
    outside.write_text("class Outside {}\n", encoding="utf-8")
    manager = install_manager(workspace, FakeClient())

    result = await call_tool(str(outside))

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error"]["type"] == "path_outside_workspace"
    assert manager.lookup_paths == []
    assert manager.restart_paths == []


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

    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error"]["type"] == "project_startup_failed"
