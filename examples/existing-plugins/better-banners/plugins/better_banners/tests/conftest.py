"""For the mutation experiment: BB_MUTANT names a mutated event.py to load in place of the
pinned one (owui.load's stand-in sources)."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def plugin(owui, plugin_dir):
    mutant = os.environ.get("BB_MUTANT")
    if mutant:
        return owui.load(plugin_dir, sources={"event.py": Path(mutant).read_text()})
    return owui.load(plugin_dir)
