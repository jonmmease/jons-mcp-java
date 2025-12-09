"""FastMCP server with lifespan management."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

from jons_mcp_java.manager import JdtlsClientManager

logger = logging.getLogger(__name__)


class _ManagerHolder:
    """Holder class to allow tools to access the manager after lifespan init."""
    instance: JdtlsClientManager | None = None


def get_manager() -> JdtlsClientManager | None:
    """Get the current manager instance."""
    return _ManagerHolder.instance


@asynccontextmanager
async def lifespan(app: FastMCP):
    """Lifespan context manager for the MCP server."""
    # Get workspace root from environment or arguments
    workspace_root = os.environ.get("JONS_MCP_JAVA_WORKSPACE")
    if not workspace_root:
        # Default to current directory
        workspace_root = os.getcwd()

    workspace_path = Path(workspace_root).resolve()
    logger.info(f"Starting jons-mcp-java with workspace: {workspace_path}")

    # Initialize manager
    manager = JdtlsClientManager(workspace_path)
    _ManagerHolder.instance = manager

    # Discover projects
    projects = manager.discover_projects()
    if projects:
        logger.info(f"Discovered projects: {[str(p) for p in projects]}")
    else:
        logger.warning(f"No Gradle projects found in {workspace_path}")

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
)


# Import tools to register them
from jons_mcp_java.tools import navigation, symbols, diagnostics, info  # noqa: E402, F401
