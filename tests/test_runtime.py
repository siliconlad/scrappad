import io

from scrappad.runtime import PythonRuntime, display_value


def test_sync_loads_editor_names() -> None:
    runtime = PythonRuntime("test.py")

    result = runtime.sync(
        "x = 5\n\ndef double(n):\n    return n * 2\n",
        output_stream=io.StringIO(),
    )

    assert result.state == "ok"
    assert runtime.namespace["x"] == 5
    assert runtime.namespace["double"](6) == 12


def test_failed_sync_keeps_last_working_namespace() -> None:
    runtime = PythonRuntime()
    runtime.sync("x = 5", output_stream=io.StringIO())

    result = runtime.sync(
        "x = 9\nraise RuntimeError('nope')",
        output_stream=io.StringIO(),
    )

    assert result.state == "error"
    assert "RuntimeError: nope" in result.error
    assert runtime.namespace["x"] == 5


def test_partial_source_is_error_and_keeps_namespace() -> None:
    runtime = PythonRuntime()
    runtime.sync("x = 5", output_stream=io.StringIO())

    result = runtime.sync("def unfinished():", output_stream=io.StringIO())

    assert result.state == "error"
    assert "IndentationError" in result.error
    assert runtime.namespace["x"] == 5


def test_repl_evaluates_final_expression_and_streams_output() -> None:
    runtime = PythonRuntime()
    output = io.StringIO()

    result = runtime.execute("print('hello'); 6 * 7", output_stream=output)

    assert output.getvalue() == "hello\n"
    assert result.has_value is True
    assert result.value == 42


def test_repl_scratch_names_survive_editor_refresh() -> None:
    runtime = PythonRuntime()
    runtime.sync("editor_name = 1", output_stream=io.StringIO())
    runtime.execute("scratch_name = 9", output_stream=io.StringIO())

    runtime.sync(
        "editor_name = 2\nnew_name = 3",
        output_stream=io.StringIO(),
    )

    assert runtime.namespace["scratch_name"] == 9
    assert runtime.namespace["editor_name"] == 2
    assert runtime.namespace["new_name"] == 3


def test_removed_editor_names_do_not_linger() -> None:
    runtime = PythonRuntime()
    runtime.sync("old_name = 1\nkept_name = 2", output_stream=io.StringIO())

    runtime.sync("kept_name = 3", output_stream=io.StringIO())

    assert "old_name" not in runtime.namespace
    assert runtime.namespace["kept_name"] == 3


def test_editor_wins_when_repl_overrides_an_editor_name() -> None:
    runtime = PythonRuntime()
    runtime.sync("value = 1", output_stream=io.StringIO())
    runtime.execute("value = 999", output_stream=io.StringIO())

    runtime.sync("value = 2", output_stream=io.StringIO())

    assert runtime.namespace["value"] == 2


def test_editor_claims_repl_name_when_value_identity_is_unchanged() -> None:
    runtime = PythonRuntime()
    runtime.execute("value = 1", output_stream=io.StringIO())

    runtime.sync("value = 1", output_stream=io.StringIO())
    runtime.sync("", output_stream=io.StringIO())

    assert "value" not in runtime.namespace


def test_reset_discards_repl_only_names() -> None:
    runtime = PythonRuntime()
    source = "editor_name = 1"
    runtime.sync(source, output_stream=io.StringIO())
    runtime.execute("scratch_name = 9", output_stream=io.StringIO())

    result = runtime.reset(source, output_stream=io.StringIO())

    assert result.state == "ok"
    assert runtime.namespace["editor_name"] == 1
    assert "scratch_name" not in runtime.namespace


def test_failed_reset_is_transactional() -> None:
    runtime = PythonRuntime()
    runtime.sync("editor_name = 1", output_stream=io.StringIO())
    runtime.execute("scratch_name = 9", output_stream=io.StringIO())

    result = runtime.reset(
        "raise RuntimeError('not reset')",
        output_stream=io.StringIO(),
    )

    assert result.state == "error"
    assert runtime.namespace["editor_name"] == 1
    assert runtime.namespace["scratch_name"] == 9


def test_comprehension_targets_are_not_mistaken_for_module_names() -> None:
    runtime = PythonRuntime()
    runtime.execute("item = 'from repl'", output_stream=io.StringIO())

    runtime.sync(
        "squares = [item * item for item in range(3)]",
        output_stream=io.StringIO(),
    )
    runtime.sync(
        "squares = [number * number for number in range(2)]",
        output_stream=io.StringIO(),
    )

    assert runtime.namespace["item"] == "from repl"


def test_match_pattern_bindings_are_owned_by_the_editor() -> None:
    runtime = PythonRuntime()
    runtime.execute(
        "captured = starred = rest = 'from repl'",
        output_stream=io.StringIO(),
    )

    runtime.sync(
        """
match None:
    case 0 as captured:
        pass
match None:
    case [*starred]:
        pass
match None:
    case {**rest}:
        pass
""",
        output_stream=io.StringIO(),
    )
    runtime.sync("", output_stream=io.StringIO())

    assert "captured" not in runtime.namespace
    assert "starred" not in runtime.namespace
    assert "rest" not in runtime.namespace


def test_sync_streams_stdout() -> None:
    runtime = PythonRuntime()
    output = io.StringIO()

    result = runtime.sync("print('loaded')", output_stream=output)

    assert result.state == "ok"
    assert output.getvalue() == "loaded\n"


def test_display_value_handles_broken_repr() -> None:
    class Broken:
        def __repr__(self) -> str:
            raise RuntimeError("broken")

    assert display_value(Broken()).startswith("<repr failed: RuntimeError")
