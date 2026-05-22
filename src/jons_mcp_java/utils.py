"""Utility functions for jons-mcp-java."""

import hashlib
from pathlib import Path
from typing import Any, TypeVar, cast
from urllib.parse import quote, unquote, urlparse

from jons_mcp_java.constants import DEFAULT_LIMIT, DEFAULT_OFFSET
from jons_mcp_java.paths import is_in_workspace
from jons_mcp_java.schemas import (
    DiagnosticItem,
    DocumentSymbolItem,
    NavigationLocation,
    NavigationResult,
    PublicLocationItem,
    RenamePreviewEdit,
    RenamePreviewResult,
)

T = TypeVar("T")


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


def apply_pagination(
    items: list[dict[str, Any]],
    offset: int = DEFAULT_OFFSET,
    limit: int = DEFAULT_LIMIT,
    *,
    add_offset_field: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply stable offset/limit pagination metadata."""
    total_items = len(items)
    start_index = min(offset, total_items)
    end_index = min(start_index + limit, total_items)
    paginated = [item.copy() for item in items[start_index:end_index]]

    if add_offset_field:
        for index, item in enumerate(paginated, start=start_index):
            item["offset"] = index

    has_more = end_index < total_items
    return paginated, {
        "totalItems": total_items,
        "offset": offset,
        "limit": limit,
        "hasMore": has_more,
        "nextOffset": end_index if has_more else None,
    }


def public_position_to_lsp(line: int, character: int) -> dict[str, int]:
    """Convert one-based public positions to zero-based LSP positions."""
    return {"line": line - 1, "character": character - 1}


def lsp_result_to_public(value: T) -> T:
    """Recursively convert LSP position payloads to one-based public positions."""
    if isinstance(value, list):
        return cast(T, [lsp_result_to_public(item) for item in value])
    if isinstance(value, dict):
        if _is_lsp_position(value):
            converted = value.copy()
            converted["line"] = value["line"] + 1
            converted["character"] = value["character"] + 1
            return cast(T, converted)
        return cast(T, {key: lsp_result_to_public(item) for key, item in value.items()})
    return value


def _is_lsp_position(value: dict[str, Any]) -> bool:
    return isinstance(value.get("line"), int) and isinstance(value.get("character"), int)


def uri_in_workspace(uri: str, workspace_root: Path | None) -> bool:
    """Return whether a file URI points inside workspace_root."""
    if workspace_root is None:
        return False
    try:
        return is_in_workspace(uri_to_path(uri), workspace_root)
    except ValueError:
        return False


def normalize_navigation_result(
    response: Any,
    workspace_root: Path | None,
) -> NavigationResult:
    """Normalize LSP Location/LocationLink results for public tools."""
    if not response:
        return NavigationResult(items=[], totalItems=0)

    raw_items = response if isinstance(response, list) else [response]
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for raw_item in raw_items:
        item = _normalize_navigation_item(raw_item, workspace_root)
        if item is None:
            continue
        key = (
            item["uri"],
            repr(item.get("range")),
            repr(item.get("fullRange")),
            repr(item.get("originRange")),
        )
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return NavigationResult.model_validate({"items": items, "totalItems": len(items)})


def _normalize_navigation_item(
    raw_item: Any,
    workspace_root: Path | None,
) -> dict[str, Any] | None:
    if not isinstance(raw_item, dict):
        return None

    target_uri = raw_item.get("targetUri")
    if isinstance(target_uri, str):
        target_range = raw_item.get("targetRange")
        selection_range = raw_item.get("targetSelectionRange") or target_range
        item: dict[str, Any] = {
            "uri": target_uri,
            "inWorkspace": uri_in_workspace(target_uri, workspace_root),
        }
        if isinstance(selection_range, dict):
            item["range"] = lsp_result_to_public(selection_range)
        if isinstance(target_range, dict) and target_range != selection_range:
            item["fullRange"] = lsp_result_to_public(target_range)
        origin_range = raw_item.get("originSelectionRange")
        if isinstance(origin_range, dict):
            item["originRange"] = lsp_result_to_public(origin_range)
        return item

    uri = raw_item.get("uri")
    if isinstance(uri, str):
        item = {
            "uri": uri,
            "inWorkspace": uri_in_workspace(uri, workspace_root),
        }
        range_obj = raw_item.get("range")
        if isinstance(range_obj, dict):
            item["range"] = lsp_result_to_public(range_obj)
        return item

    return None


def location_sort_key(item: dict[str, Any]) -> tuple[str, int, int]:
    """Sort source-location items by URI, line, and character."""
    start = item.get("range", {}).get("start", {})
    return (
        str(item.get("uri", "")),
        _safe_int(start.get("line", 0)),
        _safe_int(start.get("character", 0)),
    )


def normalize_reference_items(
    response: Any,
    workspace_root: Path | None,
) -> list[dict[str, Any]]:
    """Normalize references to paginated source-location item dictionaries."""
    if not response:
        return []

    raw_items = response if isinstance(response, list) else [response]
    items = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        uri = raw_item.get("uri")
        range_obj = raw_item.get("range")
        if not isinstance(uri, str):
            continue
        item: dict[str, Any] = {
            "uri": uri,
            "inWorkspace": uri_in_workspace(uri, workspace_root),
        }
        if isinstance(range_obj, dict):
            item["range"] = lsp_result_to_public(range_obj)
        items.append(item)
    return sorted(items, key=location_sort_key)


def get_workspace_data_dir(project_root: Path) -> Path:
    """
    Generate unique workspace data directory for a project.

    Each JDT.LS instance requires its own -data directory.
    We hash the project path to avoid conflicts.
    """
    path_hash = hashlib.md5(str(project_root.resolve()).encode()).hexdigest()[:8]
    project_name = project_root.name
    return Path.home() / ".cache" / "jdtls-workspaces" / f"{project_name}-{path_hash}"


def normalize_document_symbols(
    response: Any,
    file_uri: str,
    workspace_root: Path | None,
) -> list[dict[str, Any]]:
    """Flatten LSP document symbols into public symbol items."""
    if not isinstance(response, list):
        return []

    items: list[dict[str, Any]] = []
    for symbol in response:
        if isinstance(symbol, dict):
            _append_document_symbol(items, symbol, file_uri, workspace_root, None)
    items.sort(key=symbol_sort_key)
    return items


def _append_document_symbol(
    items: list[dict[str, Any]],
    symbol: dict[str, Any],
    file_uri: str,
    workspace_root: Path | None,
    container_name: str | None,
) -> None:
    item = _normalize_symbol(symbol, file_uri, workspace_root, container_name)
    if item is not None:
        items.append(item)

    children = symbol.get("children")
    next_container = symbol.get("name") if isinstance(symbol.get("name"), str) else None
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _append_document_symbol(
                    items,
                    child,
                    file_uri,
                    workspace_root,
                    next_container or container_name,
                )


def normalize_workspace_symbols(
    response: Any,
    workspace_root: Path | None,
) -> list[dict[str, Any]]:
    """Normalize workspace/symbol results into public symbol items."""
    if not isinstance(response, list):
        return []

    items = []
    for symbol in response:
        if not isinstance(symbol, dict):
            continue
        location = symbol.get("location")
        uri = file_uri_from_location(location)
        if uri is None:
            continue
        item = _normalize_symbol(
            symbol,
            uri,
            workspace_root,
            symbol.get("containerName") if isinstance(symbol.get("containerName"), str) else None,
        )
        if item is not None:
            items.append(item)
    items.sort(key=symbol_sort_key)
    return items


def _normalize_symbol(
    symbol: dict[str, Any],
    file_uri: str,
    workspace_root: Path | None,
    container_name: str | None,
) -> dict[str, Any] | None:
    name = symbol.get("name")
    kind = symbol.get("kind")
    if not isinstance(name, str) or not isinstance(kind, int):
        return None

    location = symbol.get("location")
    range_obj = (
        location.get("range")
        if isinstance(location, dict) and isinstance(location.get("range"), dict)
        else symbol.get("range")
    )
    selection_range = symbol.get("selectionRange")

    item: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "kindName": SYMBOL_KINDS.get(kind, "Unknown"),
        "uri": file_uri,
        "inWorkspace": uri_in_workspace(file_uri, workspace_root),
    }
    if isinstance(range_obj, dict):
        item["range"] = lsp_result_to_public(range_obj)
    if isinstance(selection_range, dict):
        item["selectionRange"] = lsp_result_to_public(selection_range)
    if container_name:
        item["containerName"] = container_name
    return item


def file_uri_from_location(location: Any) -> str | None:
    if not isinstance(location, dict):
        return None
    uri = location.get("uri")
    return uri if isinstance(uri, str) else None


def symbol_sort_key(item: dict[str, Any]) -> tuple[str, int, int, str]:
    start = item.get("range", {}).get("start", {})
    return (
        str(item.get("uri", "")),
        _safe_int(start.get("line", 0)),
        _safe_int(start.get("character", 0)),
        str(item.get("name", "")),
    )


def normalize_hover_content(response: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize LSP hover contents and range."""
    if response is None:
        return None, None
    if not isinstance(response, dict):
        return None, None

    contents = response.get("contents", {})
    content: str | None
    if isinstance(contents, str):
        content = contents
    elif isinstance(contents, dict):
        content = contents.get("value", "") if isinstance(contents.get("value"), str) else ""
    elif isinstance(contents, list):
        parts = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("value")
                if isinstance(value, str):
                    if isinstance(item.get("language"), str):
                        parts.append(f"```{item['language']}\n{value}\n```")
                    else:
                        parts.append(value)
        content = "\n\n".join(parts)
    else:
        content = None

    range_obj = response.get("range")
    public_range = lsp_result_to_public(range_obj) if isinstance(range_obj, dict) else None
    return content, public_range


def normalize_diagnostics(
    uri: str,
    diagnostics: list[dict[str, Any]],
    workspace_root: Path | None,
) -> list[dict[str, Any]]:
    """Normalize LSP diagnostics to public diagnostic items without offsets."""
    items = []
    for diagnostic in diagnostics:
        range_obj = diagnostic.get("range")
        item: dict[str, Any] = {
            "uri": uri,
            "message": str(diagnostic.get("message", "")),
            "severity": diagnostic.get("severity"),
            "severityName": severity_name(diagnostic.get("severity")),
            "source": diagnostic.get("source"),
            "code": diagnostic.get("code"),
            "inWorkspace": uri_in_workspace(uri, workspace_root),
        }
        if isinstance(range_obj, dict):
            item["range"] = lsp_result_to_public(range_obj)
        items.append(item)
    return sorted(items, key=diagnostic_sort_key)


def severity_name(severity: Any) -> str:
    return {
        1: "error",
        2: "warning",
        3: "information",
        4: "hint",
    }.get(severity, "unknown")


def diagnostic_sort_key(item: dict[str, Any]) -> tuple[str, int, int, str, str]:
    start = item.get("range", {}).get("start", {})
    return (
        str(item.get("uri", "")),
        _safe_int(start.get("line", 0)),
        _safe_int(start.get("character", 0)),
        str(item.get("severityName", "")),
        str(item.get("message", "")),
    )


def normalize_rename_preview(
    result: dict[str, Any],
    workspace_root: Path | None,
) -> RenamePreviewResult:
    """Normalize a WorkspaceEdit into a flat rename preview."""
    edits: list[RenamePreviewEdit] = []
    found_edit_container = False

    changes = result.get("changes")
    if isinstance(changes, dict):
        found_edit_container = True
        for uri, uri_edits in changes.items():
            if isinstance(uri, str) and isinstance(uri_edits, list):
                edits.extend(_rename_edits_for_uri(uri, uri_edits, workspace_root))

    document_changes = result.get("documentChanges")
    if isinstance(document_changes, list):
        found_edit_container = True
        for document_change in document_changes:
            if not isinstance(document_change, dict):
                continue
            text_document = document_change.get("textDocument")
            uri = (
                text_document.get("uri")
                if isinstance(text_document, dict)
                else document_change.get("uri")
            )
            uri_edits = document_change.get("edits")
            if isinstance(uri, str) and isinstance(uri_edits, list):
                edits.extend(_rename_edits_for_uri(uri, uri_edits, workspace_root))

    if not found_edit_container:
        raise TypeError("Rename result did not contain edits")

    edits.sort(
        key=lambda edit: (
            edit.uri,
            edit.range.start.line,
            edit.range.start.character,
            edit.range.end.line if edit.range.end else edit.range.start.line,
            edit.range.end.character if edit.range.end else edit.range.start.character,
            edit.newText,
        )
    )
    return RenamePreviewResult(edits=edits, totalEdits=len(edits))


def _rename_edits_for_uri(
    uri: str,
    raw_edits: list[Any],
    workspace_root: Path | None,
) -> list[RenamePreviewEdit]:
    edits = []
    for raw_edit in raw_edits:
        if not isinstance(raw_edit, dict):
            continue
        raw_range = raw_edit.get("range")
        new_text = raw_edit.get("newText")
        if not isinstance(raw_range, dict) or not isinstance(new_text, str):
            continue
        edits.append(
            RenamePreviewEdit.model_validate(
                {
                    "uri": uri,
                    "range": lsp_result_to_public(raw_range),
                    "newText": new_text,
                    "inWorkspace": uri_in_workspace(uri, workspace_root),
                }
            )
        )
    return edits


def public_location_items(items: list[dict[str, Any]]) -> list[PublicLocationItem]:
    return [PublicLocationItem.model_validate(item) for item in items]


def diagnostic_items(items: list[dict[str, Any]]) -> list[DiagnosticItem]:
    return [DiagnosticItem.model_validate(item) for item in items]


def document_symbol_items(items: list[dict[str, Any]]) -> list[DocumentSymbolItem]:
    return [DocumentSymbolItem.model_validate(item) for item in items]


def navigation_items(items: list[dict[str, Any]]) -> list[NavigationLocation]:
    return [NavigationLocation.model_validate(item) for item in items]


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) else 0


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
