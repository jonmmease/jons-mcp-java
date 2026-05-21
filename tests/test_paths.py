"""Path normalization and workspace boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from jons_mcp_java.paths import PathValidationError, is_in_workspace, resolve_user_path


def make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    project = workspace / "app"
    src = project / "src"
    src.mkdir(parents=True)
    java_file = src / "Main.java"
    java_file.write_text("class Main {}\n", encoding="utf-8")
    return workspace, java_file


def test_resolves_relative_paths_from_workspace_root(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)

    resolved = resolve_user_path("app/src/Main.java", workspace)

    assert resolved.path == java_file.resolve()
    assert resolved.uri.startswith("file://")


def test_accepts_absolute_in_workspace_path(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)

    resolved = resolve_user_path(str(java_file), workspace)

    assert resolved.path == java_file.resolve()


def test_accepts_file_uri(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)

    resolved = resolve_user_path(java_file.resolve().as_uri(), workspace)

    assert resolved.path == java_file.resolve()


@pytest.mark.parametrize(
    ("raw_path", "error_type"),
    [
        ("", "empty_path"),
        ("http://example.com/Main.java", "unsupported_uri_scheme"),
        ("../outside.java", "path_traversal"),
        ("app/../app/src/Main.java", "path_traversal"),
    ],
)
def test_rejects_unsafe_path_syntax(
    tmp_path: Path,
    raw_path: str,
    error_type: str,
) -> None:
    workspace, _java_file = make_workspace(tmp_path)

    with pytest.raises(PathValidationError) as exc_info:
        resolve_user_path(raw_path, workspace)

    assert exc_info.value.error_type == error_type


def test_rejects_absolute_path_outside_workspace(tmp_path: Path) -> None:
    workspace, _java_file = make_workspace(tmp_path)
    outside = tmp_path / "outside.java"
    outside.write_text("class Outside {}\n", encoding="utf-8")

    with pytest.raises(PathValidationError) as exc_info:
        resolve_user_path(str(outside), workspace)

    assert exc_info.value.error_type == "path_outside_workspace"


def test_rejects_missing_path(tmp_path: Path) -> None:
    workspace, _java_file = make_workspace(tmp_path)

    with pytest.raises(PathValidationError) as exc_info:
        resolve_user_path("app/src/Missing.java", workspace)

    assert exc_info.value.error_type == "path_not_found"


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace, _java_file = make_workspace(tmp_path)
    outside = tmp_path / "outside.java"
    outside.write_text("class Outside {}\n", encoding="utf-8")
    link = workspace / "app" / "src" / "Link.java"
    link.symlink_to(outside)

    with pytest.raises(PathValidationError) as exc_info:
        resolve_user_path("app/src/Link.java", workspace)

    assert exc_info.value.error_type == "path_outside_workspace"


def test_is_in_workspace_handles_external_locations(tmp_path: Path) -> None:
    workspace, java_file = make_workspace(tmp_path)
    outside = tmp_path / "outside.java"

    assert is_in_workspace(java_file, workspace)
    assert not is_in_workspace(outside, workspace)
