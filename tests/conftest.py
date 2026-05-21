"""Shared test helpers."""

from __future__ import annotations

import pytest

from jons_mcp_java.server import _ManagerHolder


@pytest.fixture(autouse=True)
def clear_manager_holder() -> None:
    _ManagerHolder.instance = None
    yield
    _ManagerHolder.instance = None
