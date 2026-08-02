"""Minimal check executed against built wheel and source distributions."""

from importlib.metadata import version

from pyground.cli import build_parser

distribution_version = version("pyground-repl")
parser = build_parser()

assert distribution_version
assert parser.prog == "pyground"
print(f"pyground-repl {distribution_version} imports successfully")
