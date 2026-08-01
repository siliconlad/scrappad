from pyground.runtime import PythonRuntime, display_value


def test_sync_loads_editor_names() -> None:
    runtime = PythonRuntime("test.py")

    result = runtime.sync("x = 5\n\ndef double(n):\n    return n * 2\n")

    assert result.state == "ok"
    assert runtime.namespace["x"] == 5
    assert runtime.namespace["double"](6) == 12


def test_failed_sync_keeps_last_working_namespace() -> None:
    runtime = PythonRuntime()
    runtime.sync("x = 5")

    result = runtime.sync("x = 9\nraise RuntimeError('nope')")

    assert result.state == "error"
    assert "RuntimeError: nope" in result.error
    assert runtime.namespace["x"] == 5


def test_incomplete_sync_keeps_namespace() -> None:
    runtime = PythonRuntime()
    runtime.sync("x = 5")

    result = runtime.sync("def unfinished():")

    assert result.state == "incomplete"
    assert runtime.namespace["x"] == 5


def test_repl_evaluates_final_expression_and_captures_output() -> None:
    runtime = PythonRuntime()

    result = runtime.execute("print('hello'); 6 * 7")

    assert result.output == "hello\n"
    assert result.has_value is True
    assert result.value == 42


def test_repl_scratch_names_survive_editor_refresh() -> None:
    runtime = PythonRuntime()
    runtime.sync("editor_name = 1")
    runtime.execute("scratch_name = 9")

    runtime.sync("editor_name = 2\nnew_name = 3")

    assert runtime.namespace["scratch_name"] == 9
    assert runtime.namespace["editor_name"] == 2
    assert runtime.namespace["new_name"] == 3


def test_removed_editor_names_do_not_linger() -> None:
    runtime = PythonRuntime()
    runtime.sync("old_name = 1\nkept_name = 2")

    runtime.sync("kept_name = 3")

    assert "old_name" not in runtime.namespace
    assert runtime.namespace["kept_name"] == 3


def test_editor_wins_when_repl_overrides_an_editor_name() -> None:
    runtime = PythonRuntime()
    runtime.sync("value = 1")
    runtime.execute("value = 999")

    runtime.sync("value = 2")

    assert runtime.namespace["value"] == 2


def test_reset_discards_repl_only_names() -> None:
    runtime = PythonRuntime()
    runtime.sync("editor_name = 1")
    runtime.execute("scratch_name = 9")

    result = runtime.reset()

    assert result.state == "ok"
    assert runtime.namespace["editor_name"] == 1
    assert "scratch_name" not in runtime.namespace


def test_failed_reset_is_transactional() -> None:
    runtime = PythonRuntime()
    runtime.sync("editor_name = 1")
    runtime.execute("scratch_name = 9")

    result = runtime.reset("raise RuntimeError('not reset')")

    assert result.state == "error"
    assert runtime.namespace["editor_name"] == 1
    assert runtime.namespace["scratch_name"] == 9


def test_comprehension_targets_are_not_mistaken_for_module_names() -> None:
    runtime = PythonRuntime()
    runtime.execute("item = 'from repl'")

    runtime.sync("squares = [item * item for item in range(3)]")
    runtime.sync("squares = [number * number for number in range(2)]")

    assert runtime.namespace["item"] == "from repl"


def test_sync_captures_stdout() -> None:
    runtime = PythonRuntime()

    result = runtime.sync("print('loaded')")

    assert result.state == "ok"
    assert result.output == "loaded\n"


def test_display_value_handles_broken_repr() -> None:
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("broken")

    assert display_value(Broken()).startswith("<repr failed: RuntimeError")
