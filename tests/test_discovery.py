"""Gradle project discovery tests."""

from __future__ import annotations

from pathlib import Path

from jons_mcp_java.discovery import discover_gradle_roots


def test_discovers_nested_gradle_roots(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "services" / "api"
    nested.mkdir(parents=True)
    (root / "settings.gradle").write_text("", encoding="utf-8")
    (nested / "build.gradle").write_text("", encoding="utf-8")

    roots = discover_gradle_roots(root)

    assert roots == [root.resolve(), nested.resolve()]
