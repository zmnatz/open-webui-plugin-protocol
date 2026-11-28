"""Sources and resolved plugins: what a run reads from git, and a plugin folder with its
`source:` applied."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import OwppError
from ..manifest import (
    Value,
    file_entry,
    folder_files,
    get,
    read_manifest,
    read_text,
    text_of,
)
from . import _git
from ._git import GIT_URL, MAX_SOURCE_BYTES, SHA40, Fetcher, KindOf, Lookup
from ._upstream import is_plugin_source, write_upstream

MAX_SKILL_FILES = 1000


def source_label(source: dict) -> str:
    """How a `source:` is named in a report and in a deployed function's meta."""
    path = text_of(source.get("path")).strip("/")
    return f"{text_of(source.get('git'))}{f' {path}' if path else ''}"


def _key(folder: str, src: object, rel: str, directory: bool = False) -> str:
    """A file (or, with `directory`, a folder) in a plugin's `source`, as the cache keys it:
    `<git>#<sha>:<path in the repo>[/]`. Refuses anything that is not a pinned, plain path."""
    where = f"{folder}/plugin.yaml: source"
    if not isinstance(src, dict):
        raise OwppError(f"{where} must have git, ref and path")
    git = text_of(src.get("git"))
    ref = text_of(src.get("ref"))
    if not GIT_URL.fullmatch(git):
        raise OwppError(f"{where}.git must be an https://, ssh:// or user@host:path git URL")
    if not ref:
        raise OwppError(
            f"{where} has no `ref:`; run `owpp pull {folder}` to pin it to the latest commit"
        )
    if not SHA40.fullmatch(ref):
        raise OwppError(
            f"{where}.ref must be a full 40-character commit SHA, not a branch or tag "
            "(those can change under you)"
        )
    parts = [p for p in [*text_of(src.get("path")).split("/"), *str(rel).split("/")] if p]
    if any(p in ("..", ".") for p in parts):
        raise OwppError(f"{where}: paths may not contain . or ..")
    if directory and not parts:
        raise OwppError(f"{where}: a directory needs a path")
    return f"{git}#{ref}:{'/'.join(parts)}{'/' if directory else ''}"


@dataclass(frozen=True)
class UpstreamParts:
    """Which parts of a plugin are the upstream's: taken verbatim from the files that its
    manifest names, so their code and versions are not ours to change. See `upstream_parts`."""

    whole: bool = False  # `source: {plugin: true}`: every part is the upstream's
    function_file: str = ""  # `function.file`
    tool_file: str = ""  # `tool.file`
    tool_is_function: bool = False  # `tool.from: function`: the tool is the function's bundle
    # Each `skills.<id>` with a `dir:` or `file:`, by its id in lower case (as a bundle holds
    # it): (path, is_dir).
    skill_paths: dict[str, tuple[str, bool]] = field(default_factory=dict)

    @property
    def function(self) -> bool:
        return self.whole or bool(self.function_file)

    @property
    def tool(self) -> bool:
        return self.whole or bool(self.tool_file) or (self.tool_is_function and self.function)

    def skill(self, skill_id: str) -> bool:
        return self.whole or str(skill_id).lower() in self.skill_paths

    @property
    def files(self) -> list[tuple[str, bool]]:
        """The files (and directories) these parts name in the source: (path, is_dir). A whole
        plugin is one directory: the source's `path`."""
        if self.whole:
            return [("", True)]
        named = [(p, False) for p in (self.function_file, self.tool_file) if p]
        return named + list(self.skill_paths.values())


def upstream_parts(manifest: dict) -> UpstreamParts:
    """The parts of a plugin that its manifest takes verbatim from the files it names: the one
    place that reads `function.file`, `tool.file`, `tool.from`, `skills.<id>.dir`/`.file` and
    `source.plugin` for this. It reads the manifest alone, so it fetches nothing."""
    if is_plugin_source(manifest):
        return UpstreamParts(whole=True)
    function, tool = manifest.get("function"), manifest.get("tool")
    skills: dict[str, tuple[str, bool]] = {}
    declared = manifest.get("skills")
    for skill_id, sk in declared.items() if isinstance(declared, dict) else []:
        if get(sk, "dir"):
            skills[str(skill_id).lower()] = (sk["dir"], True)
        elif get(sk, "file"):
            skills[str(skill_id).lower()] = (sk["file"], False)
    return UpstreamParts(
        function_file=get(function, "file") or "",
        tool_file=get(tool, "file") or "",
        tool_is_function=get(tool, "from") == "function",
        skill_paths=skills,
    )


