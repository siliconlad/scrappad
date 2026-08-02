"""Minimal check executed against built wheel and source distributions."""

from importlib.metadata import version

from scrappad.cli import build_parser

distribution_version = version("scrappad")
parser = build_parser()

assert distribution_version
assert parser.prog == "scrappad"
print(f"scrappad {distribution_version} imports successfully")
