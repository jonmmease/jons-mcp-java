"""MCP server providing Java development capabilities through Eclipse JDT.LS."""

import logging
import sys

from jons_mcp_java.server import mcp

__version__ = "0.1.0"


def main() -> None:
    """Entry point for the MCP server."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run()


__all__ = ["main", "mcp"]
