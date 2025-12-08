"""MCP server providing Java development capabilities through Eclipse JDT.LS."""

from jons_mcp_java.server import mcp

__version__ = "0.1.0"


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


__all__ = ["main", "mcp"]
