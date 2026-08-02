"""Textual user interface for Scrappad."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar, Literal

from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, RichLog, Static, TextArea

from scrappad.kernel import KernelClient, KernelResponse

STARTER = ""


class ReplInput(Input):
    """A one-line input with shell-style command history."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.history_index = 0
        self._draft = ""

    def remember(self, command: str) -> None:
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history_index = len(self.history)
        self._draft = ""

    def on_key(self, event: events.Key) -> None:
        if event.key == "up" and self.history:
            if self.history_index == len(self.history):
                self._draft = self.value
            self.history_index = max(0, self.history_index - 1)
            self.value = self.history[self.history_index]
            self.cursor_position = len(self.value)
            event.prevent_default()
            event.stop()
        elif event.key == "down" and self.history:
            self.history_index = min(len(self.history), self.history_index + 1)
            self.value = (
                self._draft
                if self.history_index == len(self.history)
                else self.history[self.history_index]
            )
            self.cursor_position = len(self.value)
            event.prevent_default()
            event.stop()


class ScrappadApp(App[None]):
    """Split-screen Python editor with a synchronized REPL."""

    TITLE = "Scrappad"
    SUB_TITLE = "live Python scratchpad"
    HORIZONTAL_BREAKPOINTS: ClassVar[list[tuple[int, str]]] = [
        (0, "-narrow"),
        (100, "-wide"),
    ]

    CSS = """
    Screen {
        background: #0d1117;
        color: #d8dee9;
    }

    #workspace {
        height: 1fr;
    }

    Screen.-wide #workspace {
        layout: horizontal;
    }

    Screen.-narrow #workspace {
        layout: vertical;
    }

    .pane {
        width: 1fr;
        height: 100%;
        border: round #30363d;
        background: #0d1117;
    }

    Screen.-narrow .pane {
        width: 100%;
        height: 1fr;
    }

    .pane:focus-within {
        border: round #58a6ff;
    }

    .pane-title {
        height: 1;
        padding: 0 1;
        background: #161b22;
        color: #8b949e;
        text-style: bold;
    }

    #editor {
        height: 1fr;
        border: none;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    #repl-log {
        height: 1fr;
        padding: 0 1;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    #repl-input-row {
        height: 1;
        margin: 0 1;
        background: #0d1117;
    }

    #repl-prompt {
        width: 4;
        height: 1;
        color: #58a6ff;
        background: #0d1117;
        text-style: bold;
    }

    #repl-input-row:focus-within #repl-prompt {
        color: #79c0ff;
    }

    #repl-input {
        width: 1fr;
        height: 1;
        padding: 0;
        border: none;
        background: #0d1117;
    }

    #repl-input:focus {
        border: none;
        background: #0d1117;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #161b22;
        color: #8b949e;
    }

    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f2", "switch_pane", "Switch pane", priority=True),
        Binding("ctrl+left,ctrl+up", "focus_editor", "Editor", priority=True),
        Binding("ctrl+right,ctrl+down", "focus_repl", "REPL", priority=True),
        Binding("f5", "sync", "Run editor", priority=True),
        Binding("ctrl+c", "interrupt", "Interrupt", priority=True, show=False),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+l", "clear_repl", "Clear REPL", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.kernel = KernelClient(path)
        self.source = path.read_text(encoding="utf-8") if path.exists() else STARTER
        self._last_error = ""
        self._dirty = False
        self._needs_sync = bool(self.source)
        self._edit_revision = 0
        self._symbol_count = 0
        self._active_pane: Literal["editor", "repl"] = "editor"
        self._execution_kind: Literal["editor", "repl"] | None = None
        self._execution_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="editor-pane"):
                yield Label(
                    f"EDITOR  {self.path}", classes="pane-title", id="editor-title"
                )
                yield TextArea(
                    self.source,
                    language="python",
                    show_line_numbers=True,
                    soft_wrap=True,
                    tab_behavior="indent",
                    id="editor",
                )
            with Vertical(classes="pane", id="repl-pane"):
                yield Label("REPL  shared namespace", classes="pane-title")
                yield RichLog(
                    id="repl-log",
                    highlight=True,
                    markup=False,
                    wrap=True,
                    max_lines=2_000,
                )
                with Horizontal(id="repl-input-row"):
                    yield Static(">>>", id="repl-prompt")
                    yield ReplInput(
                        id="repl-input",
                        placeholder="expression or :help",
                    )
        yield Static("Starting…", id="status")

    def on_mount(self) -> None:
        self.query_one("#editor", TextArea).focus()
        if self._needs_sync:
            self._show_pending_status()
        else:
            self._show_ready_status()

    def on_unmount(self) -> None:
        if self._execution_task is not None:
            self._execution_task.cancel()
        self.kernel.close()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "editor":
            return
        self._dirty = True
        self._needs_sync = True
        self._edit_revision += 1
        self._update_editor_title()
        self._show_pending_status()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id == "editor":
            self._active_pane = "editor"
        elif (
            event.widget.id in {"repl-input", "repl-log"}
            and self._active_pane != "repl"
        ):
            self._active_pane = "repl"
            self._sync_if_needed()

    def _sync_if_needed(self) -> None:
        if self._needs_sync:
            self._start_editor_sync()

    def _start_editor_sync(self, *, force: bool = False, reset: bool = False) -> None:
        if self._execution_kind is not None:
            self.notify("Python is already running. Press Ctrl+C to interrupt it.")
            return
        if not force and not self._needs_sync:
            return

        revision = self._edit_revision
        source = self.query_one("#editor", TextArea).text
        self._execution_kind = "editor"
        status = self.query_one("#status", Static)
        status.update("● Running editor… Ctrl+C to interrupt")
        status.styles.color = "#58a6ff"
        self._execution_task = asyncio.create_task(
            self._finish_editor_sync(source, revision, reset=reset)
        )

    async def _finish_editor_sync(
        self,
        source: str,
        revision: int,
        *,
        reset: bool,
    ) -> None:
        try:
            response = (
                await self.kernel.reset(source)
                if reset
                else await self.kernel.sync(source)
            )
        except asyncio.CancelledError:
            return
        finally:
            self._execution_kind = None
            self._execution_task = None

        if not self.is_mounted:
            return
        self._show_sync_result(response, revision)
        if reset and response.state == "ok":
            self.query_one("#repl-log", RichLog).write(
                "REPL-only names were discarded."
            )

    def _show_sync_result(self, result: KernelResponse, revision: int) -> None:
        status = self.query_one("#status", Static)
        log = self.query_one("#repl-log", RichLog)
        self._symbol_count = result.symbol_count
        if result.output:
            log.write(Text("editor output", style="bold #d29922"))
            log.write(result.output.rstrip("\n"))

        if result.interrupted:
            status.update("● Interrupted — switch to the REPL or press F5 to retry")
            status.styles.color = "#d29922"
            self.query_one("#editor", TextArea).focus()
            return

        if result.state == "ok":
            if revision == self._edit_revision:
                self._needs_sync = False
                self._show_ready_status()
            else:
                self._show_pending_status()
            self._last_error = ""
        elif result.state == "incomplete":
            status.update(
                "● Incomplete Python — last working namespace is still active"
            )
            status.styles.color = "#d29922"
        else:
            status.update("● Editor error — last working namespace is still active")
            status.styles.color = "#f85149"
            if result.error and result.error != self._last_error:
                log.write(Text("editor error", style="bold #f85149"))
                log.write(result.error)
                self._last_error = result.error

    def _show_pending_status(self) -> None:
        status = self.query_one("#status", Static)
        status.update("● Changes pending — switch to the REPL to load them")
        status.styles.color = "#d29922"

    def _show_ready_status(self) -> None:
        status = self.query_one("#status", Static)
        status.update(
            f"● Synced  {self._symbol_count} symbols available  |  {self.path.name}"
        )
        status.styles.color = "#3fb950"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "repl-input":
            return
        if self._execution_kind is not None:
            self.notify("Python is still running. Press Ctrl+C to interrupt it.")
            return
        command = event.value.strip()
        repl_input = self.query_one("#repl-input", ReplInput)
        repl_input.value = ""
        if not command:
            return
        repl_input.remember(command)
        log = self.query_one("#repl-log", RichLog)
        prompt = Text(">>> ", style="bold #58a6ff")
        prompt.append(command, style="#d8dee9")
        log.write(prompt)

        if command.startswith(":"):
            self._handle_command(command)
        else:
            self._start_repl_execution(command)

    def _start_repl_execution(self, command: str) -> None:
        self._execution_kind = "repl"
        status = self.query_one("#status", Static)
        status.update("● Running REPL… Ctrl+C to interrupt")
        status.styles.color = "#58a6ff"
        self._execution_task = asyncio.create_task(self._finish_repl_execution(command))

    async def _finish_repl_execution(self, command: str) -> None:
        try:
            result = await self.kernel.execute(command)
        except asyncio.CancelledError:
            return
        finally:
            self._execution_kind = None
            self._execution_task = None

        if not self.is_mounted:
            return
        self._show_repl_result(result)

    def _show_repl_result(self, result: KernelResponse) -> None:
        log = self.query_one("#repl-log", RichLog)
        self._symbol_count = result.symbol_count
        if result.output:
            log.write(result.output.rstrip("\n"))
        if result.has_display:
            log.write(Syntax(result.display, "python", word_wrap=True))
        if result.error:
            log.write(Text(result.error, style="#f85149"))
        if self._needs_sync:
            self._show_pending_status()
        else:
            self._show_ready_status()

    def _handle_command(self, command: str) -> None:
        log = self.query_one("#repl-log", RichLog)
        name = command.split(maxsplit=1)[0].lower()
        if name in {":help", ":h", ":?"}:
            log.write(
                ":vars   show live names\n"
                ":sync   run the editor now\n"
                ":reset  discard REPL-only names and reload the editor\n"
                ":clear  clear this output\n"
                ":help   show this help"
            )
        elif name == ":vars":
            self._start_variable_inspection()
        elif name == ":sync":
            self._start_editor_sync(force=True)
        elif name == ":reset":
            self._start_editor_sync(force=True, reset=True)
        elif name == ":clear":
            log.clear()
        else:
            log.write(Text(f"Unknown command: {name}. Try :help", style="#f85149"))

    def _start_variable_inspection(self) -> None:
        self._execution_kind = "repl"
        status = self.query_one("#status", Static)
        status.update("● Inspecting variables… Ctrl+C to interrupt")
        status.styles.color = "#58a6ff"
        self._execution_task = asyncio.create_task(self._finish_variable_inspection())

    async def _finish_variable_inspection(self) -> None:
        try:
            result = await self.kernel.variables()
        except asyncio.CancelledError:
            return
        finally:
            self._execution_kind = None
            self._execution_task = None

        if not self.is_mounted:
            return
        log = self.query_one("#repl-log", RichLog)
        self._symbol_count = result.symbol_count
        if result.interrupted or result.error:
            log.write(Text(result.error or "KeyboardInterrupt", style="#f85149"))
        elif result.variables:
            table = Table(
                "name", "type", "value", box=None, header_style="bold #58a6ff"
            )
            for variable in result.variables:
                table.add_row(
                    Text(variable.name),
                    Text(variable.type_name),
                    Text(variable.value),
                )
            log.write(table)
        else:
            log.write("No names are currently defined.")
        if self._needs_sync:
            self._show_pending_status()
        else:
            self._show_ready_status()

    def action_switch_pane(self) -> None:
        editor = self.query_one("#editor", TextArea)
        repl_input = self.query_one("#repl-input", ReplInput)
        if editor.has_focus:
            repl_input.focus()
        else:
            editor.focus()

    def action_focus_editor(self) -> None:
        self.query_one("#editor", TextArea).focus()

    def action_focus_repl(self) -> None:
        self.query_one("#repl-input", ReplInput).focus()

    def action_sync(self) -> None:
        self._start_editor_sync(force=True)

    def action_interrupt(self) -> None:
        if self._execution_kind is None:
            focused = self.focused
            copy_action = getattr(focused, "action_copy", None)
            if callable(copy_action):
                copy_action()
            return

        execution_kind = self._execution_kind
        if self.kernel.interrupt():
            status = self.query_one("#status", Static)
            status.update("● Interrupting Python…")
            status.styles.color = "#d29922"
            if execution_kind == "editor":
                self.query_one("#editor", TextArea).focus()

    def action_save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                self.query_one("#editor", TextArea).text, encoding="utf-8"
            )
        except OSError as exc:
            self.notify(f"Could not save: {exc}", severity="error")
            return
        self._dirty = False
        self._update_editor_title()
        self.notify(f"Saved {self.path}")

    def action_clear_repl(self) -> None:
        self.query_one("#repl-log", RichLog).clear()

    def _update_editor_title(self) -> None:
        marker = " ●" if self._dirty else ""
        self.query_one("#editor-title", Label).update(f"EDITOR  {self.path}{marker}")
