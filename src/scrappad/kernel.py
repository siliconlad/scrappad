"""Interruptible Python worker process used by the terminal UI."""

from __future__ import annotations

import asyncio
import io
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal

from scrappad.runtime import PythonRuntime, display_value

ResponseState = Literal["ok", "incomplete", "error"]


@dataclass(frozen=True)
class VariableSummary:
    name: str
    type_name: str
    value: str


@dataclass(frozen=True)
class KernelResponse:
    state: ResponseState
    output: str = ""
    error: str = ""
    display: str = ""
    has_display: bool = False
    interrupted: bool = False
    symbol_count: int = 0
    variables: tuple[VariableSummary, ...] = ()


class KernelClient:
    """Async facade over a persistent child process that owns the namespace."""

    def __init__(self, filename: str | Path) -> None:
        self.filename = str(filename)
        self._context = multiprocessing.get_context("spawn")
        self._connection: Connection
        self._process: multiprocessing.Process
        self._closed = False
        self._request_in_flight = threading.Event()
        self._request_active = threading.Event()
        self._interrupt_requested = threading.Event()
        self._start()

    @property
    def pid(self) -> int | None:
        return self._process.pid

    def _start(self) -> None:
        parent, child = self._context.Pipe()
        self._connection = parent
        self._process = self._context.Process(
            target=_kernel_main,
            args=(child, self.filename),
            name="scrappad-kernel",
            daemon=True,
        )
        self._process.start()
        child.close()

    async def sync(
        self,
        source: str,
        on_output: Callable[[str], None] | None = None,
    ) -> KernelResponse:
        return await self._request(
            {"operation": "sync", "source": source},
            on_output=on_output,
        )

    async def reset(
        self,
        source: str,
        on_output: Callable[[str], None] | None = None,
    ) -> KernelResponse:
        return await self._request(
            {"operation": "reset", "source": source},
            on_output=on_output,
        )

    async def execute(
        self,
        command: str,
        on_output: Callable[[str], None] | None = None,
    ) -> KernelResponse:
        return await self._request(
            {"operation": "execute", "command": command},
            on_output=on_output,
        )

    async def variables(self) -> KernelResponse:
        return await self._request({"operation": "variables"})

    async def _request(
        self,
        message: dict[str, str],
        on_output: Callable[[str], None] | None = None,
    ) -> KernelResponse:
        if self._closed:
            return KernelResponse("error", error="Python worker is closed.")
        self._request_in_flight.set()
        try:
            return await asyncio.to_thread(self._round_trip, message, on_output)
        except (BrokenPipeError, EOFError, OSError):
            return KernelResponse(
                "error",
                error="Python worker stopped unexpectedly. Restart Scrappad to continue.",
            )
        finally:
            self._request_active.clear()
            self._request_in_flight.clear()
            self._interrupt_requested.clear()

    def _round_trip(
        self,
        message: dict[str, str],
        on_output: Callable[[str], None] | None,
    ) -> KernelResponse:
        self._connection.send(message)
        acknowledgement = self._connection.recv()
        if acknowledgement != "started":
            raise RuntimeError("Invalid acknowledgement from Python worker")
        self._request_active.set()
        if self._interrupt_requested.is_set():
            self._send_interrupt()
        captured_chunks: list[str] = []
        captured_length = 0
        output_truncated = False
        while True:
            response = self._connection.recv()
            if (
                isinstance(response, tuple)
                and len(response) == 2
                and response[0] == "output"
                and isinstance(response[1], str)
            ):
                chunk = response[1]
                if on_output is not None:
                    on_output(chunk)
                else:
                    remaining = 100_000 - captured_length
                    if remaining > 0:
                        captured_chunks.append(chunk[:remaining])
                        captured_length += min(len(chunk), remaining)
                    if len(chunk) > max(remaining, 0):
                        output_truncated = True
                continue
            if not isinstance(response, KernelResponse):
                raise TypeError("Invalid response from Python worker")
            if on_output is None and captured_chunks:
                output = "".join(captured_chunks)
                if output_truncated:
                    output += "\n... <output truncated>\n"
                response = replace(response, output=output + response.output)
            return response

    def interrupt(self) -> bool:
        """Interrupt active Python code while keeping the worker namespace alive."""

        if (
            self._closed
            or not self._request_in_flight.is_set()
            or not self._process.is_alive()
            or self._process.pid is None
        ):
            return False
        self._interrupt_requested.set()
        if not self._request_active.is_set():
            return True
        self._send_interrupt()
        return True

    def _send_interrupt(self) -> None:
        if os.name == "posix":
            assert self._process.pid is not None
            os.kill(self._process.pid, signal.SIGINT)
            return

        # Windows cannot reliably deliver SIGINT to this detached worker. Stop
        # it so the UI remains responsive; the user can restart Scrappad.
        self._process.terminate()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._process.is_alive():
            self._process.terminate()
        self._process.join(timeout=1)
        self._connection.close()


