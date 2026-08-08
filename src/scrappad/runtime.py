"""Execution engine shared by the editor and REPL.

The UI deliberately knows very little about Python execution. Keeping this
logic here also makes the important namespace behavior straightforward to
test without starting a terminal application.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import CodeType
from typing import Any, Literal

SyncState = Literal["ok", "error"]


@dataclass(frozen=True)
class SyncResult:
    state: SyncState
    error: str = ""
    interrupted: bool = False


@dataclass(frozen=True)
class ReplResult:
    value: Any = None
    has_value: bool = False
    error: str = ""
    interrupted: bool = False


def _format_exception() -> str:
    """Return a useful exception without exposing runtime implementation frames."""

    lines = traceback.format_exc().splitlines()
    return "\n".join(lines[-8:])


def display_value(value: Any, limit: int = 12_000) -> str:
    """Safely produce a bounded representation for a REPL result."""

    try:
        rendered = repr(value)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 - repr is arbitrary user code
        rendered = f"<repr failed: {type(exc).__name__}: {exc}>"
    if len(rendered) > limit:
        return rendered[:limit] + f"\n... <{len(rendered) - limit} characters omitted>"
    return rendered


class PythonRuntime:
    """Own a live namespace synchronized from editor source.

    An editor refresh is transactional: code executes in a candidate mapping,
    which replaces the live namespace only on success. Names created solely in
    the REPL survive a refresh, while names owned by the editor are replaced or
    removed as the source changes.
    """

    def __init__(self, filename: str | Path = "scratch.py") -> None:
        self.filename = str(filename)
        self.namespace: dict[str, Any] = self._base_namespace()
        self._editor_names: set[str] = set()

    def _base_namespace(self) -> dict[str, Any]:
        return {
            "__name__": "__scrappad__",
            "__file__": self.filename,
            "__package__": None,
            "__builtins__": builtins.__dict__,
        }

    @property
    def visible_names(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in self.namespace.items()
            if not name.startswith("__")
        }

    def _compile_editor(self, source: str) -> tuple[CodeType | None, SyncResult | None]:
        try:
            code = compile(source, self.filename, "exec")
        except (SyntaxError, OverflowError, ValueError):
            return None, SyncResult("error", error=_format_exception())
        return code, None

    def sync(
        self,
        source: str,
        *,
        output_stream: io.TextIOBase,
    ) -> SyncResult:
        """Execute editor source and atomically publish it on success."""

        code, early_result = self._compile_editor(source)
        if early_result is not None:
            return early_result
        assert code is not None

        # Keep scratch names from the REPL, but rebuild every editor-owned name.
        candidate = self._base_namespace()
        candidate.update(
            (name, value)
            for name, value in self.namespace.items()
            if name not in self._editor_names and not name.startswith("__")
        )
        before = dict(candidate)

        try:
            with (
                contextlib.redirect_stdout(output_stream),
                contextlib.redirect_stderr(output_stream),
            ):
                exec(code, candidate, candidate)  # noqa: S102 - this is a Python REPL
        except KeyboardInterrupt:
            return SyncResult(
                "error",
                error="KeyboardInterrupt",
                interrupted=True,
            )
        except BaseException:  # noqa: BLE001 - report user exceptions in the REPL
            return SyncResult(
                "error",
                error=_format_exception(),
            )

        statically_bound = _top_level_bound_names(source)
        changed_or_new = {
            name
            for name, value in candidate.items()
            if not name.startswith("__")
            and (name not in before or value is not before[name])
        }
        self._editor_names = statically_bound | changed_or_new
        self.namespace = candidate
        return SyncResult("ok")

    def reset(
        self,
        source: str,
        *,
        output_stream: io.TextIOBase,
    ) -> SyncResult:
        """Discard REPL scratch names and rebuild from the editor."""

        previous_namespace = self.namespace
        previous_editor_names = self._editor_names
        self.namespace = self._base_namespace()
        self._editor_names.clear()
        result = self.sync(source, output_stream=output_stream)
        if result.state != "ok":
            self.namespace = previous_namespace
            self._editor_names = previous_editor_names
        return result

    def execute(
        self,
        command: str,
        *,
        output_stream: io.TextIOBase,
    ) -> ReplResult:
        """Execute one REPL command, displaying the final expression if present."""

        try:
            module = ast.parse(command, self.filename, mode="exec")
            expression: ast.expr | None = None
            # exec() runs statements but cannot return the value of a trailing
            # expression. Split that expression out and eval() it after the
            # preceding statements so commands behave like an interactive REPL.
            if module.body and isinstance(module.body[-1], ast.Expr):
                expression = module.body.pop().value

            value: Any = None
            has_value = False
            with (
                contextlib.redirect_stdout(output_stream),
                contextlib.redirect_stderr(output_stream),
            ):
                if module.body:
                    exec(  # noqa: S102 - this is a Python REPL
                        compile(module, self.filename, "exec"),
                        self.namespace,
                        self.namespace,
                    )
                if expression is not None:
                    value = eval(
                        compile(ast.Expression(expression), self.filename, "eval"),
                        self.namespace,
                        self.namespace,
                    )
                    has_value = value is not None
            return ReplResult(
                value=value,
                has_value=has_value,
            )
        except KeyboardInterrupt:
            return ReplResult(
                error="KeyboardInterrupt",
                interrupted=True,
            )
        except BaseException:  # noqa: BLE001 - report user exceptions in the REPL
            return ReplResult(
                error=_format_exception(),
            )


def _top_level_bound_names(source: str) -> set[str]:
    """Find names the module intends to own, including inside control flow."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    collector = _ModuleBindingCollector()
    collector.visit(tree)
    return collector.names


class _ModuleBindingCollector(ast.NodeVisitor):
    """Collect names that editor source intends to own at module scope.

    Comparing the namespace before and after execution is not sufficient: an
    assignment can rebind a REPL name to the same object, and a binding inside
    untaken control flow makes no runtime change. A normal AST walk is too broad
    because function locals and comprehension targets are not module bindings.
    The stdlib symtable module also exposes inlined comprehension targets as
    module symbols on Python 3.12+, even though those targets do not leak.
    This scope-aware walk supplies the static half of editor-name tracking;
    namespace comparison still catches dynamic bindings made by exec or import *.
    """

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for decorator in node.decorator_list:
            self.visit(decorator)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def _visit_comprehension(self, node: ast.AST) -> None:
        """Visit expressions in a comprehension without claiming local targets."""

        generators = node.generators  # type: ignore[attr-defined]
        for generator in generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)  # type: ignore[attr-defined]

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        # Arguments belong to nested scopes, not the module.
        return
