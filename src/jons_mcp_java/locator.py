"""JDT.LS and Java installation locator."""

import hashlib
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jons_mcp_java.constants import JAVA_MIN_VERSION
from jons_mcp_java.exceptions import (
    JavaNotFoundError,
    JavaVersionError,
    JdtlsNotFoundError,
    UnsupportedPlatformError,
)

logger = logging.getLogger(__name__)


@dataclass
class JdtlsInstallation:
    """Information about a JDT.LS installation."""

    jdtls_home: Path
    launcher_jar: Path
    config_dir: Path
    java_executable: Path


def locate_jdtls() -> JdtlsInstallation:
    """
    Locate JDT.LS installation. Search order:
    1. JDTLS_HOME environment variable
    2. Homebrew via `brew --prefix jdtls`
    3. jdtls executable on PATH
    4. Common Homebrew paths (Apple Silicon and Intel)
    5. Manual installation (~/.local/share/jdtls)
    """
    # Check environment variable first
    if jdtls_home := os.environ.get("JDTLS_HOME"):
        logger.debug(f"Using JDTLS_HOME from environment: {jdtls_home}")
        return _validate_jdtls_installation(Path(jdtls_home))

    # Try Homebrew (most reliable)
    brew_path = _get_homebrew_jdtls_path()
    if brew_path:
        logger.debug(f"Found JDT.LS via Homebrew: {brew_path}")
        return _validate_jdtls_installation(brew_path)

    path_install = _get_path_jdtls_path()
    if path_install:
        logger.debug(f"Found JDT.LS via PATH: {path_install}")
        return _validate_jdtls_installation(path_install)

    # Fallback paths
    fallback_paths = [
        Path("/opt/homebrew/opt/jdtls"),  # Apple Silicon
        Path("/usr/local/opt/jdtls"),  # Intel Mac
        Path.home() / ".local/share/jdtls",  # Manual install
    ]

    for path in fallback_paths:
        if path.exists():
            logger.debug(f"Found JDT.LS at fallback path: {path}")
            return _validate_jdtls_installation(path)

    raise JdtlsNotFoundError(
        "JDT.LS not found. Set JDTLS_HOME, install a jdtls executable on PATH, "
        "or install JDT.LS with Homebrew, your Linux package manager, or Nix."
    )


