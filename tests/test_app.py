import asyncio

from rich.style import Style
from textual.widgets import Footer, RichLog, Static, TextArea

from scrappad.app import EDITOR_SYNTAX_THEME, ReplInput, ScrappadApp


async def wait_for_idle(app: ScrappadApp, timeout: float = 3) -> None:
    async def wait() -> None:
        while app._execution_kind is not None:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


async def wait_for_execution(
    app: ScrappadApp,
    kind: str,
    timeout: float = 3,
) -> None:
    async def wait() -> None:
        while app._execution_kind != kind:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


async def wait_for_log_text(
    app: ScrappadApp,
    text: str,
    timeout: float = 3,
) -> None:
    async def wait() -> None:
        log = app.query_one("#repl-log", RichLog)
        while not any(text in line.text for line in log.lines):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout)


def test_split_panes_repl_history_and_save(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "experiment.py"
        path.write_text(
            "def greet(name):\n    return f'Hello, {name}!'\n\nanswer = 42\n",
            encoding="utf-8",
        )
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert editor.has_focus
            assert editor.language == "python"
            assert editor.theme == EDITOR_SYNTAX_THEME
            assert editor._highlight_query is not None
            highlight_names = {
                name
                for row in editor._highlights.values()
                for _, _, name in row
            }
            expected_highlights = {"keyword.function", "keyword.return", "string"}
            assert expected_highlights <= highlight_names
            assert app._needs_sync is True

            await pilot.press("ctrl+right")
            await wait_for_idle(app)
            repl_input = app.query_one("#repl-input", ReplInput)
            assert repl_input.has_focus
            assert app._symbol_count == 2
            for character in "greet('Ada')":
                await pilot.press(character)
            live_input_colors = {
                str(span.style.color)
                for span in repl_input._value.spans
                if isinstance(span.style, Style) and span.style.color is not None
            }
            assert len(live_input_colors) >= 2
            await pilot.press("enter")
            await wait_for_idle(app)
            assert repl_input.value == ""
            log = app.query_one("#repl-log", RichLog)
            submitted_line = next(
                line for line in log.lines if line.text == ">>> greet('Ada')"
            )
            submitted_colors = {
                str(segment.style.color)
                for segment in submitted_line._segments
                if segment.style is not None and segment.style.color is not None
            }
            assert len(submitted_colors) >= 2

            await pilot.press("up")
            assert repl_input.value == "greet('Ada')"

            await pilot.press("ctrl+left")
            assert editor.has_focus
            await pilot.press("ctrl+s")
            assert path.exists()
            assert "def greet" in path.read_text(encoding="utf-8")

    asyncio.run(exercise_app())


def test_save_status_is_transient_and_tracks_current_editor_state(
    tmp_path,
    monkeypatch,
) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "save-status.py"
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 24)) as pilot:
            monkeypatch.setattr(
                "scrappad.app.EDITOR_STATUS_NOTICE_DURATION",
                0.1,
            )
            editor = app.query_one("#editor", TextArea)
            status = app.query_one("#editor-status", Static)
            editor.text = "answer = 42\n"
            await pilot.pause()

            await pilot.press("ctrl+s")
            assert "Saved" in str(status.content)
            assert path.read_text(encoding="utf-8") == editor.text

            await asyncio.sleep(0.15)
            await pilot.pause()
            assert "Changes pending" in str(status.content)

            await pilot.press("ctrl+s")
            editor.text = "answer = 43\n"
            await pilot.pause()
            assert "Changes pending" in str(status.content)
            await asyncio.sleep(0.15)
            await pilot.pause()
            assert "Changes pending" in str(status.content)

            app.path = tmp_path
            await pilot.press("ctrl+s")
            assert "Could not save" in str(status.content)

    asyncio.run(exercise_app())


