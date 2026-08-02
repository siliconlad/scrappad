"""Interruptible Python worker process used by the terminal UI."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import signal
import threading
from dataclasses import dataclass
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

    async def sync(self, source: str) -> KernelResponse:
        return await self._request({"operation": "sync", "source": source})

    async def reset(self, source: str) -> KernelResponse:
        return await self._request({"operation": "reset", "source": source})

    async def execute(self, command: str) -> KernelResponse:
        return await self._request({"operation": "execute", "command": command})

    async def variables(self) -> KernelResponse:
        return await self._request({"operation": "variables"})

    async def _request(self, message: dict[str, str]) -> KernelResponse:
        if self._closed:
            return KernelResponse("error", error="Python worker is closed.")
        self._request_in_flight.set()
        try:
            return await asyncio.to_thread(self._round_trip, message)
        except (BrokenPipeError, EOFError, OSError):
            return KernelResponse(
                "error",
                error="Python worker stopped unexpectedly. Restart Scrappad to continue.",
            )
        finally:
            self._request_active.clear()
            self._request_in_flight.clear()
            self._interrupt_requested.clear()

    def _round_trip(self, message: dict[str, str]) -> KernelResponse:
        self._connection.send(message)
        acknowledgement = self._connection.recv()
        if acknowledgement != "started":
            raise RuntimeError("Invalid acknowledgement from Python worker")
        self._request_active.set()
        if self._interrupt_requested.is_set():
            self._send_interrupt()
        response = self._connection.recv()
        if not isinstance(response, KernelResponse):
            raise TypeError("Invalid response from Python worker")
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
                response = _dispatch(runtime, operation, message)
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
) -> KernelResponse:
    if operation == "sync":
        result = runtime.sync(message["source"])
        return KernelResponse(
            result.state,
            output=result.output,
            error=result.error,
            interrupted=result.interrupted,
            symbol_count=len(runtime.visible_names),
        )
    if operation == "reset":
        result = runtime.reset(message["source"])
        return KernelResponse(
            result.state,
            output=result.output,
            error=result.error,
            interrupted=result.interrupted,
            symbol_count=len(runtime.visible_names),
        )
    if operation == "execute":
        result = runtime.execute(message["command"])
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
