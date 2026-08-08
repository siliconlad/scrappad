<div align="center">

# Scrappad

### Edit like a file. Explore like a REPL.

[![CI](https://github.com/siliconlad/scrappad/actions/workflows/ci.yml/badge.svg)](https://github.com/siliconlad/scrappad/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![macOS and Linux](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-58a6ff)
[![MIT license](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)

</div>

<p align="center">
  <img
    src="docs/assets/scrappad-demo.svg"
    alt="Scrappad showing Python source beside a live REPL"
    width="100%"
  >
</p>

## Quick Start

Install with [`uv`](https://docs.astral.sh/uv/):

```bash
uv tool install scrappad
scrappad
```

Or run without installing:

```bash
uvx scrappad
```

Pass a file to keep your work: `scrappad experiment.py`.

## Keyboard Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Left` / `Ctrl+Up` | Focus editor |
| `Ctrl+Right` / `Ctrl+Down` | Focus REPL and load changes |
| `Ctrl+C` | Interrupt running code |
| `Ctrl+S` | Save |
| `Ctrl+Q` | Quit |
| `Up` / `Down` | Browse REPL history |

## REPL Commands

| Command | Action |
| --- | --- |
| `:vars` | Show live names |
| `:sync` | Run editor |
| `:reset` | Reset state and run editor |
| `:clear` | Clear REPL output |
| `:help` | Show help |
