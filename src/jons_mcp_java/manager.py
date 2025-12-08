"""JDT.LS client manager with lazy initialization and LRU eviction."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jons_mcp_java.client import JdtlsClient
from jons_mcp_java.constants import JDTLS_MAX_CLIENTS
from jons_mcp_java.discovery import discover_gradle_roots
from jons_mcp_java.utils import get_workspace_data_dir

logger = logging.getLogger(__name__)


@dataclass
class ProjectState:
    """State for a single Gradle project."""

    project_root: Path
    workspace_data_dir: Path
    client: JdtlsClient | None = None
    diagnostics: dict[str, list] = field(default_factory=dict)
    last_accessed: datetime = field(default_factory=datetime.now)
    startup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    is_initializing: bool = False  # Prevent LRU eviction during init


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
                    project_root=root,
                    workspace_data_dir=get_workspace_data_dir(root),
                )

        logger.info(f"Managing {len(self._projects)} project(s)")
        return roots

    def get_project_for_file(self, file_path: Path) -> ProjectState | None:
        """
        Route a file to its containing project using longest-prefix matching.
        Returns the DEEPEST match (most specific project).
        """
        file_path = file_path.resolve()
        best_match = None
        best_depth = -1  # Start with -1, look for LARGER depth

        for project in self._projects.values():
            try:
                # Check if file is under this project
                file_path.relative_to(project.project_root)
                depth = len(project.project_root.parts)  # Use project depth
                if depth > best_depth:  # Choose deepest (longest prefix)
                    best_match = project
                    best_depth = depth
            except ValueError:
                continue  # file not under this project

        return best_match

    async def get_client_for_file(self, file_path: Path) -> JdtlsClient:
        """Get or start client for file, with concurrent startup protection."""
        project = self.get_project_for_file(file_path)
        if project is None:
            raise FileNotFoundError(f"No project found for {file_path}")

        # Use per-project lock to prevent duplicate startups
        async with project.startup_lock:
            if project.client is not None and project.client.is_initialized:
                project.last_accessed = datetime.now()
                return project.client

            # Check if we need to evict
            if self._active_count >= self.max_active_clients:
                await self._evict_lru_client()

            # Mark as initializing (prevents LRU eviction)
            project.is_initializing = True
            try:
                await self._start_client(project)
            finally:
                project.is_initializing = False

            self._active_count += 1
            project.last_accessed = datetime.now()
            return project.client

    async def get_client_for_file_with_status(
        self, file_path: Path
    ) -> tuple[JdtlsClient | None, str]:
        """
        Get client with status message for user feedback.
        Returns (client, status_message).
        """
        project = self.get_project_for_file(file_path)
        if project is None:
            return None, f"No project found for {file_path}"

        if project.client is not None and project.client.is_initialized:
            return project.client, "ready"

        if project.is_initializing:
            return None, "Project is initializing (Gradle import in progress)... please try again in 10 seconds."

        # Start initialization in background, return status
        asyncio.create_task(self.get_client_for_file(file_path))
        return None, "Starting project initialization... please try again in 15-20 seconds."

    async def _start_client(self, project: ProjectState) -> None:
        """Start a JDT.LS client for a project."""
        logger.info(f"Starting JDT.LS client for {project.project_root}")

        client = JdtlsClient(
            project_root=project.project_root,
            workspace_data_dir=project.workspace_data_dir,
        )

        # Register diagnostics handler
        def on_diagnostics(params):
            uri = params.get("uri", "")
            diagnostics = params.get("diagnostics", [])
            project.diagnostics[uri] = diagnostics

        client.on_notification("textDocument/publishDiagnostics", on_diagnostics)

        await client.start()
        project.client = client

    async def _shutdown_client(self, project: ProjectState) -> None:
        """Shutdown a JDT.LS client."""
        if project.client is not None:
            logger.info(f"Shutting down JDT.LS client for {project.project_root}")
            await project.client.shutdown()
            project.client = None

    async def _evict_lru_client(self) -> None:
        """Shutdown the least recently used client."""
        # Filter to active clients that are NOT initializing
        evictable = [
            p for p in self._projects.values()
            if p.client and not p.is_initializing
        ]

        if not evictable:  # Guard against empty list
            logger.warning("No evictable clients available")
            return

        oldest = min(evictable, key=lambda p: p.last_accessed)
        await self._shutdown_client(oldest)
        self._active_count -= 1

    async def shutdown_all(self) -> None:
        """Shutdown all JDT.LS clients."""
        for project in self._projects.values():
            if project.client is not None:
                await self._shutdown_client(project)
        self._active_count = 0
        logger.info("All JDT.LS clients shut down")

    def get_diagnostics(self, file_path: Path) -> list:
        """Get cached diagnostics for a file."""
        project = self.get_project_for_file(file_path)
        if project is None:
            return []

        from jons_mcp_java.utils import path_to_uri
        uri = path_to_uri(file_path)
        return project.diagnostics.get(uri, [])

    def get_all_diagnostics(self) -> dict[str, list]:
        """Get all cached diagnostics across all projects."""
        all_diagnostics = {}
        for project in self._projects.values():
            all_diagnostics.update(project.diagnostics)
        return all_diagnostics