def _taken(manifest: dict) -> list[tuple[str, bool]]:
    """The files (and directories) in `source` that a manifest refers to: (path, is_dir)."""
    return upstream_parts(manifest).files


def _size(value: Value) -> int:
    return len(value) if isinstance(value, str) else len(value["base64"])


@dataclass(frozen=True, eq=False)
class ResolvedPlugin:
    """A plugin folder with its `source:` applied.

    `root` is the folder to bundle: the plugin folder, or for a plugin taken whole from git a
    scratch copy of the upstream folder with the local overrides applied (it is gone once its
    Sources is closed). `manifest` is that folder's manifest. `pins` names each repository the
    plugin takes code from with its commit: {"<git>[ <path>]": sha}."""

    folder: Path
    manifest: dict
    pins: dict[str, str]
    # Every file taken from git: {"<path in the repo>": content}, and for what the upstream of a
    # whole plugin takes from git itself, {"<git> <path in that repo>": content}.
    taken: dict[str, Value]
    _root: Path
    # The files of `manifest`'s own `source:`, by path inside its `path`.
    _files: dict[str, Value] = field(repr=False)
    _sources: Sources = field(repr=False)

    @property
    def root(self) -> Path:
        if self._root != self.folder and self._sources.closed:
            raise OwppError(
                f"{self.folder.name}: its upstream copy was deleted when its Sources was closed"
            )
        return self._root

    def read(self, rel: str) -> str:
        """The text of a file the manifest names: from its `source:` when it has one, else
        from the folder."""
        if not self.manifest.get("source"):
            return read_text(self.root / rel)
        value = self._files.get(str(rel).strip("/"))
        if value is None:
            raise OwppError(f"{self.folder.name}: {rel} is not one of the files its source takes")
        if not isinstance(value, str):
            raise OwppError(f"{self.folder.name}: {rel} in its source is not UTF-8 text")
        return value

    def read_dir(self, rel: str) -> list[dict]:
        """A folder the manifest names, as [{path, content, encoding?}] sorted by path: from
        its `source:` when it has one, else from the folder. Symlinks are never followed."""
        if not self.manifest.get("source"):
            return folder_files(self.root / rel)
        prefix = f"{str(rel).strip('/')}/"
        files = [
            file_entry(path[len(prefix) :], value)
            for path, value in self._files.items()
            if path.startswith(prefix)
        ]
        if not files:
            raise OwppError(f"{self.folder.name}: {rel} is not a folder its source takes")
        return sorted(files, key=lambda f: f["path"])


