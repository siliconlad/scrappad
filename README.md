# Pyground

Pyground is a split-screen Python scratchpad for the terminal. Write normal,
multiline Python on the left and try expressions against its live namespace in
the REPL on the right.

Editor changes are loaded when you switch to the REPL, so unfinished code is
never executed while you are still typing. A reload is transactional: if the
buffer is incomplete or raises an exception, the last working namespace stays
available. Variables created in the REPL survive editor reloads unless the
editor owns a variable with the same name.

## Install and run

Python 3.10 or newer is required.

```bash
uv sync
uv run pyground
```

Open a particular file by passing its path:

```bash
uv run pyground experiment.py
```

If the file does not exist, Pyground opens a small starter buffer. It creates
the file only when you save.

## Keys

| Key | Action |
| --- | --- |
| `F2` | Switch panes, loading editor changes when entering the REPL |
| `Ctrl+Left` / `Ctrl+Up` | Focus the editor |
| `Ctrl+Right` / `Ctrl+Down` | Load editor changes and focus the REPL |
| `F5` | Reload the editor immediately |
| `Ctrl+S` | Save the editor to disk |
| `Ctrl+L` | Clear REPL output |
| `Ctrl+Q` | Quit |
| `Up` / `Down` | Browse history while in the REPL |

The REPL also understands `:vars`, `:sync`, `:reset`, `:clear`, and `:help`.

At terminal widths below 100 columns, the editor and REPL automatically stack
top-to-bottom. Wider terminals display them side-by-side.

## Notes

Editor code is executed whenever a valid change is synchronized, including its
top-level side effects. Put experiments with side effects in the REPL or trigger
them from functions if you do not want them repeated while editing.

The REPL input is intentionally one line because multiline definitions are much
easier to edit in the left pane. Semicolon-separated statements work normally.
