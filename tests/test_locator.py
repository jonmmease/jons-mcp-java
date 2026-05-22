"""JDT.LS and Java locator tests."""

from __future__ import annotations

from pathlib import Path

import pytest

import jons_mcp_java.locator as locator


def make_jdtls_home(root: Path) -> Path:
    jdtls_home = root / "share" / "java" / "jdtls"
    plugins = jdtls_home / "plugins"
    config = jdtls_home / "config_linux"
    plugins.mkdir(parents=True)
    config.mkdir()
    (plugins / "org.eclipse.equinox.launcher_1.0.0.jar").write_text(
        "",
        encoding="utf-8",
    )
    (config / "config.ini").write_text("eclipse.product=jdt.ls\n", encoding="utf-8")
    return jdtls_home


@pytest.fixture(autouse=True)
def linux_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locator.platform, "system", lambda: "Linux")
    monkeypatch.setattr(locator.platform, "machine", lambda: "x86_64")


def test_get_config_dir_copies_read_only_install_config_to_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jdtls_home = make_jdtls_home(tmp_path / "install")
    source_config = jdtls_home / "config_linux"
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))

    def fake_writable(path: Path) -> bool:
        return path.resolve() != source_config.resolve()

    monkeypatch.setattr(locator, "_directory_is_writable", fake_writable)

    config_dir = locator.get_config_dir(jdtls_home)

    assert config_dir != source_config
    assert config_dir.is_relative_to(cache_root)
    assert config_dir.name == "config_linux"
    assert (config_dir / "config.ini").read_text(encoding="utf-8") == (
        "eclipse.product=jdt.ls\n"
    )


def test_get_config_dir_honors_override_and_copies_source_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jdtls_home = make_jdtls_home(tmp_path / "install")
    override = tmp_path / "writable-config"
    monkeypatch.setenv("JDTLS_CONFIG_DIR", str(override))

    config_dir = locator.get_config_dir(jdtls_home)

    assert config_dir == override
    assert (override / "config.ini").exists()


def test_get_config_dir_uses_bundled_config_when_writable(tmp_path: Path) -> None:
    jdtls_home = make_jdtls_home(tmp_path / "install")

    assert locator.get_config_dir(jdtls_home) == jdtls_home / "config_linux"


def test_locate_jdtls_resolves_install_root_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = tmp_path / "profile"
    jdtls_home = make_jdtls_home(prefix)
    jdtls_bin = prefix / "bin" / "jdtls"
    jdtls_bin.parent.mkdir()
    jdtls_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    java = tmp_path / "java"
    java.write_text("", encoding="utf-8")

    monkeypatch.delenv("JDTLS_HOME", raising=False)
    monkeypatch.setattr(locator, "_get_homebrew_jdtls_path", lambda: None)
    monkeypatch.setattr(locator.shutil, "which", lambda name: str(jdtls_bin))
    monkeypatch.setattr(locator, "locate_java", lambda: java)

    installation = locator.locate_jdtls()

    assert installation.jdtls_home == jdtls_home
    assert installation.launcher_jar.name == "org.eclipse.equinox.launcher_1.0.0.jar"
    assert installation.config_dir == jdtls_home / "config_linux"
    assert installation.java_executable == java
