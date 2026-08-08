"""Textual user interface for Scrappad."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import ClassVar, Literal

import tree_sitter_python
from rich.highlighter import Highlighter
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, RichLog, Static, TextArea
from textual.widgets.text_area import TextAreaTheme
from tree_sitter import Language, Parser, Query, QueryCursor

from scrappad.kernel import KernelClient, KernelResponse

STARTER_TEXT = ""
SYNTAX_THEME = "monokai"
EDITOR_SYNTAX_THEME = "scrappad-monokai"

_monokai_text_area_theme = TextAreaTheme.get_builtin_theme(SYNTAX_THEME)
if _monokai_text_area_theme is None:  # pragma: no cover - supplied by Textual
    raise RuntimeError("Textual's Monokai theme is unavailable")
_python_syntax_styles = _monokai_text_area_theme.syntax_styles.copy()
for _upright_token in ("boolean", "constant.builtin"):
    _python_syntax_styles[_upright_token] += Style(italic=False)
_editor_text_area_theme = TextAreaTheme(
    name=EDITOR_SYNTAX_THEME,
    syntax_styles=_python_syntax_styles,
)
_python_language = Language(tree_sitter_python.language())
_python_highlight_query = Query(
    _python_language,
    TextArea._get_builtin_highlight_query("python"),
)


class PythonSyntaxHighlighter(Highlighter):
    """Highlight REPL input with the editor's Tree-sitter token styles."""

    def __init__(self) -> None:
        self._parser = Parser(_python_language)
        self._cached_source: str | None = None
        self._cached_spans: list[tuple[int, int, Style]] = []

    def highlight(self, text: Text) -> None:
        source = text.plain
        if source != self._cached_source:
            self._cached_source = source
            self._cached_spans = self._parse_spans(source)
        for start, end, style in self._cached_spans:
            text.stylize(style, start, end)

    def _parse_spans(self, source: str) -> list[tuple[int, int, Style]]:
        source_bytes = source.encode("utf-8")
        tree = self._parser.parse(source_bytes)
        captures = QueryCursor(_python_highlight_query).captures(tree.root_node)

        byte_to_codepoint = {0: 0}
        byte_offset = 0
        for codepoint, character in enumerate(source, start=1):
            byte_offset += len(character.encode("utf-8"))
            byte_to_codepoint[byte_offset] = codepoint

        spans: list[tuple[int, int, Style]] = []
        get_style = _editor_text_area_theme.syntax_styles.get
        for capture_name, nodes in captures.items():
            style = get_style(capture_name)
            if style is None:
                continue
            for node in nodes:
                start = byte_to_codepoint.get(node.start_byte)
                end = byte_to_codepoint.get(node.end_byte)
                if start is not None and end is not None:
                    spans.append((start, end, style))
        return spans


PYTHON_HIGHLIGHTER = PythonSyntaxHighlighter()


