"""Path normalization and workspace boundary checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class PathValidationError(Exception):
    """Raised when a user-supplied path cannot be safely resolved."""

    error_type: str
    message: str
    path: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ResolvedPath:
    """A user path resolved inside the configured workspace."""

    original: str
    path: Path
    workspace_root: Path

    @property
    def uri(self) -> str:
        from jons_mcp_java.utils import path_to_uri

        return path_to_uri(self.path)


def is_relative_to(path: Path, root: Path) -> bool:
    """Return True if path is equal to or contained by root."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def is_in_workspace(path: Path, workspace_root: Path) -> bool:
    """Check a path against the resolved workspace boundary."""
    return is_relative_to(path.resolve(), workspace_root.resolve())


def resolve_user_path(
    raw_path: str,
    workspace_root: Path,
    *,
    must_exist: bool = True,
) -> ResolvedPath:
    """Resolve a user-supplied path safely inside workspace_root.

    Supported inputs are workspace-relative paths, absolute paths, and file:// URIs.
    """
    workspace = workspace_root.resolve()
    original = raw_path
    raw_path = raw_path.strip()

    if not raw_path:
        raise PathValidationError(
            "empty_path",
            "Path must not be empty.",
            original,
        )

    path = _parse_user_path(raw_path)

    if ".." in path.parts:
        raise PathValidationError(
            "path_traversal",
            "Path must not contain '..' segments.",
            original,
        )

    candidate = path if path.is_absolute() else workspace / path

    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathValidationError(
            "path_not_found",
            "Path does not exist.",
            original,
        ) from exc
    except OSError as exc:
        raise PathValidationError(
            "path_invalid",
            f"Path could not be resolved: {exc}",
            original,
        ) from exc

    if not is_relative_to(resolved, workspace):
        raise PathValidationError(
            "path_outside_workspace",
            "Path resolves outside the configured workspace root.",
            original,
        )

    return ResolvedPath(original=original, path=resolved, workspace_root=workspace)


def _parse_user_path(raw_path: str) -> Path:
    parsed = urlparse(raw_path)

    if parsed.scheme:
        if parsed.scheme != "file":
            raise PathValidationError(
                "unsupported_uri_scheme",
                f"Only file:// URIs are supported, got {parsed.scheme!r}.",
                raw_path,
            )
        if parsed.netloc not in ("", "localhost"):
            raise PathValidationError(
                "unsupported_file_uri",
                "file:// URIs must not include a remote host.",
                raw_path,
            )
        if not parsed.path:
            raise PathValidationError(
                "malformed_file_uri",
                "file:// URI must include a path.",
                raw_path,
            )
        return Path(unquote(parsed.path))

    return Path(raw_path)
