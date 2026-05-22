"""FastMCP server with lifespan management."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from jons_mcp_java.manager import JdtlsClientManager

logger = logging.getLogger(__name__)


SERVER_INSTRUCTIONS = """
Java language intelligence server backed by Eclipse JDT.LS.

The configured workspace root is the filesystem security boundary. Relative
tool paths are resolved from that workspace root, not from the MCP process
current working directory. Tools accept workspace-relative paths, absolute
in-workspace paths, and local file:// URIs.

Tools that accept or return line and character positions use one-based
positions, matching editor and Read output. Convert only when talking directly
to LSP internals.

Recommended workflow:
- Use document_symbols to find one-based ranges when you do not already know a
  symbol position.
- Use symbol_info for hover-style type, signature, and documentation text.
- Use definition, type_definition, implementation, and references for semantic
  navigation.
- Use diagnostics for fresh file-scoped compiler diagnostics after edits.
- Use preview_rename to inspect rename edits. It never writes files.
- Use restart_server only when JDT.LS appears stale or after project
  configuration changes.
"""


class _ManagerHolder:
    """Holder class to allow tools to access the manager after lifespan init."""
    instance: JdtlsClientManager | None = None


def get_manager() -> JdtlsClientManager | None:
    """Get the current manager instance."""
    return _ManagerHolder.instance


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Lifespan context manager for the MCP server."""
    # Get workspace root from environment or arguments
    workspace_root = os.environ.get("JONS_MCP_JAVA_WORKSPACE")
    if not workspace_root:
        # Default to current directory
        workspace_root = os.getcwd()

    workspace_path = Path(workspace_root).resolve()
    logger.info("Starting jons-mcp-java with workspace: %s", workspace_path)

    # Initialize manager
    manager = JdtlsClientManager(workspace_path)
    _ManagerHolder.instance = manager

    # Discover projects
    projects = manager.discover_projects()
    if projects:
        logger.info("Discovered projects: %s", [str(p) for p in projects])
    else:
        logger.warning("No Gradle projects found in %s", workspace_path)

    yield {"manager": manager}

    # Shutdown
    if _ManagerHolder.instance:
        await _ManagerHolder.instance.shutdown_all()
        _ManagerHolder.instance = None
    logger.info("jons-mcp-java shut down")


# Create FastMCP instance
mcp = FastMCP(
    "jons-mcp-java",
    lifespan=lifespan,
    instructions=SERVER_INSTRUCTIONS.strip(),
)


# Import tools to register them
from jons_mcp_java.tools import diagnostics, extensions, info, navigation, refactor, symbols  # noqa: E402, F401, I001