class ReplInput(Input):
    """A one-line input with shell-style command history."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.history: list[str] = []
        self.history_index = 0
        self._draft = ""
        self._withdrawn_value = ""
        self._withdrawn_selection = None
        self.busy = False

    def remember(self, command: str) -> None:
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history_index = len(self.history)
        self._draft = ""

    def withdraw_draft(self) -> None:
        """Temporarily remove the draft while Python is busy."""
        if self._withdrawn_selection is not None:
            return
        self._withdrawn_value = self.value
        self._withdrawn_selection = self.selection
        self.value = ""

    def restore_draft(self) -> None:
        """Restore a draft withdrawn while Python was busy."""
        selection = self._withdrawn_selection
        if selection is None:
            return
        value = self._withdrawn_value
        self._withdrawn_value = ""
        self._withdrawn_selection = None
        self.value = value
        self.selection = selection

    def on_key(self, event: events.Key) -> None:
        if self.busy:
            event.prevent_default()
            event.stop()
        elif event.key == "up" and self.history:
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

    TITLE = "scrappad"
    SUB_TITLE = "live Python scratchpad"
    HORIZONTAL_BREAKPOINTS = [
        (0, "-narrow"),
        (100, "-wide"),
    ]

    CSS = """
    Screen {
        margin: 0;
        padding: 0;
        background: #0d1117;
        color: #d8dee9;
    }

    #workspace {
        height: 1fr;
        margin: 0;
        padding: 0;
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

    #editor {
        height: 1fr;
        border: none;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    #repl-log {
        height: auto;
        max-height: 1fr;
        padding: 0 1;
        background: #0d1117;
        scrollbar-size: 0 0;
    }

    #repl-log:focus {
        background-tint: transparent;
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
        background-tint: transparent;
    }

    #bottom-bar {
        height: 1;
        margin: 0;
        padding: 0;
    }

    .bar-item {
        height: 1;
        padding: 0 1;
        background: #161b22;
    }

    #editor-status,
    #repl-status {
        width: 1fr;
        color: #8b949e;
    }

    #file-path {
        width: auto;
        max-width: 50%;
        color: #8b949e;
        text-align: center;
    }

    #repl-status {
        text-align: right;
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
        self.source = path.read_text(encoding="utf-8") if path.exists() else STARTER_TEXT

        self._last_error = ""
        self._synced_source = STARTER_TEXT
        self._needs_sync = self.source != self._synced_source
        self._symbol_count = 0

        self._active_pane: Literal["editor", "repl"] = "editor"
        self._execution_kind: Literal["editor", "repl"] | None = None
        self._execution_task: asyncio.Task[None] | None = None
        self._restore_repl_focus = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="editor-pane"):
                editor = TextArea(
                    self.source,
                    language="python",
                    show_line_numbers=True,
                    soft_wrap=True,
                    tab_behavior="indent",
                    highlight_cursor_line=False,
                    id="editor",
                )
                editor.register_theme(_editor_text_area_theme)
                editor.theme = EDITOR_SYNTAX_THEME
                yield editor
            with Vertical(classes="pane", id="repl-pane"):
                yield RichLog(
                    id="repl-log",
                    highlight=False,
                    markup=False,
                    wrap=True,
                    max_lines=2_000,
                )
                with Horizontal(id="repl-input-row"):
                    yield Static(">>>", id="repl-prompt")
                    yield ReplInput(
                        id="repl-input",
                        placeholder="expression or :help",
                        highlighter=PYTHON_HIGHLIGHTER,
                        select_on_focus=False,
                    )
        with Horizontal(id="bottom-bar"):
            yield Static(classes="bar-item", id="editor-status")
            yield Static(
                str(self.path.resolve()),
                classes="bar-item",
                id="file-path",
            )
            yield Static(classes="bar-item", id="repl-status")

    def on_mount(self) -> None:
        self.query_one("#editor", TextArea).focus()
        self.call_after_refresh(self._fit_repl_log)
        if self._needs_sync:
            self._show_editor_pending_status()
        else:
            self._show_editor_no_changes_status()
        self._show_repl_ready_status()

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._fit_repl_log)

    def on_unmount(self) -> None:
        execution_task = self._execution_task
        self._execution_task = None
        self._execution_kind = None
        if execution_task is not None:
            execution_task.cancel()
        self.kernel.close()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "editor":
            return
        was_pending = self._needs_sync
        self._needs_sync = event.text_area.text != self._synced_source
        if self._needs_sync:
            self._show_editor_pending_status()
        elif was_pending:
            self._show_editor_no_changes_status()
        else:
            self._show_editor_state_status()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id == "editor":
            if self._active_pane != "editor":
                self._active_pane = "editor"
                if self._execution_kind is not None:
                    self._show_execution_status()
        elif (
            event.widget.id in {"repl-input", "repl-log"}
            and self._active_pane != "repl"
        ):
            self._active_pane = "repl"
            if self._execution_kind is not None:
                self._show_execution_status()
            else:
                self._sync_if_needed()

    def on_click(self, event: events.Click) -> None:
        if event.widget is not None and event.widget.id == "repl-pane":
            self.query_one("#repl-input", ReplInput).focus()

    def _show_repl_waiting(self) -> None:
        repl_input = self.query_one("#repl-input", ReplInput)
        self._restore_repl_focus = repl_input.has_focus
        repl_input.withdraw_draft()
        repl_input.busy = True
        repl_input.placeholder = ""
        self.query_one("#repl-prompt", Static).display = False

    def _show_repl_ready(self, *, restore_focus: bool = True) -> None:
        repl_input = self.query_one("#repl-input", ReplInput)
        repl_input.busy = False
        repl_input.restore_draft()
        repl_input.placeholder = "expression or :help"
        self.query_one("#repl-prompt", Static).display = True
        if restore_focus and self._restore_repl_focus:
            repl_input.focus()
        self._restore_repl_focus = False

    def _fit_repl_log(self) -> None:
        repl_pane = self.query_one("#repl-pane")
        input_row = self.query_one("#repl-input-row")
        available_height = max(
            0,
            repl_pane.content_region.height - input_row.outer_size.height,
        )
        self.query_one("#repl-log", RichLog).styles.max_height = available_height

    def _sync_if_needed(self) -> None:
        if self._needs_sync:
            self._start_editor_sync()

    def _start_editor_sync(self, *, force: bool = False, reset: bool = False) -> None:
        if self._execution_kind is not None:
            self._show_python_busy_status()
            return
        if not force and not self._needs_sync:
            return

        source = self.query_one("#editor", TextArea).text
        self._execution_kind = "editor"
        self._show_repl_waiting()
        self._show_repl_editor_running_status()
        self._execution_task = asyncio.create_task(
            self._finish_editor_sync(source, reset=reset)
        )

    async def _finish_editor_sync(
        self,
        source: str,
        *,
        reset: bool,
    ) -> None:
        first_output = True

        def write_output(output: str) -> None:
            nonlocal first_output
            self.call_from_thread(
                self._write_editor_output,
                output,
                first_output,
            )
            first_output = False

        try:
            response = (
                await self.kernel.reset(source, on_output=write_output)
                if reset
                else await self.kernel.sync(source, on_output=write_output)
            )
        except asyncio.CancelledError:
            return
        finally:
            self._execution_kind = None
            self._execution_task = None

        if not self.is_mounted:
            return
        self._show_sync_result(response, source)
        if reset and response.state == "ok":
            self.query_one("#repl-log", RichLog).write(
                "REPL-only names were discarded."
            )
        self._show_repl_ready(restore_focus=not response.interrupted)

    def _show_sync_result(self, result: KernelResponse, source: str) -> None:
        log = self.query_one("#repl-log", RichLog)
        self._symbol_count = result.symbol_count
        if result.output:
            log.write(Text("editor output", style="bold #d29922"))
            log.write(result.output.rstrip("\n"))

        if result.interrupted:
            self._set_repl_status(
                "Editor interrupted - sync to retry",
                "#d29922",
            )
            self._show_editor_state_status()
            self.query_one("#editor", TextArea).focus()
            return

        if result.state == "ok":
            self._synced_source = source
            editor_source = self.query_one("#editor", TextArea).text
            self._needs_sync = editor_source != self._synced_source
            if self._needs_sync:
                self._show_editor_pending_status()
            else:
                self._show_editor_synced_status()
            self._show_repl_ready_status()
            self._last_error = ""
        elif result.state == "incomplete":
            self._show_editor_state_status()
            self._set_repl_status(
                "Incomplete Python — last working namespace is still active",
                "#d29922",
            )
        else:
            self._show_editor_state_status()
            self._set_repl_status(
                "Editor error — last working namespace is still active",
                "#f85149",
            )
            if result.error and result.error != self._last_error:
                log.write(Text("editor error", style="bold #f85149"))
                log.write(result.error)
                self._last_error = result.error

    def _show_editor_pending_status(self) -> None:
        self._set_editor_status("Changes pending - sync to load them", "#d29922")

    def _show_editor_synced_status(self) -> None:
        self._set_editor_status("Synced", "#3fb950")

    def _show_editor_no_changes_status(self) -> None:
        self._set_editor_status("No changes to sync", "#3fb950")

    def _show_editor_state_status(self) -> None:
        if self._needs_sync:
            self._show_editor_pending_status()
        else:
            self._show_editor_no_changes_status()

    def _set_editor_status(self, message: str, color: str) -> None:
        status = self.query_one("#editor-status", Static)
        status.update(f"●  {message}")
        status.styles.color = color

    def _set_repl_status(self, message: str, color: str) -> None:
        status = self.query_one("#repl-status", Static)
        status.update(f"{message}  ●")
        status.styles.color = color

    def _show_repl_ready_status(self) -> None:
        self._set_repl_status(
            f"Ready — {self._symbol_count} symbols available", "#3fb950"
        )

    def _show_python_busy_status(self) -> None:
        self._set_repl_status(
            "Python is already running — Ctrl+C to interrupt",
            "#d29922",
        )

    def _show_repl_editor_running_status(self) -> None:
        self._set_repl_status("Running editor… Ctrl+C to interrupt", "#58a6ff")

    def _show_repl_running_status(self) -> None:
        self._set_repl_status("Running REPL… Ctrl+C to interrupt", "#58a6ff")

    def _show_execution_status(self) -> None:
        if self._execution_kind == "editor":
            self._show_repl_editor_running_status()
        elif self._execution_kind == "repl":
            self._show_repl_running_status()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "repl-input":
            return
        if self._execution_kind is not None:
            self._show_python_busy_status()
            return
        command = event.value.strip()
        repl_input = self.query_one("#repl-input", ReplInput)
        repl_input.value = ""
        if not command:
            return
        repl_input.remember(command)
        log = self.query_one("#repl-log", RichLog)
        prompt = Text(">>> ", style="bold #58a6ff")
        prompt.append(PYTHON_HIGHLIGHTER(command))
        log.write(prompt)

        if command.startswith(":"):
            self._handle_command(command)
        else:
            self._start_repl_execution(command)

    def _start_repl_execution(self, command: str) -> None:
        self._execution_kind = "repl"
        self._show_repl_waiting()
        self._show_repl_running_status()
        self._execution_task = asyncio.create_task(self._finish_repl_execution(command))

    async def _finish_repl_execution(self, command: str) -> None:
        def write_output(output: str) -> None:
            self.call_from_thread(self._write_repl_output, output)

        try:
            result = await self.kernel.execute(command, on_output=write_output)
        except asyncio.CancelledError:
            return
        finally:
            self._execution_kind = None
            self._execution_task = None

        if not self.is_mounted:
            return
        self._show_repl_result(result)
        self._show_repl_ready()

    def _write_editor_output(self, output: str, include_header: bool) -> None:
        if include_header:
            self.query_one("#repl-log", RichLog).write(
                Text("editor output", style="bold #d29922")
            )
        self._write_repl_output(output)

    def _write_repl_output(self, output: str) -> None:
        rendered = output.rstrip("\n")
        if rendered:
            self.query_one("#repl-log", RichLog).write(rendered)

    def _show_repl_result(self, result: KernelResponse) -> None:
        log = self.query_one("#repl-log", RichLog)
        self._symbol_count = result.symbol_count
        if result.output:
            log.write(result.output.rstrip("\n"))
        if result.has_display:
            log.write(result.display)
        if result.error:
            log.write(Text(result.error, style="#f85149"))
        self._show_repl_ready_status()

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
        self._show_repl_waiting()
        self._set_repl_status(
            "Inspecting variables… Ctrl+C to interrupt", "#58a6ff"
        )
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
        self._show_repl_ready_status()
        self._show_repl_ready()

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
        if self._execution_kind is None or (
            self._execution_kind == "repl" and self._active_pane == "editor"
        ):
            focused = self.focused
            copy_action = getattr(focused, "action_copy", None)
            if callable(copy_action):
                copy_action()
            return

        execution_kind = self._execution_kind
        if self.kernel.interrupt():
            self._set_repl_status("Interrupting Python…", "#d29922")
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
        self.notify(f"Saved {self.path}")

    def action_clear_repl(self) -> None:
        self.query_one("#repl-log", RichLog).clear()
