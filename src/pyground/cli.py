"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .app import PygroundApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyground",
        description="Open a split-screen Python editor and live REPL.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default="scratch.py",
        help="Python file to open (default: scratch.py)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    PygroundApp(Path(args.file).expanduser().resolve()).run()

