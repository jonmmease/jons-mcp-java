"""MCP tools for Java language support."""

from jons_mcp_java.tools.navigation import (
    definition,
    implementation,
    references,
    type_definition,
)
from jons_mcp_java.tools.symbols import document_symbols, workspace_symbols
from jons_mcp_java.tools.diagnostics import diagnostics
from jons_mcp_java.tools.info import hover

__all__ = [
    "definition",
    "references",
    "implementation",
    "type_definition",
    "document_symbols",
    "workspace_symbols",
    "diagnostics",
    "hover",
]
