"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from scrappad.app import ScrappadApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scrappad",
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if sys.platform not in {"darwin", "linux"}:
        parser.error(f"Scrappad only supports macOS and Linux (detected: {sys.platform}).")
    if args.file is not None:
        ScrappadApp(Path(args.file).expanduser().resolve()).run()
        return

    with TemporaryDirectory(prefix="scrappad-") as directory:
        scratch_path = Path(directory) / "scratch.py"
        scratch_path.touch()
        ScrappadApp(scratch_path).run()