def _get_homebrew_jdtls_path() -> Path | None:
    """Get JDT.LS path via Homebrew."""
    try:
        result = subprocess.run(
            ["brew", "--prefix", "jdtls"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_path_jdtls_path() -> Path | None:
    """Resolve a JDT.LS install root from a jdtls executable on PATH."""
    executable = shutil.which("jdtls")
    if executable is None:
        return None

    jdtls_bin = Path(executable).resolve()
    prefix = jdtls_bin.parent.parent
    candidates = [
        prefix / "share" / "java" / "jdtls",
        prefix / "share" / "jdtls",
        prefix / "lib" / "jdtls",
        prefix,
    ]

    for candidate in candidates:
        if _looks_like_jdtls_home(candidate):
            return candidate

    return None


def _looks_like_jdtls_home(path: Path) -> bool:
    """Return whether path has enough JDT.LS layout to validate later."""
    return (path / "plugins").exists() or (path / "libexec" / "plugins").exists()


def _validate_jdtls_installation(jdtls_home: Path) -> JdtlsInstallation:
    """Validate JDT.LS installation and return full configuration."""
    # Find launcher JAR
    launcher_jar = _find_launcher_jar(jdtls_home)

    # Get platform-specific config directory
    config_dir = get_config_dir(jdtls_home)

    # Locate Java
    java_executable = locate_java()

    return JdtlsInstallation(
        jdtls_home=jdtls_home,
        launcher_jar=launcher_jar,
        config_dir=config_dir,
        java_executable=java_executable,
    )


def _find_launcher_jar(jdtls_home: Path) -> Path:
    """Find the org.eclipse.equinox.launcher JAR."""
    # Check both direct and libexec paths (Homebrew layout)
    for base in [jdtls_home, jdtls_home / "libexec"]:
        plugins_dir = base / "plugins"
        if plugins_dir.exists():
            # Find launcher JAR
            launchers = list(plugins_dir.glob("org.eclipse.equinox.launcher_*.jar"))
            if launchers:
                return launchers[0]

    raise JdtlsNotFoundError(f"Launcher JAR not found in {jdtls_home}")


def get_config_dir(jdtls_home: Path) -> Path:
    """Get a writable platform-specific JDT.LS configuration directory."""
    config_name = _platform_config_name()
    source_config_dir = _find_config_dir(jdtls_home, config_name)

    if override := os.environ.get("JDTLS_CONFIG_DIR"):
        config_dir = Path(override).expanduser()
        _prepare_writable_config_dir(source_config_dir, config_dir)
        return config_dir

    if _directory_is_writable(source_config_dir):
        return source_config_dir

    config_dir = _cached_config_dir(jdtls_home, config_name)
    _prepare_writable_config_dir(source_config_dir, config_dir)
    logger.info(
        "Using writable JDT.LS config directory %s for read-only install config %s",
        config_dir,
        source_config_dir,
    )
    return config_dir


def _platform_config_name() -> str:
    """Return the JDT.LS config_<os> directory name for this platform."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        if machine == "arm64":
            return "config_mac_arm"
        return "config_mac"

    if system == "Linux":
        if "arm" in machine or "aarch64" in machine:
            return "config_linux_arm"
        return "config_linux"

    if system == "Windows":
        return "config_win"

    raise UnsupportedPlatformError(f"Platform {system} not supported")


def _find_config_dir(jdtls_home: Path, config_name: str) -> Path:
    """Find bundled JDT.LS config directory in direct or Homebrew layout."""

    # Check both direct and libexec paths (Homebrew layout)
    for base in [jdtls_home, jdtls_home / "libexec"]:
        config_path = base / config_name
        if config_path.exists():
            return config_path

    raise JdtlsNotFoundError(f"Config directory {config_name} not found in {jdtls_home}")


def _cached_config_dir(jdtls_home: Path, config_name: str) -> Path:
    """Return a per-install writable cache config directory."""
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    install_hash = hashlib.sha256(str(jdtls_home.resolve()).encode()).hexdigest()[:12]
    return cache_root / "jons-mcp-java" / "jdtls-configs" / install_hash / config_name


def _prepare_writable_config_dir(source_config_dir: Path, config_dir: Path) -> None:
    """Copy bundled config files into config_dir and ensure it is writable."""
    if source_config_dir.resolve() == config_dir.resolve():
        _make_tree_user_writable(config_dir)
        if not _directory_is_writable(config_dir):
            raise JdtlsNotFoundError(
                f"JDT.LS config directory is not writable: {config_dir}"
            )
        return

    if config_dir.exists():
        _make_tree_user_writable(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_config_dir, config_dir, dirs_exist_ok=True)
    _make_tree_user_writable(config_dir)
    if not _directory_is_writable(config_dir):
        raise JdtlsNotFoundError(f"JDT.LS config directory is not writable: {config_dir}")


def _make_tree_user_writable(path: Path) -> None:
    """Make an extracted/copied config tree writable by the current user."""
    if not path.exists():
        return

    for item in [path, *path.rglob("*")]:
        if item.is_symlink():
            continue
        try:
            current_mode = stat.S_IMODE(item.stat().st_mode)
            user_bits = stat.S_IRUSR | stat.S_IWUSR
            if item.is_dir():
                user_bits |= stat.S_IXUSR
            item.chmod(current_mode | user_bits)
        except OSError:
            logger.debug("Could not adjust permissions for %s", item, exc_info=True)


def _directory_is_writable(path: Path) -> bool:
    """Return whether a directory is actually writable by creating a probe file."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".jons-mcp-java-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def locate_java() -> Path:
    """Locate Java 21+ installation with version validation."""
    java_path = _find_java_executable()
    _validate_java_version(java_path)
    return java_path


def _find_java_executable() -> Path:
    """
    Find Java executable. Search order:
    1. JAVA_HOME environment variable
    2. Homebrew openjdk@21
    3. System java
    """
    # Check JAVA_HOME
    if java_home := os.environ.get("JAVA_HOME"):
        java_path = Path(java_home) / "bin" / "java"
        if java_path.exists():
            logger.debug(f"Using JAVA_HOME: {java_home}")
            return java_path

    # Try Homebrew openjdk@21
    brew_java = _get_homebrew_java_path()
    if brew_java and brew_java.exists():
        logger.debug(f"Found Java via Homebrew: {brew_java}")
        return brew_java

    # Try system java
    system_java = _find_system_java()
    if system_java:
        logger.debug(f"Found system Java: {system_java}")
        return system_java

    raise JavaNotFoundError(
        "Java not found. Set JAVA_HOME, install java on PATH, or install Java 21+ "
        "with Homebrew, your Linux package manager, or Nix."
    )


def _get_homebrew_java_path() -> Path | None:
    """Get Java path via Homebrew."""
    # Try openjdk@21 first, then generic openjdk
    for formula in ["openjdk@21", "openjdk"]:
        try:
            result = subprocess.run(
                ["brew", "--prefix", formula],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                prefix = Path(result.stdout.strip())
                java_path = prefix / "bin" / "java"
                if java_path.exists():
                    return java_path
                # Some formulas put it under libexec
                java_path = prefix / "libexec" / "openjdk.jdk" / "Contents" / "Home" / "bin" / "java"
                if java_path.exists():
                    return java_path
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return None


def _find_system_java() -> Path | None:
    """Find system Java using 'which'."""
    try:
        result = subprocess.run(
            ["which", "java"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _validate_java_version(java_path: Path) -> None:
    """Verify Java version is 21 or higher."""
    try:
        result = subprocess.run(
            [str(java_path), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise JavaVersionError(f"Could not run Java: {e}") from e

    # Java version is on stderr
    version_output = result.stderr

    # Parse version (e.g., "openjdk version \"21.0.1\"")
    match = re.search(r'version "(\d+)', version_output)
    if not match:
        raise JavaVersionError(f"Could not parse Java version from: {version_output}")

    major_version = int(match.group(1))
    if major_version < JAVA_MIN_VERSION:
        raise JavaVersionError(
            f"Java {JAVA_MIN_VERSION}+ required, found Java {major_version}. "
            "Set JAVA_HOME or install Java 21+ with Homebrew, your Linux package "
            "manager, or Nix."
        )

    logger.debug(f"Java version {major_version} validated")
