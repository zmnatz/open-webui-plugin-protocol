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
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from .bundle import VALID_ID, FunctionFile, load_function_files
from .errors import OwppError
from .sources import Fetcher, fetch_sources, git_fetcher, source_keys

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
    fetch: Fetch = field(default=urllib_fetch, repr=False)
    git_fetcher: Fetcher = field(default=git_fetcher, repr=False)


def options_from_env(
    env: Mapping[str, str] | None = None,
    *,
    dir: str | os.PathLike | None = None,
    only: str | None = None,
    dry_run: bool = False,
    force_prune: bool = False,
    managed_by: str | None = None,
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


def _deploy_functions(opts: Options, files: list[FunctionFile]) -> list[Result]:
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
    results: list[Result] = []
    for p in plan:
        f = p.file
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
            results.append(Result(f.id, f.file, action, type=f.type))
            continue

        # An update replaces meta, so it is always sent whole.
        form = {
            "id": f.id,
            "name": f.name,
            "content": f.content,
            "meta": {"description": f.description, "managed_by": managed_by},
        }
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
            results.append(Result(f.id, f.file, ", ".join(["updated", *notes]), type=f.type))
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
        results.append(Result(f.id, f.file, ", ".join(["created", *notes]), type=f.type))

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


def deploy(opts: Options) -> list[Result]:
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
    return _deploy_functions(opts, files)


def render_report(results: list[Result], dry_run: bool) -> str:
    lines = [
        f"- {f'{r.type} function' if r.type else r.kind} `{r.id}` ({r.file}): {r.action}"
        for r in results
    ]
    return f"{'Dry run: ' if dry_run else ''}Open-WebUI functions\n\n" + "\n".join(lines) + "\n"


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
        report = render_report(deploy(opts), opts.dry_run)
    except OwppError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"### {report}")
    return 0
