"""Command-line interface — scaffolding stub. Subcommands land in Unit 3."""

from __future__ import annotations

import argparse
from typing import Sequence

from . import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes-plugin-sync",
        description="Sync Claude Code plugins into Hermes.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args(argv)
    return 0
