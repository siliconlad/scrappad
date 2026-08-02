import asyncio

from textual.widgets import Footer, RichLog, Static, TextArea

from scrappad.app import ReplInput, ScrappadApp


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
            assert app._needs_sync is True

            await pilot.press("ctrl+right")
            await wait_for_idle(app)
            repl_input = app.query_one("#repl-input", ReplInput)
            assert repl_input.has_focus
            assert app._symbol_count == 2
            for character in "greet('Ada')":
                await pilot.press(character)
            await pilot.press("enter")
            await wait_for_idle(app)
            assert repl_input.value == ""

            await pilot.press("up")
            assert repl_input.value == "greet('Ada')"

            await pilot.press("ctrl+left")
            assert editor.has_focus
            await pilot.press("ctrl+s")
            assert path.exists()
            assert "def greet" in path.read_text(encoding="utf-8")

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

            await pilot.resize_terminal(70, 40)
            await pilot.pause()
            assert app.screen.has_class("-narrow")
            assert editor_pane.region.x == repl_pane.region.x
            assert editor_pane.region.y < repl_pane.region.y

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
            initial = await app.kernel.execute("answer")
            assert initial.display == "42"

            await pilot.press("ctrl+left")

            editor.text = "answer = 99\n"
            await pilot.pause()
            unchanged = await app.kernel.execute("answer")
            assert unchanged.display == "42"

            # Waiting does not trigger the old debounced auto-reload behavior.
            await asyncio.sleep(0.7)
            await pilot.pause()
            unchanged = await app.kernel.execute("answer")
            assert unchanged.display == "42"

            await pilot.press("ctrl+right")
            await wait_for_idle(app)
            updated = await app.kernel.execute("answer")
            assert updated.display == "99"

            await pilot.press("ctrl+left")
            editor.text = "answer = !\n"
            await pilot.pause()
            assert app._last_error == ""
            retained = await app.kernel.execute("answer")
            assert retained.display == "99"

            await pilot.click("#repl-input")
            await wait_for_idle(app)
            assert "SyntaxError" in app._last_error
            retained = await app.kernel.execute("answer")
            assert retained.display == "99"

    asyncio.run(exercise_app())


def test_ctrl_c_interrupts_editor_and_allows_unchanged_retry(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "loop.py"
        path.write_text("while True:\n    pass\n", encoding="utf-8")
        app = ScrappadApp(path)

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert editor.has_focus
            assert app._execution_kind is None

            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")
            await pilot.press("ctrl+c")
            await wait_for_idle(app)

            assert editor.has_focus
            assert app._needs_sync is True
            assert "Interrupted" in str(app.query_one("#status", Static).content)

            # Switching back deliberately reruns the unchanged buffer.
            await pilot.press("ctrl+right")
            await wait_for_execution(app, "editor")
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
            repl_input.value = "while True: pass"
            await pilot.press("enter")
            await wait_for_execution(app, "repl")

            await pilot.press("ctrl+c")
            await wait_for_idle(app)
            assert repl_input.has_focus
            assert any(
                "KeyboardInterrupt" in line.text
                for line in app.query_one("#repl-log", RichLog).lines
            )

            repl_input.value = "1 + 1"
            await pilot.press("enter")
            await wait_for_idle(app)
            assert any(
                line.text.strip() == "2"
                for line in app.query_one("#repl-log", RichLog).lines
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
            assert str(app.query_one("#repl-prompt", Static).content) == ">>>"
            assert app.query_one("#repl-input", ReplInput).region.height == 1
            assert app.query_one("#repl-input-row").region.height == 1
            assert (
                repl_input.styles.background
                == app.query_one("#repl-log", RichLog).styles.background
            )
            log = app.query_one("#repl-log", RichLog)
            assert log.lines == []
            assert log.wrap is True
            assert log.styles.scrollbar_size_horizontal == 0
            assert log.styles.scrollbar_size_vertical == 0
            editor = app.query_one("#editor", TextArea)
            assert editor.soft_wrap is True
            assert editor.styles.scrollbar_size_horizontal == 0
            assert editor.styles.scrollbar_size_vertical == 0
            assert list(app.query(Footer)) == []
            assert "0 symbols available" in str(
                app.query_one("#status", Static).content
            )

    asyncio.run(exercise_app())
