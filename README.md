<div align="center">

# Scrappad

### Edit like a file. Explore like a REPL.

A focused Python workspace for the terminal—built for the moment when a REPL
is too cramped and a notebook is too much.

[![CI](https://github.com/siliconlad/scrappad/actions/workflows/ci.yml/badge.svg)](https://github.com/siliconlad/scrappad/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![macOS and Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-58a6ff)
[![MIT license](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)

</div>

<p align="center">
  <img
    src="https://raw.githubusercontent.com/siliconlad/scrappad/main/docs/assets/scrappad-demo.svg"
    alt="Scrappad showing Python source beside a live REPL"
    width="100%"
  >
</p>

Scrappad puts a real multiline editor beside a REPL that shares its functions,
classes, imports, and variables. Keep reusable code tidy on the left; probe it,
inspect it, and improvise on the right.

## Why Scrappad?

- **Code stays code.** Your experiment is an ordinary `.py` file, ready to
  keep, test, or commit.
- **You decide when it runs.** Editor changes load only when you enter the REPL
  or press `F5`—never halfway through a thought.
- **Mistakes are cheap.** Incomplete code and failed reloads leave the last
  working namespace available.
- **The terminal stays responsive.** Python runs in a separate worker, so
  `Ctrl+C` can interrupt slow code and infinite loops.
- **Scratch state stays scratch.** REPL-only variables survive editor reloads;
  `:reset` gives you a clean namespace when you want one.

## Quick start

Scrappad supports macOS and Linux and requires Python 3.10 or newer. Install it
with [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install scrappad
scrappad
```

Running `scrappad` opens an ephemeral `scratch.py` in your system temporary
directory. It disappears when the session ends. Pass a path when the work is
worth keeping:

```bash
scrappad experiment.py
```

New named files are written to disk only when you save with `Ctrl+S`.

## The workflow

1. Write or edit Python in the **editor**.
2. Press `Ctrl+Right` or `F2` to enter the **REPL** and load the buffer.
3. Call functions, inspect values, and create temporary variables.
4. Press `Ctrl+Left` to edit again, then repeat.

On wide terminals the panes sit side by side. Below 100 columns, Scrappad
automatically stacks the editor above the REPL.

## Controls

| Key | Action |
| :--- | :--- |
| `F2` | Switch panes; entering the REPL loads pending editor changes |
| `Ctrl+Left` / `Ctrl+Up` | Focus the editor |
| `Ctrl+Right` / `Ctrl+Down` | Focus the REPL and load pending changes |
| `F5` | Run the editor immediately |
| `Ctrl+C` | Interrupt running editor or REPL code |
| `Ctrl+S` | Save the current file |
| `Ctrl+L` | Clear REPL output |
| `Ctrl+Q` | Quit |
| `Up` / `Down` | Browse REPL history |

The REPL also has a small command set:

| Command | Action |
| :--- | :--- |
| `:vars` | Show live names, types, and values |
| `:sync` | Run the editor now |
| `:reset` | Discard REPL-only state and reload the editor |
| `:clear` | Clear REPL output |
| `:help` | Show command help |

<details>
<summary><strong>Execution model and recovery</strong></summary>

Loading the editor executes its top-level code, including side effects. Keep
repeatable definitions in the editor and trigger one-off actions from the REPL
when you do not want them repeated on every load.

If an editor load is interrupted, focus returns to the editor. Switch back to
the REPL or press `F5` to retry—even if the buffer is unchanged. Interrupting a
REPL command stops it at its current point, so mutations or external side
effects completed before `Ctrl+C` may remain. Use `:reset` whenever you want to
discard REPL-only state and rebuild from the editor.

</details>

## Run from source

```bash
git clone git@github.com:siliconlad/scrappad.git
cd scrappad
uv sync
uv run scrappad
```

Run the test suite with:

```bash
uv run pytest
```

## License

Scrappad is available under the [MIT License](LICENSE).
