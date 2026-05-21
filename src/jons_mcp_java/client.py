"""JDT.LS client with subprocess management and LSP protocol."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import queue
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jons_mcp_java.constants import (
    JDTLS_INIT_TIMEOUT,
    JDTLS_LANGUAGE_STATUS,
    JDTLS_MEMORY,
    JDTLS_PROGRESS,
    JDTLS_TIMEOUT,
    LSP_CLIENT_REGISTER_CAPABILITY,
    LSP_CLIENT_UNREGISTER_CAPABILITY,
    LSP_EXIT,
    LSP_INITIALIZE,
    LSP_INITIALIZED,
    LSP_SHUTDOWN,
    LSP_TEXT_DOCUMENT_DID_CHANGE,
    LSP_TEXT_DOCUMENT_DID_CLOSE,
    LSP_TEXT_DOCUMENT_DID_OPEN,
    LSP_TEXT_DOCUMENT_DID_SAVE,
    LSP_WINDOW_WORK_DONE_PROGRESS_CREATE,
    LSP_WORKSPACE_CONFIGURATION,
    LSP_WORKSPACE_WORKSPACE_FOLDERS,
)
from jons_mcp_java.exceptions import JdtlsNotInitializedError, LspRequestError
from jons_mcp_java.locator import JdtlsInstallation, locate_jdtls
from jons_mcp_java.utils import path_to_uri

logger = logging.getLogger(__name__)


@dataclass
class DocumentState:
    """Tracks state for an open document."""

    uri: str
    version: int
    mtime_ns: int
    size: int
    content_hash: str


class JdtlsClient:
    """LSP client for a single JDT.LS instance."""

    def __init__(self, project_root: Path, workspace_data_dir: Path):
        self.project_root = project_root.resolve()
        self.workspace_data_dir = workspace_data_dir
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._watcher_thread: threading.Thread | None = None
        self._processor_task: asyncio.Task | None = None
        self._message_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._notification_handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._request_id = 0
        self._writer_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._shutting_down = False
        self._initialized = False

        # Document tracking (URI -> DocumentState)
        self._document_states: dict[str, DocumentState] = {}

        # Per-URI locks to prevent race conditions during file operations
        self._file_locks: dict[str, asyncio.Lock] = {}

        # Server request handlers
        self._request_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            LSP_WORKSPACE_CONFIGURATION: self._handle_configuration,
            LSP_CLIENT_REGISTER_CAPABILITY: self._handle_register_capability,
            LSP_CLIENT_UNREGISTER_CAPABILITY: self._handle_unregister_capability,
            LSP_WORKSPACE_WORKSPACE_FOLDERS: self._handle_workspace_folders,
            LSP_WINDOW_WORK_DONE_PROGRESS_CREATE: self._handle_progress_create,
        }

    async def start(self) -> None:
        """Start JDT.LS subprocess and initialize."""
        if self._running:
            return

        self._loop = asyncio.get_running_loop()
        self._shutting_down = False
        self._initialized = False

        try:
            installation = locate_jdtls()
            cmd = self._build_jdtls_command(installation)
            logger.info("Starting JDT.LS for %s", self.project_root)
            logger.debug("Command: %s", " ".join(cmd))

            self.workspace_data_dir.mkdir(parents=True, exist_ok=True)
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.project_root),
            )

            self._running = True

            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()

            self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
            self._stderr_thread.start()

            self._start_process_watcher()
            self._processor_task = asyncio.create_task(self._process_messages())

            await self._initialize()

            if not await self.wait_for_ready(timeout=JDTLS_INIT_TIMEOUT):
                raise LspRequestError(
                    f"JDT.LS did not become ready within {JDTLS_INIT_TIMEOUT}s"
                )

            self._initialized = True
            logger.info("JDT.LS initialized for %s", self.project_root)
        except Exception as exc:
            await self._cleanup_after_failure(exc)
            raise

    def _build_jdtls_command(self, installation: JdtlsInstallation) -> list[str]:
        """Build JDT.LS startup command."""
        return [
            str(installation.java_executable),
            # Eclipse/OSGi configuration
            "-Declipse.application=org.eclipse.jdt.ls.core.id1",
            "-Dosgi.bundles.defaultStartLevel=4",
            "-Declipse.product=org.eclipse.jdt.ls.core.product",
            "-Dlog.level=ALL",
            # Memory
            f"-Xmx{JDTLS_MEMORY}",
            "-XX:+UseG1GC",
            # Java module system (required for Java 9+)
            "--add-modules=ALL-SYSTEM",
            "--add-opens", "java.base/java.util=ALL-UNNAMED",
            "--add-opens", "java.base/java.lang=ALL-UNNAMED",
            # JDT.LS launcher
            "-jar", str(installation.launcher_jar),
            "-configuration", str(installation.config_dir),
            "-data", str(self.workspace_data_dir),
        ]

    def _reader_loop(self) -> None:
        """Read stdout with validation for non-LSP output."""
        while self._running:
            try:
                if self._process is None or self._process.stdout is None:
                    break

                # Read header line
                line = self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()

                # Validate this looks like LSP protocol
                if not line_str.startswith("Content-Length:"):
                    # Log and skip non-LSP output (Gradle noise, JVM warnings)
                    if line_str:
                        logger.debug(f"Non-LSP stdout: {line_str}")
                    continue

                # Parse Content-Length and read body
                try:
                    content_length = int(line_str.split(":", 1)[1].strip())
                except (IndexError, ValueError):
                    logger.debug("Malformed LSP header on stdout: %s", line_str)
                    continue

                # Read empty line (header separator)
                self._process.stdout.readline()

                # Read body
                body = self._process.stdout.read(content_length)
                if not body:
                    break

                message = json.loads(body.decode("utf-8"))
                if isinstance(message, dict):
                    self._message_queue.put(message)

            except Exception as e:
                if self._running:
                    logger.error("Reader error: %s", e)

    def _stderr_loop(self) -> None:
        """Read stderr and log to file."""
        log_path = self.workspace_data_dir / "jdtls-stderr.log"
        try:
            with open(log_path, "a", encoding="utf-8") as log_file:
                while self._running:
                    if self._process is None or self._process.stderr is None:
                        break

                    line = self._process.stderr.readline()
                    if not line:
                        break

                    decoded = line.decode("utf-8", errors="replace")
                    log_file.write(decoded)
                    log_file.flush()

                    # Also log at debug level
                    if decoded.strip():
                        logger.debug("JDT.LS stderr: %s", decoded.strip())
        except Exception as e:
            if self._running:
                logger.error("Stderr reader error: %s", e)

    def _start_process_watcher(self) -> None:
        """Watch for process death and cancel pending requests."""
        def watcher() -> None:
            if self._process:
                self._process.wait()  # Blocks until process exits
            if not self._shutting_down and self._running:
                logger.error("JDT.LS process died unexpectedly")
                self._running = False
                self._initialized = False
                self._cancel_pending_requests(LspRequestError("JDT.LS process died"))

        self._watcher_thread = threading.Thread(target=watcher, daemon=True)
        self._watcher_thread.start()

    async def _process_messages(self) -> None:
        """Process messages from the queue."""
        while self._running:
            try:
                # Non-blocking check with small timeout
                try:
                    message = self._message_queue.get(timeout=0.1)
                except queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

                await self._handle_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Message processing error: {e}")

    async def _handle_message(self, message: dict) -> None:
        """Handle a single LSP message."""
        if "id" in message:
            if "method" in message:
                # Server -> client request
                await self._handle_server_request(message)
            else:
                # Response to our request
                request_id = message["id"]
                if request_id in self._pending_requests:
                    future = self._pending_requests.pop(request_id)
                    if future.done():
                        return
                    if "error" in message:
                        error = message["error"]
                        future.set_exception(
                            LspRequestError(
                                error.get("message", "Unknown error"),
                                error.get("code")
                            )
                        )
                    else:
                        future.set_result(message.get("result"))
        else:
            # Notification
            method = message.get("method", "")
            params = message.get("params", {})

            # Call registered handlers
            handlers = self._notification_handlers.get(method, [])
            for handler in handlers:
                try:
                    handler(params)
                except Exception as e:
                    logger.error(f"Notification handler error for {method}: {e}")

    async def _handle_server_request(self, message: dict) -> None:
        """Handle a request from the server."""
        method = message.get("method", "")
        params = message.get("params", {})
        request_id = message["id"]

        handler = self._request_handlers.get(method)
        if handler:
            try:
                result = await handler(params)
                await self._send_response(request_id, result)
            except Exception as e:
                logger.error(f"Server request handler error for {method}: {e}")
                await self._send_error(request_id, -32603, str(e))
        else:
            logger.warning(f"No handler for server request: {method}")
            await self._send_response(request_id, None)

    async def _send_response(self, request_id: int, result: Any) -> None:
        """Send a response to a server request."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        self._write_message(response)

    async def _send_error(self, request_id: int, code: int, message: str) -> None:
        """Send an error response."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
        self._write_message(response)

    # Server request handlers

    async def _handle_configuration(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return Java configuration settings."""
        # Return config for each requested scope
        return [{"java": {}} for _ in params.get("items", [])]

    async def _handle_register_capability(self, params: dict[str, Any]) -> None:
        """Acknowledge capability registration."""
        return None  # Empty response = success

    async def _handle_unregister_capability(self, params: dict[str, Any]) -> None:
        """Acknowledge capability unregistration."""
        return None

    async def _handle_workspace_folders(self, params: dict[str, Any]) -> list[dict[str, str]]:
        """Return workspace folders."""
        return [{"uri": self.project_root.as_uri(), "name": self.project_root.name}]

    async def _handle_progress_create(self, params: dict[str, Any]) -> None:
        """Accept progress token creation."""
        return None

    # LSP methods

    async def request(
        self, method: str, params: dict | None = None, timeout: float = JDTLS_TIMEOUT
    ) -> Any:
        """Send an LSP request and wait for response."""
        if not self._running:
            raise JdtlsNotInitializedError("JDT.LS client not running")

        self._request_id += 1
        request_id = self._request_id

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        try:
            self._write_message(message)
        except Exception:
            self._pending_requests.pop(request_id, None)
            raise

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending_requests.pop(request_id, None)
            raise LspRequestError(
                f"Request {method} timed out after {timeout}s"
            ) from exc

    async def notify(self, method: str, params: dict | None = None) -> None:
        """Send an LSP notification (no response expected)."""
        if not self._running:
            raise JdtlsNotInitializedError("JDT.LS client not running")

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        self._write_message(message)

    def _write_message(self, message: dict) -> None:
        """Write a message to JDT.LS stdin."""
        if self._process is None or self._process.stdin is None:
            raise JdtlsNotInitializedError("JDT.LS stdin is not available")

        with self._writer_lock:
            try:
                body = json.dumps(message).encode()
                header = f"Content-Length: {len(body)}\r\n\r\n".encode()
                self._process.stdin.write(header + body)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise LspRequestError("Could not write to JDT.LS stdin") from exc

    def on_notification(
        self,
        method: str,
        handler: Callable[[dict[str, Any]], None],
    ) -> None:
        """Register a notification handler."""
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    # Initialization

    async def _initialize(self) -> dict[str, Any]:
        """Perform LSP initialize handshake."""
        init_params = {
            "processId": os.getpid(),
            "rootUri": self.project_root.as_uri(),
            "capabilities": {
                "textDocument": {
                    "synchronization": {
                        "didSave": True,
                        "dynamicRegistration": True,
                    },
                    "completion": {"completionItem": {"snippetSupport": False}},
                    "hover": {"contentFormat": ["markdown", "plaintext"]},
                    "definition": {"linkSupport": True},
                    "references": {},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "codeAction": {
                        "codeActionLiteralSupport": {
                            "codeActionKind": {"valueSet": []}
                        }
                    },
                    "rename": {"prepareSupport": True},
                },
                "workspace": {
                    "workspaceFolders": True,
                    "symbol": {"symbolKind": {"valueSet": list(range(1, 27))}},
                    "configuration": True,  # Required for workspace/configuration requests
                },
            },
            "initializationOptions": {
                "bundles": [],
                "workspaceFolders": [self.project_root.as_uri()],
                "settings": {
                    "java": {
                        "import": {"gradle": {"enabled": True}},
                        "autobuild": {"enabled": True},
                    }
                }
            },
        }

        result = await self.request(LSP_INITIALIZE, init_params, timeout=60)
        await self.notify(LSP_INITIALIZED, {})
        if not isinstance(result, dict):
            return {}
        return result

    async def wait_for_ready(self, timeout: float = 120.0) -> bool:
        """Wait for JDT.LS to finish importing and be ready."""
        ready_event = asyncio.Event()

        def on_status(params: dict[str, Any]) -> None:
            message = params.get("message", "")
            msg_type = params.get("type", "")
            logger.debug(f"JDT.LS status: {msg_type} - {message}")
            if "ServiceReady" in message or msg_type == "Started":
                ready_event.set()

        def on_progress(params: dict[str, Any]) -> None:
            value = params.get("value", {})
            kind = value.get("kind", "")
            title = value.get("title", "")
            message = value.get("message", "")
            if kind and title:
                logger.debug(f"JDT.LS progress: {kind} - {title} - {message}")

        self.on_notification(JDTLS_LANGUAGE_STATUS, on_status)
        self.on_notification(JDTLS_PROGRESS, on_progress)

        try:
            await asyncio.wait_for(ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for JDT.LS ready")
            return False

    # Text document synchronization

    def _get_file_lock(self, uri: str) -> asyncio.Lock:
        """Get or create a lock for a specific file URI."""
        if uri not in self._file_locks:
            self._file_locks[uri] = asyncio.Lock()
        return self._file_locks[uri]

    def _read_file_snapshot(self, file_path: str | Path) -> tuple[str, int, int, str]:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        stat = path.stat()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return content, stat.st_mtime_ns, stat.st_size, content_hash

    def _check_file_changed(self, file_path: str | Path) -> bool:
        """Check if file on disk differs from tracked state.

        Returns True if mtime_ns, size, or content hash differs from stored state.
        Returns False if file not tracked or no change detected.
        """
        file_uri = path_to_uri(file_path)
        state = self._document_states.get(file_uri)
        if state is None:
            return False

        try:
            _content, mtime_ns, size, content_hash = self._read_file_snapshot(file_path)
            return (
                mtime_ns != state.mtime_ns
                or size != state.size
                or content_hash != state.content_hash
            )
        except FileNotFoundError:
            return True

    async def _refresh_file(self, file_path: str | Path) -> bool:
        """Refresh an already-opened file from disk.

        Handles file deletion gracefully by sending didClose.
        """
        file_uri = path_to_uri(file_path)
        state = self._document_states.get(file_uri)
        if state is None:
            return False

        try:
            content, mtime_ns, size, content_hash = self._read_file_snapshot(file_path)
        except FileNotFoundError:
            await self.notify(
                LSP_TEXT_DOCUMENT_DID_CLOSE,
                {"textDocument": {"uri": file_uri}},
            )
            del self._document_states[file_uri]
            self._file_locks.pop(file_uri, None)
            logger.info("File deleted, closed document: %s", file_path)
            return True

        state.version += 1
        state.mtime_ns = mtime_ns
        state.size = size
        state.content_hash = content_hash

        await self.notify(
            LSP_TEXT_DOCUMENT_DID_CHANGE,
            {
                "textDocument": {
                    "uri": file_uri,
                    "version": state.version,
                },
                "contentChanges": [{"text": content}],
            },
        )
        await self._notify_saved(file_uri, content)

        logger.debug("Refreshed file from disk: %s (version %s)", file_path, state.version)
        return True

    async def ensure_file_open(self, file_path: str | Path) -> bool:
        """Ensure file is open in JDT.LS for analysis, auto-refreshing if changed.

        Returns True if a didOpen, didChange, or didClose notification was sent.
        """
        file_uri = path_to_uri(file_path)

        async with self._get_file_lock(file_uri):
            if file_uri in self._document_states:
                if self._check_file_changed(file_path):
                    return await self._refresh_file(file_path)
                return False

            content, mtime_ns, size, content_hash = self._read_file_snapshot(file_path)

            self._document_states[file_uri] = DocumentState(
                uri=file_uri,
                version=1,
                mtime_ns=mtime_ns,
                size=size,
                content_hash=content_hash,
            )

            await self.notify(
                LSP_TEXT_DOCUMENT_DID_OPEN,
                {
                    "textDocument": {
                        "uri": file_uri,
                        "languageId": "java",
                        "version": 1,
                        "text": content,
                    }
                },
            )

            return True

    async def update_file(self, file_path: str | Path, content: str) -> None:
        """Update file content in JDT.LS."""
        file_uri = path_to_uri(file_path)

        if file_uri not in self._document_states:
            await self.ensure_file_open(file_path)
            return

        state = self._document_states[file_uri]
        state.version += 1

        path = Path(file_path)
        if path.exists():
            stat = path.stat()
            state.mtime_ns = stat.st_mtime_ns
            state.size = stat.st_size
        state.content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        await self.notify(
            LSP_TEXT_DOCUMENT_DID_CHANGE,
            {
                "textDocument": {
                    "uri": file_uri,
                    "version": state.version,
                },
                "contentChanges": [{"text": content}],
            },
        )
        await self._notify_saved(file_uri, content)

    async def _notify_saved(self, file_uri: str, content: str) -> None:
        await self.notify(
            LSP_TEXT_DOCUMENT_DID_SAVE,
            {"textDocument": {"uri": file_uri}, "text": content},
        )

    def clear_document_state(self) -> None:
        """Clear tracked text document state."""
        self._document_states.clear()
        self._file_locks.clear()

    # Shutdown

    async def shutdown(self) -> None:
        """Gracefully shutdown JDT.LS."""
        if not self._running and self._process is None:
            return

        self._shutting_down = True

        try:
            if self._running:
                await self.request(LSP_SHUTDOWN, timeout=10)
                await self.notify(LSP_EXIT)
        except Exception as e:
            logger.warning("Error during LSP shutdown: %s", e)
        finally:
            self._running = False
            self._initialized = False
            self._cancel_pending_requests(LspRequestError("JDT.LS client shut down"))

        await self._stop_processor_task()
        self._terminate_process()
        self.clear_document_state()

        logger.info("JDT.LS shutdown for %s", self.project_root)

    async def _cleanup_after_failure(self, exc: Exception) -> None:
        """Clean up partially started state after startup failure."""
        logger.warning("Cleaning up failed JDT.LS startup for %s: %s", self.project_root, exc)
        self._shutting_down = True
        self._running = False
        self._initialized = False
        self._cancel_pending_requests(LspRequestError(f"JDT.LS startup failed: {exc}"))
        await self._stop_processor_task()
        self._terminate_process()
        self.clear_document_state()
        self._shutting_down = False

    async def _stop_processor_task(self) -> None:
        if self._processor_task is None:
            return

        self._processor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._processor_task
        self._processor_task = None

    def _terminate_process(self) -> None:
        if self._process is None:
            return

        process = self._process
        with contextlib.suppress(Exception):
            if process.stdin is not None:
                process.stdin.close()

        if process.poll() is None:
            with contextlib.suppress(Exception):
                process.terminate()
                process.wait(timeout=5)
            if process.poll() is None:
                with contextlib.suppress(Exception):
                    process.kill()
                    process.wait(timeout=5)

        self._process = None
        current = threading.current_thread()
        for thread in (self._reader_thread, self._stderr_thread, self._watcher_thread):
            if thread is not None and thread is not current:
                thread.join(timeout=1)
        self._reader_thread = None
        self._stderr_thread = None
        self._watcher_thread = None

    def _cancel_pending_requests(self, error: Exception) -> None:
        pending = list(self._pending_requests.values())
        self._pending_requests.clear()

        def cancel() -> None:
            for future in pending:
                if not future.done():
                    future.set_exception(error)

        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(cancel)
        else:
            cancel()


    @property
    def is_initialized(self) -> bool:
        """Check if client is fully initialized."""
        return self._initialized and self._running
