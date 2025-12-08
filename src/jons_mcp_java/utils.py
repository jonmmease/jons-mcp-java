"""Utility functions for jons-mcp-java."""

import hashlib
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


def path_to_uri(path: str | Path) -> str:
    """Convert a file path to a file:// URI."""
    if isinstance(path, str):
        path = Path(path)

    # Resolve to absolute path
    path = path.resolve()

    # Convert to URI format
    # On Unix, paths start with / so we get file:///
    path_str = str(path)
    if not path_str.startswith("/"):
        path_str = "/" + path_str

    # Quote special characters but preserve /
    encoded = quote(path_str, safe="/")
    return f"file://{encoded}"


def uri_to_path(uri: str) -> Path:
    """Convert a file:// URI to a file path."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected file:// URI, got: {uri}")

    # Decode percent-encoded characters
    path_str = unquote(parsed.path)
    return Path(path_str)


def format_locations(response: dict | list | None) -> dict:
    """
    Normalize LSP Location response to a consistent format.

    LSP methods like definition can return:
    - null/None
    - Single Location object
    - Array of Location objects
    - Array of LocationLink objects

    This normalizes to: {"locations": [...]}
    """
    if response is None:
        return {"locations": []}

    if isinstance(response, dict):
        # Single Location or LocationLink
        return {"locations": [_normalize_location(response)]}

    if isinstance(response, list):
        return {"locations": [_normalize_location(loc) for loc in response]}

    return {"locations": []}


def _normalize_location(loc: dict) -> dict:
    """Normalize a Location or LocationLink to a common format."""
    # LocationLink has targetUri/targetRange, Location has uri/range
    if "targetUri" in loc:
        # LocationLink
        uri = loc["targetUri"]
        range_obj = loc.get("targetSelectionRange") or loc.get("targetRange", {})
    else:
        # Location
        uri = loc.get("uri", "")
        range_obj = loc.get("range", {})

    # Convert URI to path for easier consumption
    try:
        path = str(uri_to_path(uri))
    except ValueError:
        path = uri

    start = range_obj.get("start", {})
    end = range_obj.get("end", {})

    return {
        "path": path,
        "uri": uri,
        "line": start.get("line", 0),
        "character": start.get("character", 0),
        "end_line": end.get("line", 0),
        "end_character": end.get("character", 0),
    }


def get_workspace_data_dir(project_root: Path) -> Path:
    """
    Generate unique workspace data directory for a project.

    Each JDT.LS instance requires its own -data directory.
    We hash the project path to avoid conflicts.
    """
    path_hash = hashlib.md5(str(project_root.resolve()).encode()).hexdigest()[:8]
    project_name = project_root.name
    return Path.home() / ".cache" / "jdtls-workspaces" / f"{project_name}-{path_hash}"


def format_symbol(symbol: dict, include_children: bool = True) -> dict:
    """Format a DocumentSymbol or SymbolInformation to a common format."""
    # DocumentSymbol has range, SymbolInformation has location
    if "location" in symbol:
        # SymbolInformation
        loc = symbol["location"]
        uri = loc.get("uri", "")
        range_obj = loc.get("range", {})
        try:
            path = str(uri_to_path(uri))
        except ValueError:
            path = uri
    else:
        # DocumentSymbol (no path, just range within current file)
        path = None
        range_obj = symbol.get("range", {})

    start = range_obj.get("start", {})

    result = {
        "name": symbol.get("name", ""),
        "kind": symbol.get("kind", 0),
        "kind_name": SYMBOL_KINDS.get(symbol.get("kind", 0), "Unknown"),
        "line": start.get("line", 0),
        "character": start.get("character", 0),
    }

    if path:
        result["path"] = path

    # Include container name if present (SymbolInformation)
    if "containerName" in symbol:
        result["container"] = symbol["containerName"]

    # Include children if present (DocumentSymbol hierarchy)
    if include_children and "children" in symbol:
        result["children"] = [
            format_symbol(child, include_children=True)
            for child in symbol["children"]
        ]

    return result


# LSP Symbol kinds (from LSP spec)
SYMBOL_KINDS = {
    1: "File",
    2: "Module",
    3: "Namespace",
    4: "Package",
    5: "Class",
    6: "Method",
    7: "Property",
    8: "Field",
    9: "Constructor",
    10: "Enum",
    11: "Interface",
    12: "Function",
    13: "Variable",
    14: "Constant",
    15: "String",
    16: "Number",
    17: "Boolean",
    18: "Array",
    19: "Object",
    20: "Key",
    21: "Null",
    22: "EnumMember",
    23: "Struct",
    24: "Event",
    25: "Operator",
    26: "TypeParameter",
}