def test_layout_responds_to_terminal_width(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "responsive.py")

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            editor_pane = app.query_one("#editor-pane")
            repl_pane = app.query_one("#repl-pane")
            assert app.screen.has_class("-wide")
            assert editor_pane.region.y == repl_pane.region.y
            assert editor_pane.region.x < repl_pane.region.x
            assert (
                app.query_one("#editor-status", Static).region.x
                < app.query_one("#file-path", Static).region.x
                < app.query_one("#repl-status", Static).region.x
            )
            assert (
                app.query_one("#editor-status", Static).region.bottom
                == app.query_one("#file-path", Static).region.bottom
                == app.query_one("#repl-status", Static).region.bottom
                == 40
            )

            await pilot.resize_terminal(70, 40)
            await pilot.pause()
            assert app.screen.has_class("-narrow")
            assert editor_pane.region.x == repl_pane.region.x
            assert editor_pane.region.y < repl_pane.region.y
            assert (
                app.query_one("#editor-status", Static).region.x
                < app.query_one("#file-path", Static).region.x
                < app.query_one("#repl-status", Static).region.x
            )
            assert (
                app.query_one("#file-path", Static).region.bottom == 40
            )
            assert app.query_one("#repl-status", Static).region.bottom == 40

    asyncio.run(exercise_app())


