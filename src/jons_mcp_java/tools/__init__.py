"""MCP tools for Java language support."""

from jons_mcp_java.tools.diagnostics import diagnostics
from jons_mcp_java.tools.extensions import restart_server
from jons_mcp_java.tools.info import symbol_info
from jons_mcp_java.tools.navigation import (
    definition,
    implementation,
    references,
    type_definition,
)
from jons_mcp_java.tools.refactor import preview_rename
from jons_mcp_java.tools.symbols import document_symbols, workspace_symbols

__all__ = [
    "definition",
    "references",
    "implementation",
    "type_definition",
    "document_symbols",
    "workspace_symbols",
    "diagnostics",
    "symbol_info",
    "preview_rename",
    "restart_server",
]
