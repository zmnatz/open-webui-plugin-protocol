"""Versions: reading them from bundles, bumping them in files, and checking they were bumped.

A plugin has up to three kinds of version, each where Open-WebUI reads it:

- the **function's**, `version:` in plugin.yaml's `function:` section (the plugin's version, the
  one Open-WebUI shows; for a loose `<id>.py`, in its docstring header);
- the **tool's**, `version:` in plugin.yaml's `tool:` section;
- each **skill's**, `version:` in its SKILL.md front matter (optional).

`owpp version` shows them, and changes one in place (keeping comments and layout), adding an
entry to the plugin's CHANGELOG.md. `owpp check --since <ref>` fails when something changed since that git ref
but its version did not. Code taken from a git repository (`source:`) carries the upstream's
versions, which are not ours to bump; a move of its commit counts as a change of the plugin.
"""

from __future__ import annotations

import datetime as _dt
import io
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .bundle import FunctionFile, load_function_files, parse_frontmatter, parse_skill
from .errors import OwppError
from .manifest import get, parse_yaml, read_manifest, read_text, set_key, text_of
from .sources import Sources, is_plugin_source

SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
PARTS = ("patch", "minor", "major")


# ---- reading versions out of a bundle -----------------------------------------------


def version_of(content: str | None) -> str:
    """The `version:` of a module's docstring header."""
    return str(parse_frontmatter(content or "").get("version") or "")


def parse_version(version: str) -> tuple[int, ...] | None:
    """`1.2.3` as (1, 2, 3), for ordering; None for anything that is not dotted numbers."""
    parts = version.strip().lstrip("v").split(".")
    return tuple(int(p) for p in parts) if version and all(p.isdigit() for p in parts) else None


def is_older(new: str, live: str) -> bool:
    """Whether deploying `new` over `live` goes back a version (False when either cannot be
    ordered)."""
    a, b = parse_version(new), parse_version(live)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) < b + (0,) * (width - len(b))


# ---- the next version -----------------------------------------------------------------


def next_version(current: str, how: str = "patch") -> str:
    """`how` is patch, minor, major, or an explicit X.Y.Z. No current version starts at 0.1.0."""
    if SEMVER.fullmatch(how):
        return how
    if how not in PARTS:
        raise OwppError(
            f"bump by patch, minor or major, or give a version like 1.2.3 (not {how!r})"
        )
    if not current:
        return "0.1.0"
    m = SEMVER.fullmatch(current)
    if not m:
        raise OwppError(
            f"the version {current!r} is not X.Y.Z, so it cannot be bumped by {how}; give the new one"
        )
    major, minor, patch = (int(g) for g in m.groups())
    if how == "major":
        return f"{major + 1}.0.0"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---- writing a version into a file -----------------------------------------------------


def set_block_version(text: str, block: str, version: str) -> tuple[str, str]:
    """plugin.yaml with `version:` of the top-level `block:` mapping set (added after `title:`
    when it has none), comments and layout kept: the new text and the old version ("" when it
    had none)."""
    section = get(parse_yaml(text), block)
    if isinstance(section, dict) and section.get("file"):
        raise OwppError(f"the {block} is taken verbatim from its source, which sets its version")
    old = text_of(get(section, "version"))
    return set_key(text, f"{block}.version", version, after="title"), old


def set_front_matter_version(text: str, version: str) -> tuple[str, str]:
    """A SKILL.md with `version:` in its YAML front matter set (added after `name:`)."""
    m = re.match(r"---\n([\s\S]*?)\n---\n?", text.replace("\r\n", "\n"))
    if not m:
        raise OwppError("the SKILL.md has no front matter (--- ... ---) to put a version in")
    body = m.group(1).split("\n")
    for i, line in enumerate(body):
        v = re.match(r"(version:\s*)([\"']?)([^\"'#\s]*)\2(\s*#.*)?$", line)
        if v:
            body[i] = f"{v.group(1)}{version}{v.group(4) or ''}"
            return f"---\n{chr(10).join(body)}\n---\n" + text[m.end() :], v.group(3)
    at = next((i + 1 for i, line in enumerate(body) if line.startswith("name:")), len(body))
    body.insert(at, f"version: {version}")
    return f"---\n{chr(10).join(body)}\n---\n" + text[m.end() :], ""


