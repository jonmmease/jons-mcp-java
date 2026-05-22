"""Wheel packaging checks."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path


def test_wheel_contains_runtime_package_only(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    wheel = next(tmp_path.glob("jons_mcp_java-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points = archive.read(
            "jons_mcp_java-0.1.0.dist-info/entry_points.txt"
        ).decode("utf-8")

    assert "jons_mcp_java/client.py" in names
    assert "jons_mcp_java/paths.py" in names
    assert "jons_mcp_java/schemas.py" in names
    assert "jons_mcp_java/tools/common.py" in names
    assert "jons_mcp_java/tools/refactor.py" in names
    assert "console_scripts" in entry_points
    assert "jons-mcp-java = jons_mcp_java:main" in entry_points
    assert not any("node_modules" in name for name in names)
    assert not any(name.startswith("tests/") for name in names)
    assert not any(".cache" in name for name in names)
