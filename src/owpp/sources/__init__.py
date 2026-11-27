"""Files a plugin takes from a git repo (`source:` in plugin.yaml), pinned to a commit.

`Sources` is what one run reads git through; `Sources.resolve(folder)` gives a
`ResolvedPlugin`: the folder to bundle, its manifest, its files and the commits they are
pinned to. See GLOSSARY.md."""

from ._git import GIT_URL, SHA40, TRACK, refname
from ._resolve import ResolvedPlugin, Sources, source_label
from ._upstream import is_plugin_source

__all__ = [
    "GIT_URL",
    "SHA40",
    "TRACK",
    "ResolvedPlugin",
    "Sources",
    "is_plugin_source",
    "refname",
    "source_label",
]
