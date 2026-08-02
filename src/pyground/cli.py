"""Command-line entry point."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from .app import PygroundApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyground",
        description="Open a split-screen Python editor and live REPL.",
    )
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Python file to open (default: an ephemeral temporary scratch file)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.file is not None:
        PygroundApp(Path(args.file).expanduser().resolve()).run()
        return

    with TemporaryDirectory(prefix="pyground-") as directory:
        scratch_path = Path(directory) / "scratch.py"
        scratch_path.touch()
        PygroundApp(scratch_path).run()