def _kernel_main(connection: Connection, filename: str) -> None:
    """Own the live namespace and service one execution request at a time."""

    runtime = PythonRuntime(filename)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        while True:
            message = connection.recv()
            operation = message.get("operation")
            signal.signal(signal.SIGINT, signal.default_int_handler)
            connection.send("started")
            try:
                response = _dispatch(runtime, operation, message, connection)
            except KeyboardInterrupt:
                response = KernelResponse(
                    "error",
                    error="KeyboardInterrupt",
                    interrupted=True,
                    symbol_count=len(runtime.visible_names),
                )
            except BaseException as exc:  # noqa: BLE001 - keep the worker alive
                response = KernelResponse(
                    "error",
                    error=f"Python worker error: {type(exc).__name__}: {exc}",
                    symbol_count=len(runtime.visible_names),
                )
            finally:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
            connection.send(response)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


def _dispatch(
    runtime: PythonRuntime,
    operation: str | None,
    message: dict[str, str],
    connection: Connection,
) -> KernelResponse:
    if operation == "sync":
        output = _StreamingOutput(connection)
        try:
            result = runtime.sync(message["source"], output_stream=output)
        finally:
            output.finish()
        return KernelResponse(
            result.state,
            output=result.output,
            error=result.error,
            interrupted=result.interrupted,
            symbol_count=len(runtime.visible_names),
        )
    if operation == "reset":
        output = _StreamingOutput(connection)
        try:
            result = runtime.reset(message["source"], output_stream=output)
        finally:
            output.finish()
        return KernelResponse(
            result.state,
            output=result.output,
            error=result.error,
            interrupted=result.interrupted,
            symbol_count=len(runtime.visible_names),
        )
    if operation == "execute":
        output = _StreamingOutput(connection)
        try:
            result = runtime.execute(message["command"], output_stream=output)
        finally:
            output.finish()
        rendered = display_value(result.value) if result.has_value else ""
        return KernelResponse(
            "error" if result.error else "ok",
            output=result.output,
            error=result.error,
            display=rendered,
            has_display=result.has_value,
            interrupted=result.interrupted,
            symbol_count=len(runtime.visible_names),
        )
    if operation == "variables":
        variables = tuple(
            VariableSummary(name, type(value).__name__, display_value(value, 120))
            for name, value in sorted(runtime.visible_names.items())
        )
        return KernelResponse(
            "ok",
            symbol_count=len(runtime.visible_names),
            variables=variables,
        )
    return KernelResponse(
        "error",
        error=f"Unknown worker operation: {operation}",
        symbol_count=len(runtime.visible_names),
    )


class _StreamingOutput(io.TextIOBase):
    """Send stdout and stderr to the client in reasonably sized chunks."""

    def __init__(
        self,
        connection: Connection,
        chunk_size: int = 256,
        pacing_seconds: float = 0.05,
        large_write_size: int = 4_096,
    ) -> None:
        self.connection = connection
        self.chunk_size = chunk_size
        self.pacing_seconds = pacing_seconds
        self.large_write_size = large_write_size
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("output must be text")
        original_length = len(text)
        if len(text) >= self.large_write_size:
            if self._buffer:
                self._emit(self._buffer)
                self._buffer = ""
            while len(text) >= self.large_write_size:
                self._emit(text[: self.large_write_size], pacing_seconds=0.005)
                text = text[self.large_write_size :]
        self._buffer += text
        while len(self._buffer) >= self.chunk_size:
            split_at = self._buffer.rfind("\n", 0, self.chunk_size + 1)
            split_at = self.chunk_size if split_at < 0 else split_at + 1
            self._emit(self._buffer[:split_at])
            self._buffer = self._buffer[split_at:]
        return original_length

    def flush(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""

    def finish(self) -> None:
        if self._buffer:
            self._emit(self._buffer, pacing_seconds=0)
            self._buffer = ""

    def _emit(self, text: str, pacing_seconds: float | None = None) -> None:
        self.connection.send(("output", text))
        pacing_seconds = (
            self.pacing_seconds if pacing_seconds is None else pacing_seconds
        )
        if pacing_seconds:
            time.sleep(pacing_seconds)
