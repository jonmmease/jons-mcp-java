"""JDT.LS client with subprocess management and LSP protocol."""

import asyncio
import json
import logging
import os
import queue
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from jons_mcp_java.constants import (
    JDTLS_INIT_TIMEOUT,
    JDTLS_MEMORY,
    JDTLS_TIMEOUT,
    LSP_CLIENT_REGISTER_CAPABILITY,
    LSP_CLIENT_UNREGISTER_CAPABILITY,
    LSP_EXIT,
    LSP_INITIALIZE,
    LSP_INITIALIZED,
    LSP_SHUTDOWN,
    LSP_TEXT_DOCUMENT_DID_CHANGE,
    LSP_TEXT_DOCUMENT_DID_OPEN,
    LSP_WINDOW_WORK_DONE_PROGRESS_CREATE,
    LSP_WORKSPACE_CONFIGURATION,
    LSP_WORKSPACE_WORKSPACE_FOLDERS,
    JDTLS_LANGUAGE_STATUS,
    JDTLS_PROGRESS,
)
from jons_mcp_java.exceptions import JdtlsNotInitializedError, LspRequestError
from jons_mcp_java.locator import JdtlsInstallation, locate_jdtls
from jons_mcp_java.utils import path_to_uri

logger = logging.getLogger(__name__)