def test_editor_changes_load_only_when_entering_repl(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "manual-sync.py"
        path.write_text("answer = 42\n", encoding="utf-8")
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            await pilot.press("ctrl+right")
            await wait_for_idle(app)
            initial = await app.kernel.execute("answer", on_output=lambda _: None)
            assert initial.display == "42"

            await pilot.press("ctrl+left")

            editor.text = "answer = 99\n"
            await pilot.pause()
            assert "Changes pending" in str(
                app.query_one("#editor-status", Static).content
            )

            editor.text = "answer = 42\n"
            await pilot.pause()
            assert app._needs_sync is False
            assert "No changes to sync" in str(
                app.query_one("#editor-status", Static).content
            )

            editor.text = "answer = 99\n"
            await pilot.pause()
            unchanged = await app.kernel.execute("answer", on_output=lambda _: None)
            assert unchanged.display == "42"

            # Waiting does not trigger the old debounced auto-reload behavior.
            await asyncio.sleep(0.7)
            await pilot.pause()
            unchanged = await app.kernel.execute("answer", on_output=lambda _: None)
            assert unchanged.display == "42"

            await pilot.press("ctrl+right")
            await wait_for_idle(app)
            updated = await app.kernel.execute("answer", on_output=lambda _: None)
            assert updated.display == "99"

            await pilot.press("ctrl+left")
            editor.text = "answer = !\n"
            await pilot.pause()
            assert app._last_error == ""
            retained = await app.kernel.execute("answer", on_output=lambda _: None)
            assert retained.display == "99"

            await pilot.click("#repl-input")
            await wait_for_idle(app)
            assert "SyntaxError" in app._last_error
            retained = await app.kernel.execute("answer", on_output=lambda _: None)
            assert retained.display == "99"

    asyncio.run(exercise_app())


def test_repl_draft_is_withdrawn_during_editor_sync_and_restored(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "draft-during-sync.py")

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.press("ctrl+right")
            repl_input = app.query_one("#repl-input", ReplInput)
            prompt = app.query_one("#repl-prompt", Static)
            repl_input.value = "pending_call(1)"
            assert repl_input.selection.is_empty

            await pilot.press("ctrl+left")
            app.query_one("#editor", TextArea).text = "while True: pass\n"
            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")

            assert prompt.display is False
            assert repl_input.value == ""

            await pilot.press("ctrl+c")
            await wait_for_idle(app)

            assert prompt.display is True
            assert repl_input.value == "pending_call(1)"
            assert repl_input.selection.is_empty

            app.query_one("#editor", TextArea).text = (
                "import time\ntime.sleep(0.1)\nanswer = 42\n"
            )
            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")
            assert repl_input.value == ""
            await wait_for_idle(app)
            assert prompt.display is True
            assert repl_input.value == "pending_call(1)"
            assert repl_input.selection.is_empty

    asyncio.run(exercise_app())


def test_ctrl_c_interrupts_editor_and_allows_unchanged_retry(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "loop.py"
        path.write_text("while True:\n    print('editor')\n", encoding="utf-8")
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert editor.has_focus
            assert app._execution_kind is None

            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")
            await wait_for_log_text(app, "editor")
            log = app.query_one("#repl-log", RichLog)
            assert any(line.text == "editor output" for line in log.lines)
            assert not any("<output truncated>" in line.text for line in log.lines)
            log.focus()
            await pilot.pause()
            assert log.has_focus
            assert app._active_pane == "repl"
            await pilot.press("ctrl+c")
            await wait_for_idle(app)

            assert editor.has_focus
            assert app._needs_sync is True
            assert "Editor interrupted - sync to retry" in str(
                app.query_one("#repl-status", Static).content
            )

            # Re-entering the REPL retries the unchanged editor source and
            # remains interruptible from the REPL input.
            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")
            assert app.query_one("#repl-input", ReplInput).has_focus
            await pilot.press("ctrl+c")
            await wait_for_idle(app)
            assert editor.has_focus

    asyncio.run(exercise_app())


def test_ctrl_c_interrupts_repl_without_losing_worker(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "repl-loop.py")

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+right")
            repl_input = app.query_one("#repl-input", ReplInput)
            input_row = app.query_one("#repl-input-row")
            prompt = app.query_one("#repl-prompt", Static)
            log = app.query_one("#repl-log", RichLog)
            repl_pane = app.query_one("#repl-pane")
            repl_input.value = "while True: print('hi')"
            await pilot.press("enter")
            await wait_for_execution(app, "repl")
            assert input_row.display is True
            assert prompt.display is False
            assert repl_input.has_focus
            assert input_row.region.y == log.region.bottom

            await pilot.press("x")
            assert repl_input.value == ""

            await wait_for_log_text(app, "hi")
            assert not any(
                "<output truncated>" in line.text for line in log.lines
            )

            # Switching away and back without editing does not imply that a
            # sync was requested or blocked.
            await pilot.press("ctrl+left")
            await pilot.press("ctrl+right")
            status = str(app.query_one("#repl-status", Static).content)
            assert "Running REPL" in status

            await pilot.press("ctrl+left")
            assert "Running REPL" in str(
                app.query_one("#repl-status", Static).content
            )
            await pilot.press("ctrl+c")
            await pilot.pause()
            assert app._execution_kind == "repl"

            app.query_one("#editor", TextArea).text = "answer = 42\n"
            await pilot.pause()
            assert "Changes pending" in str(
                app.query_one("#editor-status", Static).content
            )
            assert "Running REPL" in str(
                app.query_one("#repl-status", Static).content
            )

            await pilot.press("ctrl+right")
            assert "Running REPL" in str(
                app.query_one("#repl-status", Static).content
            )

            await pilot.press("ctrl+left")
            assert "Running REPL" in str(
                app.query_one("#repl-status", Static).content
            )

            await pilot.press("ctrl+right")

            await pilot.press("ctrl+c")
            await wait_for_idle(app)
            editor_status = str(
                app.query_one("#editor-status", Static).content
            )
            assert "Changes pending - sync to load them" in editor_status
            assert "switch to the REPL" not in editor_status
            assert "Ready" in str(
                app.query_one("#repl-status", Static).content
            )
            assert input_row.display is True
            assert prompt.display is True
            assert str(prompt.content) == ">>>"
            assert repl_input.has_focus
            assert input_row.region.bottom <= repl_pane.region.bottom - 1
            widget_at_prompt, _ = app.get_widget_at(
                prompt.region.x,
                prompt.region.y,
            )
            assert widget_at_prompt is prompt
            assert log.lines[-1].text.strip() == "KeyboardInterrupt"
            assert not any(
                "<output truncated>" in line.text for line in log.lines
            )

            repl_input.value = "1 + 1"
            await pilot.press("enter")
            await wait_for_idle(app)
            assert input_row.display is True
            result_line = next(
                line for line in log.lines if line.text.strip() == "2"
            )
            assert all(
                segment.style is None
                or segment.style.bgcolor is None
                or segment.style.bgcolor.is_default
                for segment in result_line._segments
            )
            assert all(
                segment.style is None or segment.style.color is None
                for segment in result_line._segments
            )

    asyncio.run(exercise_app())


def test_new_scratchpad_is_empty_and_repl_starts_clean(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "new.py")

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            assert app.query_one("#editor", TextArea).text == ""
            repl_input = app.query_one("#repl-input", ReplInput)
            assert repl_input.placeholder == "expression or :help"
            assert repl_input.select_on_focus is False
            assert str(app.query_one("#repl-prompt", Static).content) == ">>>"
            assert app.query_one("#repl-input", ReplInput).region.height == 1
            assert app.query_one("#repl-input-row").region.height == 1
            assert (
                repl_input.styles.background
                == app.query_one("#repl-log", RichLog).styles.background
            )
            log = app.query_one("#repl-log", RichLog)
            assert log.lines == []
            assert log.highlight is False
            assert log.wrap is True
            assert log.styles.scrollbar_size_horizontal == 0
            assert log.styles.scrollbar_size_vertical == 0
            editor = app.query_one("#editor", TextArea)
            assert editor.soft_wrap is True
            assert editor.highlight_cursor_line is False
            assert editor.styles.background == log.styles.background
            assert editor.styles.scrollbar_size_horizontal == 0
            assert editor.styles.scrollbar_size_vertical == 0
            assert list(app.query(Footer)) == []
            editor_status = str(
                app.query_one("#editor-status", Static).content
            )
            assert "No changes to sync" in editor_status
            assert editor_status.startswith("●")
            repl_status = str(app.query_one("#repl-status", Static).content)
            assert "Ready — 0 symbols available" in repl_status
            assert repl_status.endswith("●")
            assert not repl_status.startswith("●")
            assert str(app.query_one("#file-path", Static).content) == str(
                (tmp_path / "new.py").resolve()
            )
            assert (
                app.query_one("#editor-status", Static).region.x
                < app.query_one("#file-path", Static).region.x
                < app.query_one("#repl-status", Static).region.x
            )

    asyncio.run(exercise_app())


def test_repl_and_editor_use_identical_tree_sitter_colors(tmp_path) -> None:
    async def exercise_app() -> None:
        source = "while True: pass"
        app = ScrappadApp(tmp_path / "matching-highlights.py")

        async with app.run_test(size=(120, 24)) as pilot:
            editor = app.query_one("#editor", TextArea)
            repl_input = app.query_one("#repl-input", ReplInput)
            editor.text = source
            repl_input.value = source
            await pilot.pause()

            editor_colors: list[str | None] = []
            repl_colors: list[str | None] = []
            for offset in (0, 6, 12):
                editor_color = None
                for start, end, name in editor._highlights[0]:
                    if start <= offset < end:
                        style = editor._theme.syntax_styles.get(name)
                        if style is not None and style.color is not None:
                            editor_color = str(style.color)
                editor_colors.append(editor_color)

                repl_color = None
                for span in repl_input._value.spans:
                    if span.start <= offset < span.end:
                        style = span.style
                        if isinstance(style, Style) and style.color is not None:
                            repl_color = str(style.color)
                repl_colors.append(repl_color)

            assert repl_colors == editor_colors
            assert editor_colors[0] == editor_colors[2]
            assert editor_colors[0] != editor_colors[1]
            assert editor._theme.syntax_styles["boolean"].italic is False
            true_style = next(
                span.style
                for span in repl_input._value.spans
                if span.start <= 6 < span.end and isinstance(span.style, Style)
            )
            assert true_style.italic is False

    asyncio.run(exercise_app())


def test_repl_input_follows_transcript_content(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "flowing-repl.py")

        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            log = app.query_one("#repl-log", RichLog)
            input_row = app.query_one("#repl-input-row")
            status = app.query_one("#repl-status", Static)

            assert log.region.height == 0
            assert input_row.region.y == log.region.y
            assert status.region.bottom == app.screen.region.bottom

            log.write("first line")
            await pilot.pause()
            assert log.region.height == 1
            assert input_row.region.y == log.region.bottom
            assert status.region.bottom == app.screen.region.bottom

            log.focus()
            await pilot.pause()
            assert log.has_focus
            assert log.styles.background_tint.a == 0

            app.query_one("#repl-input", ReplInput).focus()
            await pilot.pause()
            assert app.query_one("#repl-input", ReplInput).styles.background_tint.a == 0

            for index in range(30):
                log.write(f"line {index}")
            await pilot.pause()
            assert log.virtual_size.height > log.region.height
            assert input_row.region.y == log.region.bottom
            assert status.region.bottom == app.screen.region.bottom

            log.clear()
            await pilot.pause()
            assert log.region.height == 0
            assert input_row.region.y == log.region.y
            assert status.region.bottom == app.screen.region.bottom

    asyncio.run(exercise_app())


def test_clicking_empty_repl_space_focuses_input(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "clickable-repl.py")

        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            repl_input = app.query_one("#repl-input", ReplInput)
            repl_pane = app.query_one("#repl-pane")
            assert not repl_input.has_focus
            assert repl_input.region.bottom < repl_pane.content_region.bottom

            await pilot.click("#repl-pane", offset=(10, 10))
            await pilot.pause()

            assert repl_input.has_focus

    asyncio.run(exercise_app())


def test_clicking_repl_during_editor_execution_restores_focus(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "editor-loop.py"
        path.write_text("while True:\n    pass\n", encoding="utf-8")
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            repl_input = app.query_one("#repl-input", ReplInput)

            await pilot.click("#repl-pane", offset=(10, 10))
            await wait_for_execution(app, "editor")
            assert repl_input.has_focus
            assert "Running editor" in str(
                app.query_one("#repl-status", Static).content
            )

            await pilot.click("#editor", offset=(5, 5))
            await pilot.pause()
            assert editor.has_focus
            assert "Running editor" in str(
                app.query_one("#repl-status", Static).content
            )

            editor.text = "while True:\n    pass\n# changed\n"
            await pilot.pause()
            assert "Changes pending" in str(
                app.query_one("#editor-status", Static).content
            )
            assert "Running editor" in str(
                app.query_one("#repl-status", Static).content
            )

            editor.text = "while True:\n    pass\n"
            await pilot.pause()
            assert "Changes pending" in str(
                app.query_one("#editor-status", Static).content
            )
            assert "Running editor" in str(
                app.query_one("#repl-status", Static).content
            )

            await pilot.click("#repl-pane", offset=(10, 10))
            await pilot.pause()
            assert repl_input.has_focus
            assert app._active_pane == "repl"
            status = str(app.query_one("#repl-status", Static).content)
            assert "Running editor" in status

            await pilot.press("ctrl+c")
            await wait_for_idle(app)

    asyncio.run(exercise_app())


def test_quit_stops_running_repl_and_worker(tmp_path) -> None:
    async def exercise_app() -> None:
        app = ScrappadApp(tmp_path / "quit-loop.py")
        worker = app.kernel._process

        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+right")
            repl_input = app.query_one("#repl-input", ReplInput)
            repl_input.value = "while True: print('hi')"
            await pilot.press("enter")
            await wait_for_execution(app, "repl")
            await wait_for_log_text(app, "hi")

            await pilot.press("ctrl+q")

        assert not worker.is_alive()
        assert app.kernel._closed is True
        assert app._execution_kind is None
        assert app._execution_task is None

    asyncio.run(exercise_app())