def set_header_version(text: str, version: str) -> tuple[str, str]:
    """A loose `<id>.py` with `version:` of its docstring header set."""
    m = re.match(r'(\s*""")([\s\S]*?)(""")', text)
    if not m:
        raise OwppError("the file has no docstring header to put a version in")
    head = m.group(2)
    v = re.search(r"^(version:[ \t]*)(.*)$", head, re.M)
    if v:
        new_head = head[: v.start()] + f"{v.group(1)}{version}" + head[v.end() :]
        old = v.group(2).strip()
    else:
        new_head = re.sub(
            r"^(title:.*\n)", rf"\g<1>version: {version}\n", head, count=1, flags=re.M
        )
        if new_head == head:  # no title: first line of the header
            new_head = f"\nversion: {version}" + (head if head.startswith("\n") else "\n" + head)
        old = ""
    return text[: m.start(2)] + new_head + text[m.end(2) :], old


# ---- CHANGELOG.md -----------------------------------------------------------------------


def changelog_text(title: str, version: str, lines: list[str], today: str) -> str:
    entries = "\n".join(f"- {line}" for line in lines)
    return f"# {title} changelog\n\n## {version} ({today})\n\n{entries}\n"


def add_changelog_entry(
    folder: Path, title: str, version: str, lines: list[str], today: str
) -> Path:
    """A `## <version> (<date>)` entry at the top of the plugin's CHANGELOG.md (made if missing)."""
    path = folder / "CHANGELOG.md"
    entry = f"## {version} ({today})\n\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    if not path.exists():
        path.write_bytes(changelog_text(title, version, lines, today).encode("utf-8"))
        return path
    text = read_text(path)
    m = re.search(r"^## ", text, re.M)
    text = (
        f"{text[: m.start()]}{entry}\n{text[m.start() :]}" if m else f"{text.rstrip()}\n\n{entry}"
    )
    path.write_bytes(text.encode("utf-8"))
    return path


def changelog_problem(folder: Path, version: str) -> str | None:
    """Why the plugin's CHANGELOG.md does not do (None when it does, or there is none)."""
    path = folder / "CHANGELOG.md"
    if not path.exists() or not version:
        return None
    if not re.search(rf"^##\s+\[?v?{re.escape(version)}\]?(\s|$)", read_text(path), re.M):
        return f"CHANGELOG.md has no `## {version}` entry for the current version"
    return None


# ---- owpp version: showing them ----------------------------------------------------------


UPSTREAM = "(the upstream's)"


def versions_of(directory: Path, plugin_id: str) -> list[tuple[str, str]]:
    """A plugin's versions as its files declare them: [(what, version)], the function first.
    Read from the files, not bundled, so a plugin from git needs no fetch: what it takes verbatim
    is shown as the upstream's."""
    folder, loose = directory / plugin_id, directory / f"{plugin_id}.py"
    if loose.is_file() and not folder.is_dir():
        return [("function", version_of(read_text(loose)))]
    if not (folder / "plugin.yaml").is_file():
        raise OwppError(f"no plugin {plugin_id} in {directory}")
    manifest = read_manifest(folder)
    if is_plugin_source(manifest):
        return [("function", UPSTREAM)]
    out = []
    for block in ("function", "tool"):
        section = manifest.get(block)
        if not isinstance(section, dict):
            continue
        label = block if block == "function" else f"tool {get(section, 'id') or plugin_id}"
        verbatim = section.get("file") or section.get("from")
        out.append((label, UPSTREAM if verbatim else str(get(section, "version") or "")))
    declared = manifest.get("skills")
    if manifest.get("source") and isinstance(declared, dict):
        out += [(f"skill {s}", UPSTREAM) for s in declared]
    skills = folder / "skills"
    for path in sorted(skills.glob("*/SKILL.md")) if skills.is_dir() else []:
        fm, _ = parse_skill(str(path), read_text(path))
        out.append((f"skill {path.parent.name}", str(fm.get("version") or "")))
    return out