class JdtlsClient:
    """LSP client for a single JDT.LS instance."""

    def __init__(self, project_root: Path, workspace_data_dir: Path):
        self.project_root = project_root.resolve()
        self.workspace_data_dir = workspace_data_dir
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._processor_task: asyncio.Task | None = None
        self._message_queue: queue.Queue = queue.Queue()
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._notification_handlers: dict[str, list[Callable]] = {}
        self._request_id = 0
        self._writer_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._shutting_down = False
        self._initialized = False

        # Document tracking
        self._opened_files: set[str] = set()
        self._doc_versions: dict[str, int] = {}

        # Server request handlers
        self._request_handlers: dict[str, Callable] = {
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

        self._loop = asyncio.get_event_loop()

        # Locate JDT.LS installation
        installation = locate_jdtls()

        # Build command
        cmd = self._build_jdtls_command(installation)
        logger.info(f"Starting JDT.LS for {self.project_root}")
        logger.debug(f"Command: {' '.join(cmd)}")

        # Ensure workspace data directory exists
        self.workspace_data_dir.mkdir(parents=True, exist_ok=True)

        # Start subprocess
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.project_root),
        )

        self._running = True

        # Start reader threads
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()

        # Start process watcher
        self._start_process_watcher()

        # Start message processor
        self._processor_task = asyncio.create_task(self._process_messages())

        # Initialize LSP
        await self._initialize()

        # Wait for ready
        await self.wait_for_ready(timeout=JDTLS_INIT_TIMEOUT)

        self._initialized = True
        logger.info(f"JDT.LS initialized for {self.project_root}")

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
                content_length = int(line_str.split(":")[1].strip())

                # Read empty line (header separator)
                self._process.stdout.readline()

                # Read body
                body = self._process.stdout.read(content_length)
                if not body:
                    break

                message = json.loads(body.decode("utf-8"))
                self._message_queue.put(message)

            except Exception as e:
                if self._running:
                    logger.error(f"Reader error: {e}")

    def _stderr_loop(self) -> None:
        """Read stderr and log to file."""
        log_path = self.workspace_data_dir / "jdtls-stderr.log"
        try:
            with open(log_path, "a") as log_file:
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
                        logger.debug(f"JDT.LS stderr: {decoded.strip()}")
        except Exception as e:
            if self._running:
                logger.error(f"Stderr reader error: {e}")

    def _start_process_watcher(self) -> None:
        """Watch for process death and cancel pending requests."""
        def watcher():
            if self._process:
                self._process.wait()  # Blocks until process exits
            if not self._shutting_down:
                logger.error("JDT.LS process died unexpectedly")
                # Cancel all pending requests
                for future in self._pending_requests.values():
                    if not future.done():
                        self._loop.call_soon_threadsafe(
                            future.set_exception,
                            LspRequestError("JDT.LS process died")
                        )
                self._pending_requests.clear()
                self._running = False

        thread = threading.Thread(target=watcher, daemon=True)
        thread.start()

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

    async def _handle_configuration(self, params: dict) -> list:
        """Return Java configuration settings."""
        # Return config for each requested scope
        return [{"java": {}} for _ in params.get("items", [])]

    async def _handle_register_capability(self, params: dict) -> None:
        """Acknowledge capability registration."""
        return None  # Empty response = success

    async def _handle_unregister_capability(self, params: dict) -> None:
        """Acknowledge capability unregistration."""
        return None

    async def _handle_workspace_folders(self, params: dict) -> list:
        """Return workspace folders."""
        return [{"uri": self.project_root.as_uri(), "name": self.project_root.name}]

    async def _handle_progress_create(self, params: dict) -> None:
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

        future: asyncio.Future = asyncio.Future()
        self._pending_requests[request_id] = future

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }

        self._write_message(message)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise LspRequestError(f"Request {method} timed out after {timeout}s")

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
            return

        with self._writer_lock:
            body = json.dumps(message).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
            self._process.stdin.write(header + body)
            self._process.stdin.flush()

    def on_notification(self, method: str, handler: Callable) -> None:
        """Register a notification handler."""
        if method not in self._notification_handlers:
            self._notification_handlers[method] = []
        self._notification_handlers[method].append(handler)

    # Initialization

    async def _initialize(self) -> dict:
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
                    "codeAction": {"codeActionLiteralSupport": {"codeActionKind": {"valueSet": []}}},
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
            }
        }

        result = await self.request(LSP_INITIALIZE, init_params, timeout=60)
        await self.notify(LSP_INITIALIZED, {})
        return result

    async def wait_for_ready(self, timeout: float = 120.0) -> bool:
        """Wait for JDT.LS to finish importing and be ready."""
        ready_event = asyncio.Event()

        def on_status(params):
            message = params.get("message", "")
            msg_type = params.get("type", "")
            logger.debug(f"JDT.LS status: {msg_type} - {message}")
            if "ServiceReady" in message or msg_type == "Started":
                ready_event.set()

        def on_progress(params):
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

    async def ensure_file_open(self, file_path: str) -> None:
        """Ensure file is open in JDT.LS for analysis."""
        file_uri = path_to_uri(file_path)

        if file_uri in self._opened_files:
            return

        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Track version
        self._doc_versions[file_uri] = 1

        # Send didOpen
        await self.notify(LSP_TEXT_DOCUMENT_DID_OPEN, {
            "textDocument": {
                "uri": file_uri,
                "languageId": "java",
                "version": 1,
                "text": content,
            }
        })

        self._opened_files.add(file_uri)

    async def update_file(self, file_path: str, content: str) -> None:
        """Update file content in JDT.LS."""
        file_uri = path_to_uri(file_path)

        if file_uri not in self._opened_files:
            await self.ensure_file_open(file_path)
            return

        # Increment version
        self._doc_versions[file_uri] += 1

        await self.notify(LSP_TEXT_DOCUMENT_DID_CHANGE, {
            "textDocument": {
                "uri": file_uri,
                "version": self._doc_versions[file_uri],
            },
            "contentChanges": [{"text": content}],
        })

    # Shutdown

    async def shutdown(self) -> None:
        """Gracefully shutdown JDT.LS."""
        if not self._running:
            return

        self._shutting_down = True
        self._running = False

        try:
            # Send LSP shutdown
            await self.request(LSP_SHUTDOWN, timeout=10)
            await self.notify(LSP_EXIT)
        except Exception as e:
            logger.warning(f"Error during LSP shutdown: {e}")

        # Cancel processor task
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        # Terminate process
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()

        logger.info(f"JDT.LS shutdown for {self.project_root}")

    @property
    def is_initialized(self) -> bool:
        """Check if client is fully initialized."""
        return self._initialized and self._running
