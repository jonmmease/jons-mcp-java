"""Public response schemas for MCP tools."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class PublicPosition(BaseModel):
    """One-based source position returned by public tools."""

    model_config = ConfigDict(extra="forbid")

    line: int = Field(..., ge=1)
    character: int = Field(..., ge=1)


class PublicRange(BaseModel):
    """One-based source range returned by public tools."""

    model_config = ConfigDict(extra="forbid")

    start: PublicPosition
    end: PublicPosition | None = None


class NavigationLocation(BaseModel):
    """Normalized target returned by navigation tools."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    range: PublicRange | dict[str, Any] | None = None
    fullRange: PublicRange | dict[str, Any] | None = None
    originRange: PublicRange | dict[str, Any] | None = None
    inWorkspace: bool


class NavigationResult(BaseModel):
    """Result returned by definition, type_definition, and implementation."""

    model_config = ConfigDict(extra="forbid")

    items: list[NavigationLocation]
    totalItems: int = Field(..., ge=0)


class PaginatedResult(BaseModel, Generic[T]):
    """Common paginated result envelope."""

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    totalItems: int = Field(..., ge=0)
    offset: int = Field(..., ge=0)
    limit: int = Field(..., ge=0)
    hasMore: bool
    nextOffset: int | None = None


class PublicLocationItem(BaseModel):
    """Paginated source location item."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    range: PublicRange | dict[str, Any] | None = None
    offset: int = Field(..., ge=0)
    inWorkspace: bool


class ReferencesResult(PaginatedResult[PublicLocationItem]):
    """Result returned by references."""


class DiagnosticItem(BaseModel):
    """One diagnostic item."""

    model_config = ConfigDict(extra="allow")

    uri: str
    range: PublicRange | dict[str, Any] | None = None
    severity: int | str | None = None
    severityName: str | None = None
    message: str
    source: str | None = None
    code: Any = None
    offset: int = Field(..., ge=0)
    inWorkspace: bool


class DiagnosticsResult(PaginatedResult[DiagnosticItem]):
    """Result returned by diagnostics."""


class DocumentSymbolItem(BaseModel):
    """One document or workspace symbol item."""

    model_config = ConfigDict(extra="allow")

    name: str
    kind: int
    kindName: str | None = None
    uri: str | None = None
    range: PublicRange | dict[str, Any] | None = None
    selectionRange: PublicRange | dict[str, Any] | None = None
    containerName: str | None = None
    offset: int = Field(..., ge=0)
    inWorkspace: bool | None = None


class DocumentSymbolsResult(PaginatedResult[DocumentSymbolItem]):
    """Result returned by document_symbols."""


class WorkspaceSymbolsResult(PaginatedResult[DocumentSymbolItem]):
    """Result returned by workspace_symbols."""


class SymbolInfoResult(BaseModel):
    """Result returned by symbol_info."""

    model_config = ConfigDict(extra="forbid")

    content: str | None
    range: PublicRange | dict[str, Any] | None = None


class RenamePreviewEdit(BaseModel):
    """One file edit returned by preview_rename."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    range: PublicRange
    newText: str
    inWorkspace: bool


class RenamePreviewResult(BaseModel):
    """Normalized preview_rename result."""

    model_config = ConfigDict(extra="forbid")

    edits: list[RenamePreviewEdit]
    totalEdits: int = Field(..., ge=0)


class RenamePreviewError(BaseModel):
    """Semantic rename failure returned by preview_rename."""

    model_config = ConfigDict(extra="forbid")

    error: str


class RestartServerResult(BaseModel):
    """Result returned by restart_server."""

    model_config = ConfigDict(extra="forbid")

    status: str
    message: str
    projects: list[str] | None = None
    project: str | None = None
    wasRunning: bool | None = None