# ---- owpp version: changing one ---------------------------------------------------------------------------


@dataclass
class Bumped:
    what: str  # "function", "tool <id>", "skill <id>"
    file: Path
    old: str
    new: str


def bump(
    directory: Path,
    plugin_id: str,
    how: str = "patch",
    tool: bool = False,
    skill: str | None = None,
    message: str = "",
    today: str | None = None,
    changelog: bool = True,
) -> list[Bumped]:
    """Bump one version of a plugin: the function's (default), its tool's, or one skill's."""
    folder, loose = directory / plugin_id, directory / f"{plugin_id}.py"
    if loose.is_file() and not folder.is_dir():
        if tool or skill:
            raise OwppError(f"{loose.name} is a single function: it has no tool or skills")
        text, old = set_header_version(read_text(loose), next_version_from_file(loose, how))
        new = version_of(text)
        loose.write_bytes(text.encode("utf-8"))
        return [Bumped("function", loose, old, new)]
    if not (folder / "plugin.yaml").is_file():
        raise OwppError(f"no plugin {plugin_id} in {directory}")
    manifest = read_manifest(folder)
    if is_plugin_source(manifest):
        raise OwppError(
            f"{plugin_id} is taken whole from git, so its versions are the upstream's; "
            f"`owpp pull {plugin_id}` moves it to a newer commit"
        )
    if skill:
        path = folder / "skills" / skill / "SKILL.md"
        if not path.is_file():
            raise OwppError(f"{plugin_id} has no skill {skill} (skills/{skill}/SKILL.md)")
        fm, _ = parse_skill(str(path), read_text(path))
        new = next_version(str(fm.get("version") or ""), how)
        text, old = set_front_matter_version(read_text(path), new)
        path.write_bytes(text.encode("utf-8"))
        return [Bumped(f"skill {skill}", path, old, new)]
    block = "tool" if tool else "function"
    section = manifest.get(block)
    if not isinstance(section, dict):
        raise OwppError(f"{plugin_id}/plugin.yaml has no `{block}:` section")
    if section.get("file") or section.get("from"):
        raise OwppError(
            f"{plugin_id}'s {block} is taken verbatim from elsewhere, which sets its version"
        )
    path = folder / "plugin.yaml"
    new = next_version(str(get(section, "version") or ""), how)
    text, old = set_block_version(read_text(path), block, new)
    path.write_bytes(text.encode("utf-8"))
    done = [
        Bumped(f"tool {get(section, 'id') or plugin_id}" if tool else "function", path, old, new)
    ]
    if block == "function" and changelog:
        title = str(get(section, "title") or plugin_id)
        add_changelog_entry(
            folder, title, new, [message or "What changed."], today or _dt.date.today().isoformat()
        )
    return done


def next_version_from_file(path: Path, how: str) -> str:
    return next_version(version_of(read_text(path)), how)


# ---- owpp check --since ------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, timeout=120
        ).stdout
    except FileNotFoundError as e:
        raise OwppError("`owpp check --since` needs the git CLI") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or b"").decode("utf-8", "replace").strip()
        raise OwppError(f"git {' '.join(args)}: {detail}") from e


