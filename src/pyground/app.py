"""Textual user interface for Pyground."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, Label, RichLog, Static, TextArea

from .runtime import PythonRuntime, ReplResult, SyncResult, display_value


STARTER = '''\
"""Edit this code, then switch to the REPL to load your changes."""


def greet(name: str) -> str:
    return f"Hello, {name}!"


answer = 42
'''


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


class PygroundApp(App[None]):
    """Split-screen Python editor with a synchronized REPL."""

    TITLE = "Pyground"
    SUB_TITLE = "live Python scratchpad"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-wide")]

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
    }

    #repl-log {
        height: 1fr;
        padding: 0 1;
        background: #0d1117;
        scrollbar-color: #30363d;
        scrollbar-color-hover: #58a6ff;
    }

    #repl-input {
        height: 3;
        margin: 0 1 1 1;
        border: tall #30363d;
        background: #161b22;
    }

    #repl-input:focus {
        border: tall #58a6ff;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: #161b22;
        color: #8b949e;
    }

    Footer {
        background: #010409;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("f2", "switch_pane", "Switch pane", priority=True),
        Binding("ctrl+left,ctrl+up", "focus_editor", "Editor", priority=True),
        Binding("ctrl+right,ctrl+down", "focus_repl", "REPL", priority=True),
        Binding("f5", "sync", "Run editor", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+l", "clear_repl", "Clear REPL", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.runtime = PythonRuntime(path)
        self.source = path.read_text(encoding="utf-8") if path.exists() else STARTER
        self._last_error = ""
        self._dirty = False
        self._needs_sync = True
        self._edit_revision = 0
        self._last_attempted_revision = -1

    def compose(self) -> ComposeResult:
        with Horizontal(id="workspace"):
            with Vertical(classes="pane", id="editor-pane"):
                yield Label(f"EDITOR  {self.path}", classes="pane-title", id="editor-title")
                yield TextArea(
                    self.source,
                    language="python",
                    show_line_numbers=True,
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
                yield ReplInput(
                    id="repl-input",
                    placeholder=">>> Try: greet('Ada')   (:help for commands)",
                )
        yield Static("Starting…", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#editor", TextArea).focus()
        log = self.query_one("#repl-log", RichLog)
        log.write(Text("Pyground REPL", style="bold #58a6ff"))
        log.write("Switch to the REPL to load editor changes. Type :help for commands.")
        self._perform_sync(announce=True)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "editor":
            return
        self._dirty = True
        self._needs_sync = True
        self._edit_revision += 1
        self._update_editor_title()
        status = self.query_one("#status", Static)
        status.update("● Changes pending — switch to the REPL to load them")
        status.styles.color = "#d29922"

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        if event.widget.id in {"repl-input", "repl-log"}:
            self._sync_if_needed()

    def _sync_if_needed(self) -> None:
        if (
            self._needs_sync
            and self._last_attempted_revision != self._edit_revision
        ):
            self._perform_sync()

    def _perform_sync(self, announce: bool = False) -> None:
        self._last_attempted_revision = self._edit_revision
        source = self.query_one("#editor", TextArea).text
        result = self.runtime.sync(source)
        self._show_sync_result(result, announce)

    def _show_sync_result(self, result: SyncResult, announce: bool = False) -> None:
        status = self.query_one("#status", Static)
        log = self.query_one("#repl-log", RichLog)
        if result.output:
            log.write(Text("editor output", style="bold #d29922"))
            log.write(result.output.rstrip("\n"))

        if result.state == "ok":
            self._needs_sync = False
            count = len(self.runtime.visible_names)
            status.update(f"● Synced  {count} names available  |  {self.path.name}")
            status.styles.color = "#3fb950"
            self._last_error = ""
            if announce:
                log.write(Text(f"Loaded {count} names from the editor.", style="#3fb950"))
        elif result.state == "incomplete":
            status.update("● Incomplete Python — last working namespace is still active")
            status.styles.color = "#d29922"
        else:
            status.update("● Editor error — last working namespace is still active")
            status.styles.color = "#f85149"
            if result.error and result.error != self._last_error:
                log.write(Text("editor error", style="bold #f85149"))
                log.write(result.error)
                self._last_error = result.error

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "repl-input":
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
            self._show_repl_result(self.runtime.execute(command))

    def _show_repl_result(self, result: ReplResult) -> None:
        log = self.query_one("#repl-log", RichLog)
        if result.output:
            log.write(result.output.rstrip("\n"))
        if result.has_value:
            rendered = display_value(result.value)
            log.write(Syntax(rendered, "python", word_wrap=True))
        if result.error:
            log.write(Text(result.error, style="#f85149"))

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
            table = Table("name", "type", "value", box=None, header_style="bold #58a6ff")
            for item_name, value in sorted(self.runtime.visible_names.items()):
                table.add_row(
                    Text(item_name),
                    Text(type(value).__name__),
                    Text(display_value(value, 120)),
                )
            if table.row_count:
                log.write(table)
            else:
                log.write("No names are currently defined.")
        elif name == ":sync":
            self._perform_sync(announce=True)
        elif name == ":reset":
            result = self.runtime.reset(self.query_one("#editor", TextArea).text)
            self._show_sync_result(result, announce=True)
            if result.state == "ok":
                log.write("REPL-only names were discarded.")
        elif name == ":clear":
            log.clear()
        else:
            log.write(Text(f"Unknown command: {name}. Try :help", style="#f85149"))

    def action_switch_pane(self) -> None:
        editor = self.query_one("#editor", TextArea)
        repl_input = self.query_one("#repl-input", ReplInput)
        if editor.has_focus:
            self._sync_if_needed()
            repl_input.focus()
        else:
            editor.focus()

    def action_focus_editor(self) -> None:
        self.query_one("#editor", TextArea).focus()

    def action_focus_repl(self) -> None:
        self._sync_if_needed()
        self.query_one("#repl-input", ReplInput).focus()

    def action_sync(self) -> None:
        self._perform_sync(announce=True)

    def action_save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(self.query_one("#editor", TextArea).text, encoding="utf-8")
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
