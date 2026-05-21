"""Gradle project discovery."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories to skip during discovery
IGNORE_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".vscode",
    ".claude",
    "build",
    "target",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
}

# Gradle project markers (in priority order)
GRADLE_MARKERS = [
    "settings.gradle.kts",
    "settings.gradle",
    "build.gradle.kts",
    "build.gradle",
]

# Maximum depth for scanning
MAX_SCAN_DEPTH = 10


def discover_gradle_roots(workspace_root: Path) -> list[Path]:
    """
    Discover Gradle project roots in the workspace.

    A Gradle root is defined by the presence of settings.gradle(.kts) or
    build.gradle(.kts). Nested roots are included so callers can route files
    to the deepest matching project.

    Returns a sorted list of Path objects.
    """
    roots: list[Path] = []
    workspace_root = workspace_root.resolve()

    _scan_for_gradle_roots(workspace_root, roots, depth=0)

    # Sort by path for consistent ordering
    roots.sort()

    logger.info(f"Discovered {len(roots)} Gradle project(s) in {workspace_root}")
    for root in roots:
        logger.debug(f"  - {root}")

    return roots


def _scan_for_gradle_roots(
    directory: Path,
    roots: list[Path],
    depth: int,
) -> None:
    """Recursively scan for Gradle roots."""
    if depth > MAX_SCAN_DEPTH:
        return

    # Check if this directory is a Gradle root
    is_gradle_root = _is_gradle_root(directory)

    if is_gradle_root:
        roots.append(directory)
        # Keep scanning; manager routing chooses the deepest project match.

    # Scan subdirectories
    try:
        for child in directory.iterdir():
            if child.is_dir() and child.name not in IGNORE_DIRS:
                _scan_for_gradle_roots(child, roots, depth + 1)
    except PermissionError:
        logger.debug(f"Permission denied scanning: {directory}")


def _is_gradle_root(directory: Path) -> bool:
    """Check if directory is a Gradle project root."""
    for marker in GRADLE_MARKERS:
        if (directory / marker).exists():
            return True
    return False
