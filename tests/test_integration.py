"""Opt-in integration tests against a real JDT.LS process."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from jons_mcp_java.constants import (
    LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    LSP_TEXT_DOCUMENT_HOVER,
)
from jons_mcp_java.manager import JdtlsClientManager
from jons_mcp_java.utils import path_to_uri


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_jdtls_startup_hover_symbols_diagnostics_and_restart(
    tmp_path: Path,
) -> None:
    if os.environ.get("JONS_MCP_JAVA_RUN_INTEGRATION") != "1":
        pytest.skip("Set JONS_MCP_JAVA_RUN_INTEGRATION=1 to run real JDT.LS tests")

    project = tmp_path / "demo"
    src = project / "src" / "main" / "java" / "demo"
    src.mkdir(parents=True)
    (project / "settings.gradle").write_text(
        'pluginManagement { repositories { gradlePluginPortal() } }\n'
        'dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS) }\n'
        'rootProject.name = "demo"\n',
        encoding="utf-8",
    )
    (project / "build.gradle").write_text(
        "plugins { id 'java' }\n"
        "repositories { mavenCentral() }\n",
        encoding="utf-8",
    )
    java_file = src / "App.java"
    java_file.write_text(
        "package demo;\n\npublic class App { public String message() { return \"ok\"; } }\n",
        encoding="utf-8",
    )

    manager = JdtlsClientManager(project)
    manager.discover_projects()
    client = await manager.get_client_for_file(java_file)

    await client.ensure_file_open(java_file)
    symbol_response = await client.request(
        LSP_TEXT_DOCUMENT_DOCUMENT_SYMBOL,
        {"textDocument": {"uri": path_to_uri(java_file)}},
    )
    hover_response: Any = await client.request(
        LSP_TEXT_DOCUMENT_HOVER,
        {
            "textDocument": {"uri": path_to_uri(java_file)},
            "position": {"line": 2, "character": 32},
        },
    )

    waiter = manager.create_diagnostics_waiter(java_file)
    java_file.write_text(
        "package demo;\n\npublic class App { MissingType value; }\n",
        encoding="utf-8",
    )
    changed = await client.ensure_file_open(java_file)
    diagnostics = (
        await manager.wait_for_diagnostics(java_file, waiter, timeout=10)
        if changed
        else manager.get_diagnostics(java_file)
    )

    restart_result = await manager.restart_all()

    assert isinstance(symbol_response, list)
    assert hover_response is None or isinstance(hover_response, dict)
    assert isinstance(diagnostics, list)
    assert restart_result["status"] == "success"
