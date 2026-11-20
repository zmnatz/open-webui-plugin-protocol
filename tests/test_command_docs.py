"""Every owpp command has a page in docs/commands/, and the page documents each of its flags."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from owpp.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "docs" / "commands"


def commands() -> dict[str, argparse.ArgumentParser]:
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return dict(sub.choices)


def flags(command: argparse.ArgumentParser) -> list[str]:
    return [
        flag
        for action in command._actions
        if not isinstance(action, argparse._HelpAction)
        for flag in action.option_strings
    ]


def test_there_are_commands_to_check():
    assert {"deploy", "check", "pull"} <= set(commands())


@pytest.mark.parametrize("name", list(commands()))
def test_each_command_has_a_page_in_the_commands_menu(name):
    """docs/commands/<name>.md exists, is titled `owpp <name>`, and is in zensical.toml's
    Commands section."""
    page = PAGES / f"{name}.md"
    assert page.is_file(), f"owpp {name} has no page: write docs/commands/{name}.md"
    assert page.read_text().startswith(f"# owpp {name}\n")
    # Read as text: tomllib is Python 3.11+, and owpp supports 3.10.
    toml = (ROOT / "zensical.toml").read_text()
    section = re.search(r'\{ "Commands" = \[(.*?)\] \}', toml, re.S)
    assert section, 'zensical.toml has no { "Commands" = [...] } section'
    assert f'"commands/{name}.md"' in section.group(1)


@pytest.mark.parametrize(
    ("name", "flag"), [(n, f) for n, p in commands().items() for f in flags(p)]
)
def test_each_flag_is_in_its_commands_options_table(name, flag):
    """A row of the page's options table starts with the flag, in code."""
    text = (PAGES / f"{name}.md").read_text()
    rows = re.findall(r"^\| (.+?) \|", text.partition("## Options")[2], re.M)
    assert any(re.search(rf"`{re.escape(flag)}[ `]", row) for row in rows), (
        f"docs/commands/{name}.md: no row for {flag} in its ## Options table"
    )
