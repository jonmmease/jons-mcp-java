"""Manager startup, routing, restart, and diagnostics state tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import jons_mcp_java.manager as manager_module
from jons_mcp_java.manager import JdtlsClientManager
from jons_mcp_java.utils import path_to_uri


class FakeJdtlsClient:
    fail_start = False
    instances: list[FakeJdtlsClient] = []

    def __init__(self, project_root: Path, workspace_data_dir: Path):
        self.project_root = project_root
        self.workspace_data_dir = workspace_data_dir
        self.handlers: dict[str, Any] = {}
        self.is_initialized = False
        self.shutdown_called = False
        FakeJdtlsClient.instances.append(self)

    def on_notification(self, method: str, handler: Any) -> None:
        self.handlers[method] = handler

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("boom")
        self.is_initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True
        self.is_initialized = False


@pytest.fixture(autouse=True)
def reset_fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeJdtlsClient.fail_start = False
    FakeJdtlsClient.instances = []
    monkeypatch.setattr(manager_module, "JdtlsClient", FakeJdtlsClient)


def make_gradle_project(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "repo"
    project = workspace / "app"
    src = project / "src"
    src.mkdir(parents=True)
    (project / "build.gradle").write_text("", encoding="utf-8")
    java_file = src / "Main.java"
    java_file.write_text("class Main {}\n", encoding="utf-8")
    return workspace, java_file


def test_routes_to_deepest_gradle_project(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    nested = workspace / "services" / "api"
    src = nested / "src"
    src.mkdir(parents=True)
    (workspace / "settings.gradle").write_text("", encoding="utf-8")
    (nested / "build.gradle").write_text("", encoding="utf-8")
    java_file = src / "Main.java"
    java_file.write_text("class Main {}\n", encoding="utf-8")
    manager = JdtlsClientManager(workspace)
    manager.discover_projects()

    project = manager.get_project_for_file(java_file)

    assert project is not None
    assert project.project_root == nested.resolve()


@pytest.mark.asyncio
async def test_background_startup_captures_failure(tmp_path: Path) -> None:
    workspace, java_file = make_gradle_project(tmp_path)
    manager = JdtlsClientManager(workspace)
    manager.discover_projects()
    FakeJdtlsClient.fail_start = True

    status = await manager.get_client_for_file_with_status(java_file)
    project = manager.get_project_for_file(java_file)
    assert status.status == "initializing"
    assert project is not None
    assert project.startup_task is not None
    await project.startup_task

    failed = await manager.get_client_for_file_with_status(java_file)

    assert failed.status == "error"
    assert failed.error_type == "project_startup_failed"
    assert "boom" in failed.message


@pytest.mark.asyncio
async def test_restart_project_clears_runtime_state(tmp_path: Path) -> None:
    workspace, java_file = make_gradle_project(tmp_path)
    manager = JdtlsClientManager(workspace)
    manager.discover_projects()

    client = await manager.get_client_for_file(java_file)
    project = manager.get_project_for_file(java_file)
    assert project is not None
    project.diagnostics[path_to_uri(java_file)] = [{"message": "old"}]

    result = await manager.restart_project_for_file(java_file)

    assert result["status"] == "success"
    assert result["wasRunning"] is True
    assert project.client is None
    assert project.diagnostics == {}
    assert client.shutdown_called is True


@pytest.mark.asyncio
async def test_diagnostics_waiter_receives_notification(tmp_path: Path) -> None:
    workspace, java_file = make_gradle_project(tmp_path)
    manager = JdtlsClientManager(workspace)
    manager.discover_projects()
    await manager.get_client_for_file(java_file)
    project = manager.get_project_for_file(java_file)
    assert project is not None

    waiter = manager.create_diagnostics_waiter(java_file)
    assert waiter is not None
    diagnostic = {"message": "fresh"}

    manager._on_diagnostics(
        project,
        {"uri": path_to_uri(java_file), "diagnostics": [diagnostic]},
    )

    assert await manager.wait_for_diagnostics(java_file, waiter) == [diagnostic]
