"""JDT.LS client manager with lazy initialization and LRU eviction."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jons_mcp_java.client import JdtlsClient
from jons_mcp_java.constants import JDTLS_MAX_CLIENTS
from jons_mcp_java.discovery import discover_gradle_roots
from jons_mcp_java.paths import is_relative_to
from jons_mcp_java.utils import get_workspace_data_dir, path_to_uri

logger = logging.getLogger(__name__)


PROJECT_IDLE = "idle"
PROJECT_STARTING = "starting"
PROJECT_READY = "ready"
PROJECT_FAILED = "failed"
PROJECT_STOPPED = "stopped"


@dataclass
class ClientStatus:
    """Tool-facing result for client lookup."""

    client: JdtlsClient | None
    status: str
    message: str
    project: str | None = None
    error_type: str | None = None


@dataclass
class ProjectState:
    """State for a single Gradle project."""

    project_root: Path
    workspace_data_dir: Path
    client: JdtlsClient | None = None
    diagnostics: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    diagnostic_waiters: dict[
        str,
        list[asyncio.Future[list[dict[str, Any]]]],
    ] = field(default_factory=dict)
    last_accessed: datetime = field(default_factory=datetime.now)
    startup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    startup_state: str = PROJECT_STOPPED
    startup_error: str | None = None
    startup_task: asyncio.Task[None] | None = None

    @property
    def is_starting(self) -> bool:
        return self.startup_state == PROJECT_STARTING

    @property
    def is_ready(self) -> bool:
        return (
            self.startup_state == PROJECT_READY
            and self.client is not None
            and self.client.is_initialized
        )

    def clear_runtime_state(self) -> None:
        self.diagnostics.clear()
        for waiters in self.diagnostic_waiters.values():
            for future in waiters:
                if not future.done():
                    future.cancel()
        self.diagnostic_waiters.clear()


class JdtlsClientManager:
    """Manages multiple JDT.LS clients with lazy init and LRU eviction."""

    def __init__(
        self,
        workspace_root: Path,
        max_active_clients: int = JDTLS_MAX_CLIENTS,
    ):
        self.workspace_root = workspace_root.resolve()
        self.max_active_clients = max_active_clients
        self._projects: dict[str, ProjectState] = {}
        self._active_count = 0

    def discover_projects(self) -> list[Path]:
        """Discover Gradle projects in the workspace."""
        roots = discover_gradle_roots(self.workspace_root)

        for root in roots:
            key = str(root)
            if key not in self._projects:
                self._projects[key] = ProjectState(
                    project_root=root.resolve(),
                    workspace_data_dir=get_workspace_data_dir(root),
                )

        logger.info("Managing %s project(s)", len(self._projects))
        return roots

    def get_project_for_file(self, file_path: Path) -> ProjectState | None:
        """
        Route a file to its containing project using longest-prefix matching.
        Returns the deepest matching project.
        """
        resolved = file_path.resolve()
        if not is_relative_to(resolved, self.workspace_root):
            return None

        best_match: ProjectState | None = None
        best_depth = -1

        for project in self._projects.values():
            if is_relative_to(resolved, project.project_root):
                depth = len(project.project_root.parts)
                if depth > best_depth:
                    best_match = project
                    best_depth = depth

        return best_match

    async def get_client_for_file(self, file_path: Path) -> JdtlsClient:
        """Get or start a client for file, waiting for startup to finish."""
        project = self.get_project_for_file(file_path)
        if project is None:
            raise FileNotFoundError(f"No Gradle project found for {file_path}")

        await self._ensure_project_started(project)
        if project.client is None or not project.client.is_initialized:
            message = project.startup_error or f"JDT.LS is not ready for {file_path}"
            raise RuntimeError(message)

        project.last_accessed = datetime.now()
        return project.client

    async def get_client_for_file_with_status(self, file_path: Path) -> ClientStatus:
        """
        Get a client with status information for public tools.

        The first lookup starts initialization in the background and returns an
        initializing response. Later calls expose ready or failed state.
        """
        project = self.get_project_for_file(file_path)
        if project is None:
            return ClientStatus(
                client=None,
                status="error",
                message=f"No Gradle project found for {file_path}",
                error_type="project_not_found",
            )

        if project.is_ready:
            project.last_accessed = datetime.now()
            return ClientStatus(
                client=project.client,
                status="ready",
                message="ready",
                project=str(project.project_root),
            )

        if project.startup_state == PROJECT_FAILED:
            return ClientStatus(
                client=None,
                status="error",
                message=project.startup_error
                or f"JDT.LS failed to start for {project.project_root}",
                project=str(project.project_root),
                error_type="project_startup_failed",
            )

        if project.is_starting:
            return ClientStatus(
                client=None,
                status="initializing",
                message="Project is initializing; please retry shortly.",
                project=str(project.project_root),
            )

        self.start_project_background(project)
        return ClientStatus(
            client=None,
            status="initializing",
            message="Starting project initialization; please retry shortly.",
            project=str(project.project_root),
        )

    def get_initialized_client(self) -> ClientStatus:
        """Return any initialized client for workspace-wide tools."""
        ready_projects = [p for p in self._projects.values() if p.is_ready]
        if ready_projects:
            project = min(ready_projects, key=lambda p: p.last_accessed)
            project.last_accessed = datetime.now()
            return ClientStatus(
                client=project.client,
                status="ready",
                message="ready",
                project=str(project.project_root),
            )

        failed = [p for p in self._projects.values() if p.startup_state == PROJECT_FAILED]
        if failed:
            project = failed[0]
            return ClientStatus(
                client=None,
                status="error",
                message=project.startup_error
                or f"JDT.LS failed to start for {project.project_root}",
                project=str(project.project_root),
                error_type="project_startup_failed",
            )

        starting = [p for p in self._projects.values() if p.is_starting]
        if starting:
            project = starting[0]
            return ClientStatus(
                client=None,
                status="initializing",
                message="Project is initializing; please retry shortly.",
                project=str(project.project_root),
            )

        return ClientStatus(
            client=None,
            status="error",
            message="No initialized projects. Provide file_path to start one.",
            error_type="no_initialized_project",
        )

    def start_project_background(self, project: ProjectState) -> None:
        """Start project initialization in the background and capture failures."""
        if project.startup_task is not None and not project.startup_task.done():
            return
        project.startup_state = PROJECT_STARTING
        project.startup_error = None
        project.startup_task = asyncio.create_task(self._start_project_background(project))

    async def _start_project_background(self, project: ProjectState) -> None:
        try:
            await self._ensure_project_started(project)
        except Exception as exc:
            logger.exception("JDT.LS startup failed for %s", project.project_root)
            project.startup_state = PROJECT_FAILED
            project.startup_error = _friendly_exception_message(exc)
            project.client = None
            project.clear_runtime_state()
        finally:
            project.startup_task = None

    async def _ensure_project_started(self, project: ProjectState) -> None:
        """Start a project's JDT.LS client if needed."""
        async with project.startup_lock:
            if project.is_ready:
                return

            if self._active_count >= self.max_active_clients:
                await self._evict_lru_client()

            project.startup_state = PROJECT_STARTING
            project.startup_error = None
            project.clear_runtime_state()

            client = JdtlsClient(
                project_root=project.project_root,
                workspace_data_dir=project.workspace_data_dir,
            )
            client.on_notification(
                "textDocument/publishDiagnostics",
                lambda params: self._on_diagnostics(project, params),
            )

            try:
                await client.start()
            except Exception as exc:
                await client.shutdown()
                project.client = None
                project.startup_state = PROJECT_FAILED
                project.startup_error = _friendly_exception_message(exc)
                project.clear_runtime_state()
                raise

            project.client = client
            project.startup_state = PROJECT_READY
            project.last_accessed = datetime.now()
            self._active_count = self._count_active_clients()

    def _on_diagnostics(self, project: ProjectState, params: dict[str, Any]) -> None:
        uri = params.get("uri", "")
        diagnostics = params.get("diagnostics", [])
        if not isinstance(diagnostics, list):
            diagnostics = []
        project.diagnostics[uri] = diagnostics

        waiters = project.diagnostic_waiters.pop(uri, [])
        for future in waiters:
            if not future.done():
                future.set_result(diagnostics)

    def create_diagnostics_waiter(
        self,
        file_path: Path,
    ) -> asyncio.Future[list[dict[str, Any]]] | None:
        """Create a one-shot future for the next diagnostics for file_path."""
        project = self.get_project_for_file(file_path)
        if project is None:
            return None

        uri = path_to_uri(file_path)
        future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
        project.diagnostic_waiters.setdefault(uri, []).append(future)
        return future

    def cancel_diagnostics_waiter(
        self,
        file_path: Path,
        future: asyncio.Future[list[dict[str, Any]]] | None,
    ) -> None:
        """Cancel and remove a diagnostics waiter if it is no longer needed."""
        if future is None:
            return

        project = self.get_project_for_file(file_path)
        if project is not None:
            uri = path_to_uri(file_path)
            waiters = project.diagnostic_waiters.get(uri, [])
            if future in waiters:
                waiters.remove(future)
            if not waiters:
                project.diagnostic_waiters.pop(uri, None)
        if not future.done():
            future.cancel()

    async def wait_for_diagnostics(
        self,
        file_path: Path,
        future: asyncio.Future[list[dict[str, Any]]] | None,
        timeout: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Wait for diagnostics from a previously created waiter."""
        if future is None:
            return self.get_diagnostics(file_path)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self.cancel_diagnostics_waiter(file_path, future)
            return self.get_diagnostics(file_path)

    async def shutdown_project(self, project: ProjectState) -> bool:
        """Shutdown one project client and clear runtime state."""
        had_client = project.client is not None
        if project.client is not None:
            logger.info("Shutting down JDT.LS client for %s", project.project_root)
            await project.client.shutdown()
        project.client = None
        project.startup_state = PROJECT_STOPPED
        project.startup_error = None
        project.clear_runtime_state()
        self._active_count = self._count_active_clients()
        return had_client

    async def restart_project_for_file(self, file_path: Path) -> dict[str, Any]:
        """Stop the project containing file_path. It will restart lazily."""
        project = self.get_project_for_file(file_path)
        if project is None:
            return {
                "status": "error",
                "error": {
                    "type": "project_not_found",
                    "message": f"No Gradle project found for {file_path}",
                    "path": str(file_path),
                },
            }

        was_running = await self.shutdown_project(project)
        return {
            "status": "success",
            "message": f"Restarted server for project: {project.project_root}",
            "project": str(project.project_root),
            "wasRunning": was_running,
        }

    async def restart_all(self) -> dict[str, Any]:
        """Stop all clients. They will restart lazily on next file tool call."""
        active_projects = [
            str(project.project_root)
            for project in self._projects.values()
            if project.client is not None
        ]
        await self.shutdown_all()
        return {
            "status": "success",
            "message": f"Restarted {len(active_projects)} server(s)",
            "projects": active_projects,
        }

    async def _evict_lru_client(self) -> None:
        """Shutdown the least recently used initialized client."""
        evictable = [p for p in self._projects.values() if p.is_ready]

        if not evictable:
            logger.warning("No evictable clients available")
            return

        oldest = min(evictable, key=lambda p: p.last_accessed)
        await self.shutdown_project(oldest)

    async def shutdown_all(self) -> None:
        """Shutdown all JDT.LS clients."""
        for project in self._projects.values():
            if project.client is not None:
                await self.shutdown_project(project)
            else:
                project.clear_runtime_state()
                project.startup_state = PROJECT_STOPPED
                project.startup_error = None
        self._active_count = 0
        logger.info("All JDT.LS clients shut down")

    def get_diagnostics(self, file_path: Path) -> list[dict[str, Any]]:
        """Get cached diagnostics for a file."""
        project = self.get_project_for_file(file_path)
        if project is None:
            return []

        uri = path_to_uri(file_path)
        return project.diagnostics.get(uri, [])

    def get_all_diagnostics(self) -> dict[str, list[dict[str, Any]]]:
        """Get all cached diagnostics across all projects."""
        all_diagnostics: dict[str, list[dict[str, Any]]] = {}
        for project in self._projects.values():
            all_diagnostics.update(project.diagnostics)
        return all_diagnostics

    def _count_active_clients(self) -> int:
        return sum(
            1
            for project in self._projects.values()
            if project.client is not None and project.client.is_initialized
        )


def _friendly_exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return message
    return exc.__class__.__name__
