"""Sbomly: see what changed between two SBOMs, and what deserves a closer look."""

__version__ = "1.0.0"


def main() -> None:
    from .cli import main as _main

    _main()
