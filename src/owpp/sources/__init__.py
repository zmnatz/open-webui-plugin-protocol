"""Files a plugin takes from a git repo (`source:` in plugin.yaml), pinned to a commit.

`Sources` is what one run reads git through; `Sources.resolve(folder)` gives a
`ResolvedPlugin`: the folder to bundle, its manifest, its files and the commits they are
pinned to. See GLOSSARY.md."""

from ._git import GIT_URL, SHA40, TRACK, refname
from ._resolve import ResolvedPlugin, Sources, UpstreamParts, source_label, upstream_parts
from ._upstream import is_plugin_source

__all__ = [
    "GIT_URL",
    "SHA40",
    "TRACK",
    "ResolvedPlugin",
    "Sources",
    "UpstreamParts",
    "is_plugin_source",
    "refname",
    "source_label",
    "upstream_parts",
]
