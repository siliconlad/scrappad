# Pyground

**Edit like a file. Explore like a REPL.**

Pyground is a terminal workspace for experimenting with Python. It places a
real multiline editor beside a REPL that shares the editor's functions,
classes, imports, and variables—so you can refine code without repeatedly
retyping it at a prompt.

Your code is loaded only when you enter the REPL. If the buffer is incomplete
or raises an error, Pyground keeps the last working namespace active, letting
you return to the editor and fix it without losing your session.

## Install

Pyground requires Python 3.10 or newer and [`uv`](https://docs.astral.sh/uv/).

```bash
uv tool install pyground-repl
pyground
```

Running without a path opens an ephemeral `scratch.py` in your system temporary
directory. It is removed when Pyground exits. To keep your work, open an
existing file—or start a named one—by passing its path:

```bash
pyground experiment.py
```

A new file is created on disk only when you save it with `Ctrl+S`.

To run Pyground from source instead:

```bash
git clone git@github.com:siliconlad/pyground.git
cd pyground
uv sync
uv run pyground
```

## How to use it

1. Write or edit Python in the editor pane.
2. Press `Ctrl+Right` (or `F2`) to enter the REPL and load the current buffer.
3. Call your functions, inspect values, and create temporary variables.
4. Press `Ctrl+Left` to return to the editor, make changes, and repeat.

Variables created only in the REPL survive later reloads. If the editor defines
the same name, the editor's value takes precedence.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| `F2` | Switch panes; entering the REPL loads editor changes |
| `Ctrl+Left` / `Ctrl+Up` | Focus the editor |
| `Ctrl+Right` / `Ctrl+Down` | Load editor changes and focus the REPL |
| `F5` | Load the editor immediately |
| `Ctrl+S` | Save the current file |
| `Ctrl+L` | Clear REPL output |
| `Ctrl+C` | Interrupt running editor or REPL code |
| `Ctrl+Q` | Quit |
| `Up` / `Down` | Browse REPL history |

REPL commands: `:vars`, `:sync`, `:reset`, `:clear`, and `:help`.

## Responsive layout

Pyground displays the panes side by side in wide terminals. Below 100 columns,
it automatically stacks the editor above the REPL.

## A note about execution

Loading the editor executes its top-level code, including side effects. Put
repeatable definitions in the editor and trigger one-off actions from the REPL
when you do not want them to run again after every load.

Editor and REPL code runs in a separate Python worker process, so a slow or
infinite computation does not freeze the interface. Interrupting an editor load
returns focus to the editor. Switch back to the REPL or press `F5` to retry,
even when the buffer is unchanged.