def tree_at(directory: Path, ref: str, into: Path) -> Path | None:
    """The plugins folder as it was at git `ref`, extracted under `into`; None when the folder
    did not exist then."""
    directory = directory.resolve()
    top = Path(_git(directory, "rev-parse", "--show-toplevel").decode().strip())
    if ref.startswith("-"):
        raise OwppError(f"{ref!r} is not a git ref")
    _git(directory, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    rel = directory.relative_to(top).as_posix()
    listing = _git(top, "ls-tree", "--name-only", ref, "--", rel or ".")
    if not listing.strip():
        return None
    data = _git(top, "archive", "--format=tar", ref, "--", rel or ".")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            target = (into / member.name).resolve()
            if not (member.isfile() or member.isdir()) or not target.is_relative_to(into.resolve()):
                continue  # links and anything outside are not plugin files
            tar.extract(member, into, set_attrs=False)
    return into / rel if rel else into


@dataclass
class Finding:
    id: str
    message: str
    fix: str = ""

    def __str__(self) -> str:
        return f"{self.id}: {self.message}" + (f" (run `{self.fix}`)" if self.fix else "")


def _from_source(manifest: dict, kind: str, item_id: str = "") -> bool:
    """Whether the plugin's function, tool or skill is taken verbatim, so it keeps the upstream's
    version. `item_id` says which skill."""
    if is_plugin_source(manifest):  # a whole plugin from git: every version is the upstream's
        return True
    if kind == "skill":
        declared = manifest.get("skills")
        entries = declared.items() if isinstance(declared, dict) else []
        # a bundle holds a skill's id in lower case
        section = next((v for k, v in entries if str(k).lower() == item_id), None)
        keys = ("file", "dir")
    else:
        section = manifest.get(kind)
        keys = ("file", "from")
    return isinstance(section, dict) and any(section.get(k) for k in keys)


def unbumped(old: FunctionFile, new: FunctionFile, manifest: dict, since: str) -> list[Finding]:
    """What changed between `old` and `new` without a new version."""
    from .compare import compare  # noqa: PLC0415 (compare reads versions with this module)

    function, *items = compare(old.content, new.content).parts
    findings: list[Finding] = []
    sourced = bool(manifest.get("source"))
    plugin_changed = function.status != "unchanged" or old.meta.sources != new.meta.sources
    fixes = {
        "tool": f"owpp version {new.id} patch --tool",
        "skill": f"owpp version {new.id} patch --skill {{id}}",
    }
    for part in items:
        if part.status == "unchanged":
            continue
        upstream = sourced and _from_source(manifest, part.kind, part.id)
        if part.status != "changed" or upstream or not (part.old_version or part.new_version):
            plugin_changed = True  # added, removed, upstream's or unversioned: the plugin's change
        elif part.old_version == part.new_version:
            findings.append(
                Finding(
                    f"{part.kind} {part.id}",
                    f"changed since {since} but its version is still {part.new_version}",
                    fixes[part.kind].format(id=part.id),
                )
            )
    if plugin_changed and function.old_version == function.new_version:
        if _from_source(manifest, "function"):
            return findings  # the upstream function's version is the upstream's to change
        findings.insert(
            0,
            Finding(
                new.id,
                f"changed since {since} but its version is still {function.new_version or '(none)'}",
                f"owpp version {new.id} patch",
            ),
        )
    return findings


def check_since(
    directory: Path,
    since: str,
    ids: list[str] | None = None,
    sources: Sources | None = None,
    new_files: list[FunctionFile] | None = None,
) -> list[Finding]:
    """Every plugin in `directory` that changed since git `since` without a new version."""
    sources = sources if sources is not None else Sources()
    if new_files is None:
        new_files = load_function_files(directory, sources)
    with tempfile.TemporaryDirectory(prefix="owpp-since-") as work:
        old_dir = tree_at(directory, since, Path(work))
        if old_dir is None or not old_dir.is_dir():
            return []
        old_files = {f.id: f for f in load_function_files(old_dir, sources)}
    findings: list[Finding] = []
    for f in new_files:
        if ids and f.id not in ids:
            continue
        old = old_files.get(f.id)
        if old is None:
            continue  # new since then: any version is a first version
        folder = directory / f.id
        manifest = read_manifest(folder) if (folder / "plugin.yaml").exists() else {}
        findings += unbumped(old, f, manifest, since)
    return findings
