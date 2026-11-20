"""Files a plugin takes from a git repo (`source:` in plugin.yaml), pinned to a commit.

`Sources` is what one run reads them through; `Sources.resolve(folder)` gives a
`ResolvedPlugin`: the folder to bundle, its manifest, its files and the commits they are
pinned to. See GLOSSARY.md."""

from ._git import GIT_URL, SHA40, TRACK, Fetcher, Lookup, git_fetcher, resolve_ref
from ._resolve import ResolvedPlugin, Sources, source_label
from ._upstream import is_plugin_source

__all__ = [
    "GIT_URL",
    "SHA40",
    "TRACK",
    "Fetcher",
    "Lookup",
    "ResolvedPlugin",
    "Sources",
    "git_fetcher",
    "is_plugin_source",
    "resolve_ref",
    "source_label",
]
