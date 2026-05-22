"""Public response schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jons_mcp_java.schemas import (
    DiagnosticsResult,
    DocumentSymbolsResult,
    NavigationResult,
    PublicRange,
    ReferencesResult,
    RenamePreviewError,
    RenamePreviewResult,
    RestartServerResult,
    SymbolInfoResult,
    WorkspaceSymbolsResult,
)


def test_public_range_is_one_based() -> None:
    PublicRange.model_validate(
        {
            "start": {"line": 1, "character": 1},
            "end": {"line": 1, "character": 5},
        }
    )

    with pytest.raises(ValidationError):
        PublicRange.model_validate({"start": {"line": 0, "character": 1}})


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            NavigationResult,
            {
                "items": [{"uri": "file:///A.java", "range": None, "inWorkspace": True}],
                "totalItems": 1,
            },
        ),
        (
            ReferencesResult,
            {
                "items": [
                    {
                        "uri": "file:///A.java",
                        "range": None,
                        "offset": 0,
                        "inWorkspace": True,
                    }
                ],
                "totalItems": 1,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
        (
            DiagnosticsResult,
            {
                "items": [
                    {
                        "uri": "file:///A.java",
                        "message": "bad",
                        "offset": 0,
                        "inWorkspace": True,
                    }
                ],
                "totalItems": 1,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
        (
            DocumentSymbolsResult,
            {
                "items": [{"name": "A", "kind": 5, "offset": 0}],
                "totalItems": 1,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
        (
            WorkspaceSymbolsResult,
            {
                "items": [{"name": "A", "kind": 5, "offset": 0}],
                "totalItems": 1,
                "offset": 0,
                "limit": 20,
                "hasMore": False,
            },
        ),
        (SymbolInfoResult, {"content": "class A", "range": None}),
        (
            RenamePreviewResult,
            {
                "edits": [
                    {
                        "uri": "file:///A.java",
                        "range": {"start": {"line": 1, "character": 1}},
                        "newText": "B",
                        "inWorkspace": True,
                    }
                ],
                "totalEdits": 1,
            },
        ),
        (RenamePreviewError, {"error": "Symbol cannot be renamed"}),
        (RestartServerResult, {"status": "success", "message": "ok"}),
    ],
)
def test_public_success_schemas_accept_expected_payloads(
    model: type,
    payload: dict,
) -> None:
    model.model_validate(payload)
