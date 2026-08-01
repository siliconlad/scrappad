import asyncio

from textual.widgets import TextArea

from pyground.app import PygroundApp, ReplInput


def test_split_panes_repl_history_and_save(tmp_path) -> None:
    async def exercise_app() -> None:
        path = tmp_path / "experiment.py"
        app = PygroundApp(path)

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert editor.has_focus
            assert app.runtime.namespace["answer"] == 42

            await pilot.press("ctrl+right")
            repl_input = app.query_one("#repl-input", ReplInput)
            assert repl_input.has_focus
            for character in "greet('Ada')":
                await pilot.press(character)
            await pilot.press("enter")
            await pilot.pause()
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
        app = PygroundApp(tmp_path / "responsive.py")

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
        app = PygroundApp(tmp_path / "manual-sync.py")

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert app.runtime.namespace["answer"] == 42

            editor.text = "answer = 99\n"
            await pilot.pause()
            assert app.runtime.namespace["answer"] == 42

            # Waiting does not trigger the old debounced auto-reload behavior.
            await asyncio.sleep(0.7)
            await pilot.pause()
            assert app.runtime.namespace["answer"] == 42

            await pilot.press("ctrl+right")
            await pilot.pause()
            assert app.runtime.namespace["answer"] == 99

            await pilot.press("ctrl+left")
            editor.text = "answer = !\n"
            await pilot.pause()
            assert app._last_error == ""
            assert app.runtime.namespace["answer"] == 99

            await pilot.click("#repl-input")
            await pilot.pause()
            assert "SyntaxError" in app._last_error
            assert app.runtime.namespace["answer"] == 99

    asyncio.run(exercise_app())
