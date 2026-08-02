"""Execution engine shared by the editor and REPL.

The UI deliberately knows very little about Python execution. Keeping this
logic here also makes the important namespace behavior straightforward to
test without starting a terminal application.
"""

from __future__ import annotations

import ast
import builtins
import codeop
import contextlib
import io
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import CodeType
from typing import Any, Literal

SyncState = Literal["ok", "incomplete", "error"]


@dataclass(frozen=True)
class SyncResult:
    state: SyncState
    output: str = ""
    error: str = ""
    interrupted: bool = False


@dataclass(frozen=True)
class ReplResult:
    output: str = ""
    value: Any = None
    has_value: bool = False
    error: str = ""
    interrupted: bool = False


class _BoundedOutput(io.StringIO):
    """Capture user output without allowing an infinite print loop to exhaust RAM."""

    def __init__(self, limit: int = 100_000) -> None:
        super().__init__()
        self.limit = limit
        self.truncated = False

    def write(self, text: str) -> int:
        original_length = len(text)
        remaining = self.limit - self.tell()
        if remaining > 0:
            super().write(text[:remaining])
        if original_length > max(remaining, 0):
            self.truncated = True
        return original_length

    def getvalue(self) -> str:
        value = super().getvalue()
        if self.truncated:
            value += "\n... <output truncated>\n"
        return value


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
        self.last_source = ""

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
            # compile_command distinguishes code that is temporarily incomplete
            # while someone is in the middle of typing a block.
            maybe_code = codeop.compile_command(source, self.filename, "exec")
        except (SyntaxError, OverflowError, ValueError):
            return None, SyncResult("error", error=_format_exception())

        if maybe_code is None:
            return None, SyncResult("incomplete")
        return maybe_code, None

    def sync(self, source: str) -> SyncResult:
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
        stdout = _BoundedOutput()
        stderr = _BoundedOutput()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(code, candidate, candidate)  # noqa: S102 - this is a Python REPL
        except KeyboardInterrupt:
            output = stdout.getvalue() + stderr.getvalue()
            return SyncResult(
                "error",
                output=output,
                error="KeyboardInterrupt",
                interrupted=True,
            )
        except BaseException:  # noqa: BLE001 - report user exceptions in the REPL
            output = stdout.getvalue() + stderr.getvalue()
            return SyncResult("error", output=output, error=_format_exception())

        statically_bound = _top_level_bound_names(source)
        changed_or_new = {
            name
            for name, value in candidate.items()
            if not name.startswith("__")
            and (name not in before or value is not before[name])
        }
        self._editor_names = statically_bound | changed_or_new
        self.namespace = candidate
        self.last_source = source
        return SyncResult("ok", output=stdout.getvalue() + stderr.getvalue())

    def reset(self, source: str | None = None) -> SyncResult:
        """Discard REPL scratch names and rebuild from the editor."""

        source = self.last_source if source is None else source
        previous_namespace = self.namespace
        previous_editor_names = self._editor_names
        self.namespace = self._base_namespace()
        self._editor_names.clear()
        result = self.sync(source)
        if result.state != "ok":
            self.namespace = previous_namespace
            self._editor_names = previous_editor_names
        return result

    def execute(self, command: str) -> ReplResult:
        """Execute one REPL command, displaying the final expression if present."""

        stdout = _BoundedOutput()
        stderr = _BoundedOutput()
        try:
            module = ast.parse(command, self.filename, mode="exec")
            expression: ast.expr | None = None
            if module.body and isinstance(module.body[-1], ast.Expr):
                expression = module.body.pop().value

            value: Any = None
            has_value = False
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
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
                output=stdout.getvalue() + stderr.getvalue(),
                value=value,
                has_value=has_value,
            )
        except KeyboardInterrupt:
            return ReplResult(
                output=stdout.getvalue() + stderr.getvalue(),
                error="KeyboardInterrupt",
                interrupted=True,
            )
        except BaseException:  # noqa: BLE001 - report user exceptions in the REPL
            return ReplResult(
                output=stdout.getvalue() + stderr.getvalue(),
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
    """Collect module bindings while not descending into nested scopes."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def _target(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self.names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for element in node.elts:
                self._target(element)
        elif isinstance(node, ast.Starred):
            self._target(node.value)

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

    def visit_arg(self, node: ast.arg) -> None:
        # Arguments belong to nested scopes, not the module.
        return
