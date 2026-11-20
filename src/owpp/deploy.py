"""Deploys a folder of Open-WebUI plugins into a running Open-WebUI through its admin API
(docs/tooling.md). Normally run through the CLI (`owpp deploy`).

The repo is the source of truth: a function whose code differs is updated, one that is
missing is created, activated and (for a Filter, unless it says `global: false`) made
global. Existing functions keep their active/global state and their valves, which are
stored outside the code. A plugin that declares `global: true` is kept active and global on
every run, not just when created; one that declares `global: false` is kept out of global.

Every function it deploys is marked as git-controlled (meta.managed_by, plus a note in the
description the UI shows). That mark is also the only thing it will delete: a marked
function whose folder is gone is removed, and a function without the mark (made by hand in
the UI) is never touched. Deleting more than half of the marked functions at once is
refused unless --force-prune is given, so a renamed folder or an emptied one cannot wipe
them all.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, NamedTuple

from .bundle import VALID_ID, FunctionFile, load_function_files
from .errors import OwppError
from .sources import Fetcher, fetch_sources, git_fetcher, plugin_folders, source_keys
from .versioning import (
    is_older,
    own_code,
    same,
    skill_version,
    skills_of,
    tool_version,
    tools_of,
    version_of,
)

API = "/api/v1/functions"

# Stored in each deployed function's meta (meta.managed_by); the only thing pruning acts
# on, so a deploy never touches a function it did not create. Override it per deployment
# (--managed-by / OWPP_MANAGED_BY), and never change it for an instance that already has
# functions deployed: they would look hand-made and stop being pruned.
MANAGED_BY = "open-webui-plugin-protocol"


# ---- http ---------------------------------------------------------------------


class HttpResponse(NamedTuple):
    status: int
    text: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


Fetch = Callable[[str, str, "dict[str, str] | None", "bytes | None"], HttpResponse]


def urllib_fetch(
    method: str, url: str, headers: dict[str, str] | None = None, body: bytes | None = None
) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (admin-chosen URL)
            return HttpResponse(response.status, response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return HttpResponse(e.code, e.read().decode("utf-8", "replace"))


@dataclass
class Options:
    base_url: str
    api_key: str
    dir: Path
    dry_run: bool = False
    force_prune: bool = False
    only: list[str] | None = None
    managed_by: str = MANAGED_BY
    # With dry_run: report against the latest commit each git-sourced plugin tracks, not the
    # pinned one (as if `owpp sync` had run), without changing plugin.yaml.
    sync: bool = False
    # Deploy even where the live version is newer than the repository's (a downgrade).
    force: bool = False
    fetch: Fetch = field(default=urllib_fetch, repr=False)
    git_fetcher: Fetcher = field(default=git_fetcher, repr=False)
    resolve: Callable[[str, str], str | None] | None = field(default=None, repr=False)


def options_from_env(
    env: Mapping[str, str] | None = None,
    *,
    dir: str | os.PathLike | None = None,
    only: str | None = None,
    dry_run: bool = False,
    force_prune: bool = False,
    managed_by: str | None = None,
    sync: bool = False,
    force: bool = False,
) -> Options:
    """Flags win over the environment, which wins over the defaults."""
    env = os.environ if env is None else env
    return Options(
        base_url=env.get("OPEN_WEBUI_URL", "").rstrip("/"),
        api_key=env.get("OPEN_WEBUI_API_KEY", ""),
        dir=Path(
            dir or env.get("OWPP_PLUGINS_DIR") or env.get("FUNCTIONS_DIR") or "plugins"
        ).resolve(),
        dry_run=dry_run,
        force_prune=force_prune,
        only=[i for i in only.split(",") if i] if only else None,
        managed_by=managed_by or env.get("OWPP_MANAGED_BY") or MANAGED_BY,
        sync=sync,
        force=force,
    )


def _call(opts: Options, method: str, path: str, body: dict | None = None) -> Any:
    headers = {"Authorization": f"Bearer {opts.api_key}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    res = opts.fetch(method, f"{opts.base_url}{path}", headers, data)
    if not res.ok:
        raise OwppError(f"{method} {path} -> HTTP {res.status}: {res.text[:300]}")
    try:
        return json.loads(res.text)
    except ValueError:
        return res.text


def _field(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def wait_for_health(opts: Options, attempts: int = 6, delay: float = 30.0) -> None:
    """Open-WebUI may still be starting (the stack redeploys on the same push). Six tries
    30 s apart (~3 min); rerun the workflow if a redeploy takes longer."""
    for i in range(attempts):
        try:
            if opts.fetch("GET", f"{opts.base_url}/health", None, None).ok:
                return
        except OSError:
            pass  # not up yet
        if i < attempts - 1:
            time.sleep(delay)
    raise OwppError(f"{opts.base_url}/health did not answer in time")


# ---- planning -----------------------------------------------------------------


@dataclass
class PlanItem:
    file: FunctionFile
    action: str  # create | update | unchanged | invalid
    existing: dict | None = None


def _norm(s: Any) -> str:
    return str(s or "").replace("\r\n", "\n").rstrip()


def replace_imports(content: Any) -> str:
    """Open-WebUI rewrites these import prefixes in the code before it stores it
    (utils/plugin.py replace_imports), so the stored copy of a file that uses them never
    equals the file. Compare against the rewritten text."""
    return (
        str(content or "")
        .replace("from utils", "from open_webui.utils")
        .replace("from apps", "from open_webui.apps")
        .replace("from main", "from open_webui.main")
        .replace("from config", "from open_webui.config")
    )


def plan_deploy(
    files: list[FunctionFile], live: list[dict], managed_by: str = MANAGED_BY
) -> list[PlanItem]:
    """What to do for each function, given the ones the server already has (each with its
    `content`; see _with_content). A function whose code matches but that is not yet marked
    (or whose description is stale) is updated too, which is how an existing one is adopted."""
    by_id = {f["id"]: f for f in live}
    plan = []
    for f in files:
        existing = by_id.get(f.id)
        if not VALID_ID.fullmatch(f.id):
            plan.append(PlanItem(f, "invalid"))
        elif existing is None:
            plan.append(PlanItem(f, "create"))
        else:
            meta = existing.get("meta") or {}
            same = (
                _norm(existing.get("content")) == _norm(replace_imports(f.content))
                and meta.get("managed_by") == managed_by
                and (meta.get("description") or "") == f.description
                and (meta.get("sources") or {}) == f.sources
            )
            plan.append(PlanItem(f, "unchanged" if same else "update", existing))
    return plan


def plan_prune(
    files: list[FunctionFile], live: list[dict], managed_by: str = MANAGED_BY
) -> list[dict]:
    """Marked functions whose folder is gone."""
    keep = {f.id for f in files}
    return [
        f
        for f in live
        if (f.get("meta") or {}).get("managed_by") == managed_by and f["id"] not in keep
    ]


# ---- deploying ----------------------------------------------------------------


@dataclass
class Result:
    id: str
    file: str
    action: str
    kind: str = "function"
    type: str | None = None
    version: str = ""  # the function's version, from its header
    details: list[str] = field(default_factory=list)  # what changes: versions, tools, skills
    downgrades: list[str] = field(default_factory=list)  # parts older than the live version


# ---- what changes, in versions ------------------------------------------------


def _from_to(old: str, new: str) -> str:
    return f"{old or '(no version)'} -> {new or '(no version)'}"


@dataclass
class Changes:
    """What deploying a function changes: `details` for the report, and `downgrades`, the
    parts whose new version is older than the live one."""

    details: list[str] = field(default_factory=list)
    downgrades: list[str] = field(default_factory=list)

    def version_change(self, label: str, old: str, new: str) -> None:
        if is_older(new, old):
            self.downgrades.append(f"{label} {old} -> {new}")
            self.details.append(f"{label}: {_from_to(old, new)}, OLDER than the live version")
        else:
            self.details.append(f"{label}: {_from_to(old, new)}")


def _parts(changes: Changes, kind: str, old: dict, new: dict, version) -> None:
    """One line per tool (or skill) that is added, removed or changed."""
    for item_id in sorted(set(old) | set(new)):
        a, b = old.get(item_id), new.get(item_id)
        label = f"{kind} `{item_id}`"
        if a is None:
            v = version(b)
            changes.details.append(f"{label}: new{f' ({v})' if v else ''}")
        elif b is None:
            changes.details.append(f"{label}: removed")
        elif not same(a, b):
            va, vb = version(a), version(b)
            if va != vb:
                changes.version_change(label, va, vb)
            else:
                changes.details.append(f"{label}: changed, still {vb or '(no version)'}")


def describe_changes(f: FunctionFile, existing: dict | None, latest: dict[str, str]) -> Changes:
    """What deploying `f` changes, by version: the function, each tool and skill it installs,
    and the commit of the git repository it takes code from. `existing` is the live function
    (with its content), or None; `latest` notes which sources were moved to their latest commit."""
    old = existing.get("content") if existing else None
    changes = Changes()
    old_v, new_v = version_of(old), version_of(f.content)
    if existing is None:
        changes.details.append(f"function: new{f' ({new_v})' if new_v else ''}")
    elif old_v != new_v:
        changes.version_change("function", old_v, new_v)
    elif own_code(old) != own_code(replace_imports(f.content)):
        changes.details.append(f"function: code changed, still {new_v or '(no version)'}")
    _parts(changes, "tool", tools_of(old), tools_of(f.content), tool_version)
    _parts(changes, "skill", skills_of(old), skills_of(f.content), skill_version)
    live_sources = ((existing or {}).get("meta") or {}).get("sources") or {}
    for label, sha in f.sources.items():
        was = live_sources.get(label)
        note = f" ({latest[label]})" if label in latest else ""
        if existing is None:
            changes.details.append(f"source {label}: {sha[:7]}{note}")
        elif was != sha:
            changes.details.append(
                f"source {label}: {was[:7] if was else '(not recorded)'} -> {sha[:7]}{note}"
            )
    return changes


def _with_content(opts: Options, files: list[FunctionFile], live: list[dict]) -> list[dict]:
    """GET /functions/list returns no `content`, so the code comes from
    GET /functions/id/<id>, fetched only for functions that have a folder."""
    wanted = {f.id for f in files}
    out = []
    for fn in live:
        if fn["id"] in wanted:
            full = _call(opts, "GET", f"{API}/id/{fn['id']}")
            fn = {**fn, "content": _field(full, "content")}
        out.append(fn)
    return out


def _ensure_global(opts: Options, fn_id: str, state: Any) -> list[str]:
    """Brings a function declared global to active + global. A toggle is only sent when
    the flag is off, so a run that is already right makes no call."""
    notes = []
    if not _field(state, "is_active"):
        _call(opts, "POST", f"{API}/id/{fn_id}/toggle")
        notes.append("activated")
    if not _field(state, "is_global"):
        _call(opts, "POST", f"{API}/id/{fn_id}/toggle/global")
        notes.append("made global")
    return notes


def _ensure_not_global(opts: Options, fn_id: str, state: Any) -> list[str]:
    """Takes a function declared `global: false` (a toggle) out of global, when it is in."""
    if _field(state, "is_global"):
        _call(opts, "POST", f"{API}/id/{fn_id}/toggle/global")
        return ["made not global"]
    return []


def _deploy_functions(
    opts: Options, files: list[FunctionFile], latest: dict[str, str] | None = None
) -> list[Result]:
    # The list call is also the credential check: a bad key is a 401/403 here, before
    # anything is written. (A missing single function is a 401 too, so it cannot be used
    # to tell "absent" from "unauthorised".)
    live = _call(opts, "GET", f"{API}/list")
    if not isinstance(live, list):
        raise OwppError("GET /functions/list did not return a list")

    bad = [f for f in files if not VALID_ID.fullmatch(f.id)]
    if bad:
        raise OwppError(
            "invalid function id(s): " + ", ".join(f'{f.file} -> "{f.id}"' for f in bad)
        )

    # Refuse a mass delete before writing anything: it points at renamed folders or an
    # emptied one rather than at functions that were really retired.
    managed_by = opts.managed_by
    orphans = (
        [] if opts.only else plan_prune(files, live, managed_by)
    )  # a partial deploy never prunes
    managed = sum(1 for f in live if (f.get("meta") or {}).get("managed_by") == managed_by)
    if len(orphans) > 1 and len(orphans) > managed / 2 and not opts.force_prune:
        raise OwppError(
            f"refusing to delete {len(orphans)} of {managed} git-controlled functions "
            f"({', '.join(o['id'] for o in orphans)}); check the folder names in the plugins "
            "folder (the id is the folder name), or re-run with --force-prune"
        )

    plan = plan_deploy(files, _with_content(opts, files, live), managed_by)
    changes = {p.file.id: describe_changes(p.file, p.existing, latest or {}) for p in plan}
    # Going back a version is refused before anything is written, unless forced.
    older = {i: c.downgrades for i, c in changes.items() if c.downgrades}
    if older and not opts.dry_run and not opts.force:
        raise OwppError(
            "refusing to deploy older versions over newer ones on the instance: "
            + "; ".join(f"{i} ({', '.join(d)})" for i, d in older.items())
            + ". Check you are deploying the right branch, or re-run with --force"
        )
    results: list[Result] = []
    for p in plan:
        f = p.file
        details, downgrades = changes[f.id].details, changes[f.id].downgrades
        version = version_of(f.content)
        if p.action == "unchanged" or opts.dry_run:
            pending = []
            if f.want_global and p.existing:
                if not p.existing.get("is_active"):
                    pending.append("activate")
                if not p.existing.get("is_global"):
                    pending.append("make global")
            if f.not_global and p.existing and p.existing.get("is_global"):
                pending.append("make not global")
            action = p.action
            if opts.dry_run:
                steps = [*([] if p.action == "unchanged" else [p.action]), *pending]
                action = f"would {', '.join(steps)}" if steps else "unchanged"
            elif pending:
                notes = (
                    _ensure_global(opts, f.id, p.existing)
                    if f.want_global
                    else _ensure_not_global(opts, f.id, p.existing)
                )
                action = f"unchanged, {', '.join(notes)}"
            results.append(
                Result(f.id, f.file, action, f.kind, f.type, version, details, downgrades)
            )
            continue

        # An update replaces meta, so it is always sent whole.
        meta: dict = {"description": f.description, "managed_by": managed_by}
        if f.sources:  # the commit it was deployed from, for the next report
            meta["sources"] = f.sources
        form = {"id": f.id, "name": f.name, "content": f.content, "meta": meta}
        if p.action == "update":
            updated = _call(opts, "POST", f"{API}/id/{f.id}/update", form)
            state = updated if updated is not None else p.existing
            notes = (
                _ensure_global(opts, f.id, state)
                if f.want_global
                else _ensure_not_global(opts, f.id, state)
                if f.not_global
                else []
            )
            results.append(
                Result(
                    f.id,
                    f.file,
                    ", ".join(["updated", *notes]),
                    f.kind,
                    f.type,
                    version,
                    details,
                    downgrades,
                )
            )
            continue

        created = _call(opts, "POST", f"{API}/create", form)
        notes = []
        if not _field(created, "is_active"):
            created = _call(opts, "POST", f"{API}/id/{f.id}/toggle")
            notes.append("activated")
        # A new filter is made global (unattached, it does nothing) unless it says
        # `global: false`: a toggle that each user switches on.
        default_global = _field(created, "type") == "filter" and not f.not_global
        if (f.want_global or default_global) and not _field(created, "is_global"):
            _call(opts, "POST", f"{API}/id/{f.id}/toggle/global")
            notes.append("made global")
        results.append(
            Result(f.id, f.file, ", ".join(["created", *notes]), f.kind, f.type, version, details)
        )

    _valves_pass(opts, plan, results)

    for o in orphans:
        if opts.dry_run:
            results.append(Result(o["id"], "(no file)", "would delete"))
            continue
        if _call(opts, "DELETE", f"{API}/id/{o['id']}/delete") is not True:
            raise OwppError(f"deleting {o['id']} was not confirmed")
        results.append(Result(o["id"], "(no file)", "deleted"))
    return results


def _valves_pass(opts: Options, plan: list[PlanItem], results: list[Result]) -> None:
    """A plugin can declare `valves:` for its function. Only the declared keys are written;
    every other valve keeps the value set in the UI. Secrets do not belong here (the file is
    in git): read them from the container environment instead."""
    for p in plan:
        f = p.file
        if not f.valves or not isinstance(f.valves, dict):
            continue
        row = next((r for r in results if r.id == f.id and r.kind == f.kind), None)
        if p.action == "create" and opts.dry_run:
            note = "would set valves"
        else:
            current = _call(opts, "GET", f"{API}/id/{f.id}/valves")
            current = current if isinstance(current, dict) else {}
            differs = any(
                k not in current
                or json.dumps(current[k], sort_keys=True) != json.dumps(v, sort_keys=True)
                for k, v in f.valves.items()
            )
            if not differs:
                continue
            if opts.dry_run:
                note = "would set valves"
            else:
                _call(opts, "POST", f"{API}/id/{f.id}/valves/update", {**current, **f.valves})
                note = "set valves"
        if row:
            row.action = note if row.action == "unchanged" else f"{row.action}, {note}"


def _latest_copy(opts: Options, work: Path) -> tuple[Path, dict[str, str]]:
    """A copy of the plugins folder in `work` with each git-sourced plugin moved to the latest
    commit it tracks, as `owpp sync` would, and {source label: note} for the report."""
    from .bundle import source_label
    from .manifest import read_manifest, read_text, text_of
    from .sources import resolve_ref
    from .sync import rewrite_ref, track_of

    copy = work / opts.dir.name
    shutil.copytree(
        opts.dir, copy, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules")
    )
    notes: dict[str, str] = {}
    for folder in plugin_folders(copy):
        src = read_manifest(folder).get("source")
        if not isinstance(src, dict):
            continue
        track = track_of(folder, src)
        where = "the default branch" if track == "HEAD" else track
        label, pinned = source_label(src), text_of(src.get("ref"))
        sha = (opts.resolve or resolve_ref)(text_of(src.get("git")), track)
        if not sha:
            notes[label] = f"could not look up {where}: the pinned commit"
            continue
        path = folder / "plugin.yaml"
        if sha != pinned:
            path.write_bytes(rewrite_ref(read_text(path), pinned, sha).encode("utf-8"))
        notes[label] = (
            f"latest of {where}; plugin.yaml pins {pinned[:7]}"
            if sha != pinned
            else f"latest of {where}, as pinned"
        )
    return copy, notes


def deploy(opts: Options) -> list[Result]:
    if opts.sync and not opts.dry_run:
        raise OwppError(
            "--sync only goes with --dry-run: to deploy the latest commits, run `owpp sync`, "
            "review and commit the change, then deploy"
        )
    if not opts.sync:
        return _deploy(opts)
    with tempfile.TemporaryDirectory(prefix="owpp-sync-") as work:
        copy, notes = _latest_copy(opts, Path(work))
        return _deploy(replace(opts, dir=copy), notes)


def _deploy(opts: Options, latest: dict[str, str] | None = None) -> list[Result]:
    remote = fetch_sources(source_keys(opts.dir), opts.git_fetcher)
    files = load_function_files(opts.dir, remote)
    if opts.only:
        missing = [i for i in opts.only if not any(f.id == i for f in files)]
        if missing:
            raise OwppError(
                f"--only: no such plugin function {', '.join(missing)} "
                f"(have {', '.join(f.id for f in files)})"
            )
        files = [f for f in files if f.id in opts.only]
    if not files:
        raise OwppError(
            "no functions (plugin folders with a function in plugin.yaml, or *.py files) "
            f"in {opts.dir}"
        )
    return _deploy_functions(opts, files, latest)


def render_report(results: list[Result], dry_run: bool, sync: bool = False) -> str:
    lines = []
    for r in results:
        what = f"{r.type} function" if r.type else r.kind
        unchanged = r.action == "unchanged" and r.version
        action = f"{r.action} ({r.version})" if unchanged else r.action
        lines.append(f"- {what} `{r.id}` ({r.file}): {action}")
        lines += [f"  - {d}" for d in r.details]
    title = "Open-WebUI functions"
    older = [r for r in results if r.downgrades]
    if older:
        forced = any("updated" in r.action for r in older)
        lines += [
            "",
            f"Warning: {len(older)} function(s) would go back a version: "
            + ", ".join(f"`{r.id}` ({', '.join(r.downgrades)})" for r in older)
            + (
                ". Deployed with --force."
                if forced
                else ". The instance has newer versions than this repository: check the branch. "
                "A deploy refuses this without --force."
            ),
        ]
    if dry_run:
        title = f"Dry run{' at the latest commits' if sync else ''}: {title}"
    return f"{title}\n\n" + "\n".join(lines) + "\n"


def run_deploy(opts: Options, env: Mapping[str, str] | None = None) -> int:
    """Health check, deploy, print the report (and append it to the GitHub step summary)."""
    env = os.environ if env is None else env
    if not opts.base_url:
        print(
            "error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, "
            "e.g. https://chat.example.com)",
            file=sys.stderr,
        )
        return 1
    if not opts.api_key:
        print(
            "error: OPEN_WEBUI_API_KEY is not set: create an API key for an admin user in "
            "Open-WebUI (Settings > Account > API keys; the admin setting 'Enable API Keys' "
            "must be on)",
            file=sys.stderr,
        )
        return 1
    try:
        wait_for_health(opts)
        report = render_report(deploy(opts), opts.dry_run, opts.sync)
    except OwppError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"### {report}")
    return 0
