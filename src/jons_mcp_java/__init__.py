"""MCP server providing Java development capabilities through Eclipse JDT.LS."""

import argparse
import logging
import os
import sys

from jons_mcp_java.server import mcp

__version__ = "0.1.0"


def main() -> None:
    """Entry point for the MCP server."""
    parser = argparse.ArgumentParser(description="Run the jons-mcp-java MCP server.")
    parser.add_argument(
        "workspace_root",
        nargs="?",
        help="Java workspace root. Overrides JONS_MCP_JAVA_WORKSPACE.",
    )
    args = parser.parse_args()
    if args.workspace_root:
        os.environ["JONS_MCP_JAVA_WORKSPACE"] = args.workspace_root

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run()


__all__ = ["main", "mcp"]
