"""Opt-in integration tests against a real JDT.LS process."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jons_mcp_java.manager import JdtlsClientManager
from jons_mcp_java.schemas import (
    DiagnosticsResult,
    DocumentSymbolsResult,
    RenamePreviewError,
    RenamePreviewResult,
    RestartServerResult,
    SymbolInfoResult,
)
from jons_mcp_java.server import _ManagerHolder
from jons_mcp_java.tools import (
    diagnostics,
    document_symbols,
    preview_rename,
    restart_server,
    symbol_info,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_jdtls_startup_symbol_info_rename_diagnostics_and_restart(
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
    _ManagerHolder.instance = manager
    manager.discover_projects()
    await manager.get_client_for_file(java_file)

    symbol_response = await document_symbols(str(java_file), limit=10)
    info_response = await symbol_info(str(java_file), 3, 34)
    rename_response = await preview_rename(str(java_file), 3, 14, "Application")

    java_file.write_text(
        "package demo;\n\npublic class App { MissingType value; }\n",
        encoding="utf-8",
    )
    diagnostics_response = await diagnostics(str(java_file), limit=10)
    restart_result = await restart_server()

    assert isinstance(symbol_response, DocumentSymbolsResult)
    assert isinstance(info_response, SymbolInfoResult)
    assert isinstance(rename_response, RenamePreviewResult | RenamePreviewError)
    assert isinstance(diagnostics_response, DiagnosticsResult)
    assert isinstance(restart_result, RestartServerResult)