class Sources:
    """What one run reads from git through: each plugin file at its pinned commit, fetched
    once, the scratch copies of plugins taken whole from git, and what a branch or tag names.

    Use it as a context manager: the scratch copies are deleted when it closes (or when the
    process exits, for one that is never closed)."""

    def __init__(
        self,
        fetcher: Fetcher | None = None,
        lookup: Lookup | None = None,
        kind_of: KindOf | None = None,
    ):
        self.fetcher = fetcher if fetcher is not None else _git.git_fetcher
        self._lookup = lookup if lookup is not None else _git.resolve_ref
        self._kind_of = kind_of if kind_of is not None else _git.ref_kind
        self._cache: dict[str, dict[str, Value]] = {}
        self._made: dict[str, Path] = {}
        self._scratch: tempfile.TemporaryDirectory | None = None
        self.closed = False

    def __enter__(self) -> Sources:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._scratch is not None:
            self._scratch.cleanup()
            self._scratch = None
        self._made.clear()
        self.closed = True

    def latest(self, git: str, ref: str) -> str | None:
        """The commit a branch or tag of `git` points at now (`refs/heads/<branch>`,
        `refs/tags/<tag>`, a name that may be either, or `HEAD`: the default branch)."""
        return self._lookup(git, ref)

    def kind(self, git: str, name: str) -> str | None:
        """Whether `name` is a "branch" or a "tag" of `git` (a tag wins, as in git); None
        when it is neither, or the repository cannot be reached."""
        return self._kind_of(git, name)

    def files(self, git: str, sha: str, path: str = "") -> dict[str, Value]:
        """Every file in the folder `path` of `git` ("": the whole repository) at the commit
        `sha`, by path inside it: for looking at a folder no `source:` names yet."""
        prefix = f"{path}/" if path else ""
        got = self.fetcher(git, sha, [prefix or "./"])
        return {k[len(prefix) :]: v for k, v in got.items() if k.startswith(prefix)}

    def resolve(self, folder: Path | str, ref: str | None = None) -> ResolvedPlugin:
        """The plugin in `folder`, with what its `source:` takes fetched at the pinned commit,
        or at `ref` instead when given."""
        if self.closed:
            raise OwppError("this Sources is closed")
        folder = Path(folder)
        manifest = read_manifest(folder)
        src = manifest.get("source")
        if not src:
            return ResolvedPlugin(folder, manifest, {}, {}, folder, {}, self)
        if ref is not None and isinstance(src, dict):
            src = {**src, "ref": ref}
            manifest = {**manifest, "source": src}
        pins = {source_label(src): text_of(src.get("ref"))}
        files = self._fetch(folder.name, src, _taken(manifest))
        taken = self._repo_paths(src, files)
        if not is_plugin_source(manifest):
            return ResolvedPlugin(folder, manifest, pins, taken, folder, files, self)
        root = self._upstream_copy(folder, manifest, files)
        inner = read_manifest(root)
        inner_src = inner.get("source")
        inner_files: dict[str, Value] = {}
        if inner_src:
            inner_files = self._fetch(folder.name, inner_src, _taken(inner))
            pins[source_label(inner_src)] = text_of(inner_src.get("ref"))
            git = text_of(inner_src.get("git"))
            taken |= {f"{git} {p}": v for p, v in self._repo_paths(inner_src, inner_files).items()}
        return ResolvedPlugin(folder, inner, pins, taken, root, inner_files, self)

    # ---- inside -------------------------------------------------------------------------

    @staticmethod
    def _repo_paths(src: dict, files: dict[str, Value]) -> dict[str, Value]:
        base = "/".join(p for p in text_of(src.get("path")).split("/") if p)
        return {f"{base}/{rel}" if base else rel: v for rel, v in files.items()}

    def _fetch(self, name: str, src: object, entries: list[tuple[str, bool]]) -> dict[str, Value]:
        """What `src` holds at its commit for each (path, is_dir) entry: {path inside the
        source's `path`: content}. Each repository and commit is fetched once per call, and
        each file once per Sources."""
        keys = [_key(name, src, rel, d) for rel, d in entries]
        missing = [k for k in keys if k not in self._cache]
        groups: dict[str, tuple[str, str, list[str]]] = {}
        for key in missing:
            git, ref, path = re.fullmatch(r"(.*)#([0-9a-f]{40}):(.*)", key, re.DOTALL).groups()
            groups.setdefault(f"{git}#{ref}", (git, ref, []))[2].append(path)
        for git, ref, paths in groups.values():
            got = self.fetcher(git, ref, paths)
            for path in paths:
                if path.endswith("/"):
                    under = {k: v for k, v in got.items() if k.startswith(path)}
                    if not under:
                        raise OwppError(f"no files under {path} in {git} at {ref}")
                    if len(under) > MAX_SKILL_FILES:
                        raise OwppError(f"{path} in {git} has more than {MAX_SKILL_FILES} files")
                elif path in got:
                    under = {path: got[path]}
                else:
                    raise OwppError(f"{path} not found in {git} at {ref}")
                for p, v in under.items():
                    if _size(v) > MAX_SOURCE_BYTES:
                        raise OwppError(f"{git} {p} is larger than {MAX_SOURCE_BYTES} bytes")
                self._cache[f"{git}#{ref}:{path}"] = under
        base = "/".join(p for p in text_of(get(src, "path")).split("/") if p)
        out: dict[str, Value] = {}
        for key in keys:
            for p, v in self._cache[key].items():
                out[p[len(base) + 1 :] if base else p] = v
        return out

    def _upstream_copy(self, folder: Path, manifest: dict, files: dict[str, Value]) -> Path:
        """The scratch copy of a whole plugin's upstream folder, made once per Sources for the
        same local manifest, config.yaml and files."""
        local_text = read_text(folder / "plugin.yaml")
        config = folder / "config.yaml"
        config_text = read_text(config) if config.is_file() else None
        where = _key(folder.name, manifest["source"], "", True)
        digest = hashlib.sha256(
            repr(
                (str(folder.resolve()), where, local_text, config_text, sorted(files.items()))
            ).encode()
        ).hexdigest()[:16]
        if digest in self._made:
            return self._made[digest]
        if self._scratch is None:
            self._scratch = tempfile.TemporaryDirectory(prefix="owpp-upstream-")
        root = Path(self._scratch.name) / digest / folder.name
        write_upstream(root, folder, manifest, files, where)
        self._made[digest] = root
        return root
