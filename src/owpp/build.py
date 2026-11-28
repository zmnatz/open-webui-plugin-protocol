"""`owpp build`: the plugins, bundled into a folder that `owpp deploy --from` deploys elsewhere.

A build is the deploy's input, written down: where the sources can be fetched (CI, with git and
the network), `owpp build` bundles each plugin; where the instance can be reached, `owpp deploy
--from <folder>` deploys exactly that, with no checkout, no git and no access to the source
repositories. Like a dist/ folder, it is generated, never committed, and the same repository
commit and owpp version build it byte for byte the same.

The folder holds, for each plugin, `<id>.py` (the bundle Open-WebUI stores) and `<id>.json`
(what the deploy needs besides the code), and `build.json`: the owpp version that built it,
whether it holds every plugin (only a complete build can prune), and, for a `--latest` build, the
commits it was moved to (such a build only deploys as a dry run).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from .bundle import FunctionFile
from .errors import OwppError
from .openwebui import FunctionMeta

FORMAT = 2
INDEX = "build.json"


@dataclass
class Build:
    """What a deploy writes: the functions, whether that is every plugin, and for a build moved
    to the latest commits, {source label: note} for the report."""

    files: list[FunctionFile]
    complete: bool = True
    latest: dict[str, str] = field(default_factory=dict)
    owpp: str = __version__


# What a function's <id>.json holds: every FunctionFile field but its code, its folder and its
# meta (which is stored as a deploy sends it, under `meta`).
_FIELDS = ("id", "file", "kind", "type", "name", "want_global", "not_global", "valves")


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def write_build(build: Build, out: Path | str) -> list[Path]:
    """Write `build` to the folder `out`: a new one, an empty one, or an earlier build (whose
    files are replaced). Refuses a folder that holds anything else. Returns the bundles written."""
    out = Path(out)
    if out.exists():
        if not out.is_dir():
            raise OwppError(f"{out} is not a folder")
        index = out / INDEX
        if index.is_file():
            for name in json.loads(index.read_text()).get("plugins", []):
                for suffix in (".py", ".json"):
                    (out / f"{name}{suffix}").unlink(missing_ok=True)
            index.unlink()
        if any(out.iterdir()):
            raise OwppError(
                f"{out} holds files that are not an owpp build; build into an empty folder"
            )
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for f in build.files:
        (out / f"{f.id}.py").write_bytes(f.content.encode("utf-8"))
        data = {k: getattr(f, k) for k in _FIELDS} | {
            "meta": f.meta.stored(),
            "sha256": _digest(f.content),
        }
        (out / f"{f.id}.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        written.append(out / f"{f.id}.py")
    index = {
        "format": FORMAT,
        "owpp": build.owpp,
        "complete": build.complete,
        "plugins": [f.id for f in build.files],
        "latest": build.latest,
    }
    (out / INDEX).write_text(json.dumps(index, indent=2) + "\n")
    return written


def _field(data: dict, key: str, kind: type, where: str) -> Any:
    value = data.get(key)
    if not isinstance(value, kind):
        raise OwppError(f"{where}: `{key}` is missing or not a {kind.__name__}")
    return value


def read_build(folder: Path | str) -> Build:
    """The build in `folder`, checked: its format, the owpp version that built it (it must be
    this one: the bundles embed its runtime), and each bundle against its recorded digest."""
    folder = Path(folder)
    index_path = folder / INDEX
    if not index_path.is_file():
        raise OwppError(f"{folder} is not an owpp build (no {INDEX}); make one with `owpp build`")
    try:
        index = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        raise OwppError(f"{index_path}: not valid JSON ({e})") from e
    where = str(index_path)
    if index.get("format") != FORMAT:
        raise OwppError(f"{where}: build format {index.get('format')!r}, this owpp reads {FORMAT}")
    built_by = _field(index, "owpp", str, where)
    if built_by != __version__:
        raise OwppError(
            f"{folder} was built by owpp {built_by}, and this is owpp {__version__}: the bundles "
            "embed the runtime of the owpp that built them, so build and deploy with the same version"
        )
    files = []
    for name in _field(index, "plugins", list, where):
        meta_path, code_path = folder / f"{name}.json", folder / f"{name}.py"
        if not meta_path.is_file() or not code_path.is_file():
            raise OwppError(f"{folder}: {name}.py or {name}.json is missing")
        data = json.loads(meta_path.read_text())
        content = code_path.read_bytes().decode("utf-8")
        if data.get("sha256") != _digest(content):
            raise OwppError(f"{code_path} does not match the build (changed since it was built)")
        missing = [k for k in (*_FIELDS, "meta") if k not in data]
        if missing:
            raise OwppError(f"{meta_path}: missing {', '.join(missing)}")
        files.append(
            FunctionFile(
                content=content,
                meta=FunctionMeta.from_stored(data["meta"]),
                **{k: data[k] for k in _FIELDS},
            )
        )
    return Build(
        files,
        complete=_field(index, "complete", bool, where),
        latest=_field(index, "latest", dict, where),
        owpp=built_by,
    )
