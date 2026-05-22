"""JDT.LS client protocol and document sync tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from jons_mcp_java.client import JdtlsClient
from jons_mcp_java.constants import (
    LSP_EXIT,
    LSP_SHUTDOWN,
    LSP_TEXT_DOCUMENT_DID_CHANGE,
    LSP_TEXT_DOCUMENT_DID_CLOSE,
    LSP_TEXT_DOCUMENT_DID_OPEN,
    LSP_TEXT_DOCUMENT_DID_SAVE,
)
from jons_mcp_java.exceptions import LspRequestError


class RecordingClient(JdtlsClient):
    def __init__(self, project_root: Path):
        super().__init__(project_root, project_root / ".jdtls")
        self.notifications: list[tuple[str, dict[str, Any]]] = []

    async def notify(self, method: str, params: dict | None = None) -> None:
        self.notifications.append((method, params or {}))


@pytest.mark.asyncio
async def test_ensure_file_open_sends_empty_content_as_valid_text(
    tmp_path: Path,
) -> None:
    java_file = tmp_path / "Empty.java"
    java_file.write_text("", encoding="utf-8")
    client = RecordingClient(tmp_path)

    changed = await client.ensure_file_open(java_file)

    assert changed is True
    method, params = client.notifications[-1]
    assert method == LSP_TEXT_DOCUMENT_DID_OPEN
    assert params["textDocument"]["text"] == ""


@pytest.mark.asyncio
async def test_ensure_file_open_refreshes_changed_disk_content(tmp_path: Path) -> None:
    java_file = tmp_path / "Main.java"
    java_file.write_text("class A {}\n", encoding="utf-8")
    client = RecordingClient(tmp_path)
    await client.ensure_file_open(java_file)

    java_file.write_text("class B {}\n", encoding="utf-8")
    changed = await client.ensure_file_open(java_file)

    assert changed is True
    methods = [method for method, _params in client.notifications]
    assert LSP_TEXT_DOCUMENT_DID_CHANGE in methods
    assert LSP_TEXT_DOCUMENT_DID_SAVE in methods
    change = next(
        params
        for method, params in client.notifications
        if method == LSP_TEXT_DOCUMENT_DID_CHANGE
    )
    assert change["contentChanges"] == [{"text": "class B {}\n"}]


@pytest.mark.asyncio
async def test_ensure_file_open_closes_deleted_open_document(tmp_path: Path) -> None:
    java_file = tmp_path / "Main.java"
    java_file.write_text("class A {}\n", encoding="utf-8")
    client = RecordingClient(tmp_path)
    await client.ensure_file_open(java_file)

    java_file.unlink()
    changed = await client.ensure_file_open(java_file)

    assert changed is True
    assert client.notifications[-1][0] == LSP_TEXT_DOCUMENT_DID_CLOSE


class TimeoutClient(JdtlsClient):
    def __init__(self, project_root: Path):
        super().__init__(project_root, project_root / ".jdtls")
        self._running = True

    def _write_message(self, message: dict) -> None:
        return None


@pytest.mark.asyncio
async def test_request_timeout_cleans_pending_waiter(tmp_path: Path) -> None:
    client = TimeoutClient(tmp_path)

    with pytest.raises(LspRequestError):
        await client.request("java/test", timeout=0.01)

    assert client._pending_requests == {}


class ShutdownClient(JdtlsClient):
    def __init__(self, project_root: Path):
        super().__init__(project_root, project_root / ".jdtls")
        self._running = True
        self.calls: list[str] = []

    async def request(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 60,
    ) -> Any:
        assert self._running is True
        self.calls.append(method)
        return None

    async def notify(self, method: str, params: dict | None = None) -> None:
        assert self._running is True
        self.calls.append(method)


@pytest.mark.asyncio
async def test_shutdown_sends_lsp_shutdown_before_marking_not_running(
    tmp_path: Path,
) -> None:
    client = ShutdownClient(tmp_path)

    await client.shutdown()

    assert client.calls == [LSP_SHUTDOWN, LSP_EXIT]
    assert client.is_initialized is False


class FakeStdout:
    def __init__(self, chunks: list[bytes], body: bytes):
        self.chunks = chunks
        self.body = body

    def readline(self) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        return b""

    def read(self, length: int) -> bytes:
        return self.body[:length]


class FakeProcess:
    def __init__(self, stdout: FakeStdout):
        self.stdout = stdout
        self.stderr = None


def test_reader_loop_skips_non_lsp_stdout_and_reads_message(tmp_path: Path) -> None:
    message = {"jsonrpc": "2.0", "id": 1, "result": "ok"}
    body = json.dumps(message).encode("utf-8")
    stdout = FakeStdout(
        [
            b"plain log line\n",
            f"Content-Length: {len(body)}\r\n".encode(),
            b"\r\n",
        ],
        body,
    )
    client = JdtlsClient(tmp_path, tmp_path / ".jdtls")
    client._process = FakeProcess(stdout)  # type: ignore[assignment]
    client._running = True

    client._reader_loop()

    assert client._message_queue.get_nowait() == message


class ExitedProcess:
    def wait(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_process_death_error_points_to_stderr_log(tmp_path: Path) -> None:
    client = JdtlsClient(tmp_path, tmp_path / ".jdtls")
    client._process = ExitedProcess()  # type: ignore[assignment]
    client._running = True
    client._loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    client._pending_requests[1] = future

    client._start_process_watcher()

    with pytest.raises(LspRequestError, match="jdtls-stderr.log"):
        await future
