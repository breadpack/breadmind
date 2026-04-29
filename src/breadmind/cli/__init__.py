"""breadmind CLI entrypoint (Click groups).

The legacy argparse-based entrypoint lives at ``breadmind.main:main`` and
is the one wired up via ``[project.scripts]`` in ``pyproject.toml``. This
module exposes a parallel Click ``main`` group used by tests and by
future consolidation. Subcommands register themselves below via
``main.add_command(...)``.
"""
from __future__ import annotations

import click

from breadmind.cli.migrate import migrate as migrate_group


@click.group()
def main() -> None:
    """BreadMind command-line interface."""


main.add_command(migrate_group)
