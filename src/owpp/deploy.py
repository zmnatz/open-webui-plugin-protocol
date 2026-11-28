"""Deploys a folder of Open-WebUI plugins into a running Open-WebUI through its admin API
(docs/commands/deploy.md). Normally run through the CLI (`owpp deploy`).

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

Two inputs, kept apart: an Instance (where Open-WebUI is and how to sign in to it: the URL,
the credentials, TLS and the HTTP adapter) and the Choices (what to deploy and how: the
plugins folder or a build, --only, --dry-run, the prune flags, the ownership marker).
plugins_for(choices) needs no instance; deploy(instance, choices) and
iframe_sandbox_warning(instance, plugins) use the same signed-in Instance.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import ssl
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .build import Build, read_build
from .bundle import VALID_ID, FunctionFile, load_function_files
from .errors import OwppError
from .manifest import plugin_folders, read_manifest
from .openwebui import (
    MANAGED_BY,
    Fetch,
    FunctionMeta,
    OpenWebUI,
    SignInRefused,
    field_of,
    replace_imports,
    urllib_fetch,
)
from .sources import Sources
from .versioning import (
    is_older,
    norm,
    own_code,
    same,
    skill_version,
    skills_of,
    tool_version,
    tools_of,
    version_of,
)

# ---- TLS: a CA to trust, a client certificate to present ------------------------


def _is_pem(value: str) -> bool:
    return "-----BEGIN " in value


def _pem_file(value: str, label: str, work: Path) -> str:
    """A PEM given as a path, or as its text (then written to a private file in `work`)."""
    if _is_pem(value):
        path = work / f"{label}.pem"
        path.touch(mode=0o600)
        path.write_text(value if value.endswith("\n") else value + "\n")
        return str(path)
    if not Path(value).expanduser().is_file():
        raise OwppError(f"{label}: no file {value} (give a path to a PEM file, or the PEM itself)")
    return str(Path(value).expanduser())


def tls_context(
    ca_cert: str = "", client_cert: str = "", client_key: str = ""
) -> ssl.SSLContext | None:
    """The TLS settings for talking to Open-WebUI, or None for Python's defaults.

    `ca_cert`: certificates to trust besides the system's (a private CA, or a self-signed
    server). `client_cert` (and `client_key`, when the key is not in the same PEM): the
    certificate to present to a server or proxy that asks for one (mutual TLS). Each is a path
    to a PEM file, or the PEM text itself (as a CI secret holds it)."""
    if not (ca_cert or client_cert or client_key):
        return None
    if client_key and not client_cert:
        raise OwppError("OPEN_WEBUI_CLIENT_KEY needs OPEN_WEBUI_CLIENT_CERT")
    context = ssl.create_default_context()  # the system's CAs, and verification on
    try:
        if ca_cert:
            if _is_pem(ca_cert):
                context.load_verify_locations(cadata=ca_cert)
            else:
                context.load_verify_locations(
                    cafile=_pem_file(ca_cert, "OPEN_WEBUI_CA_CERT", Path())
                )
        if client_cert:
            with tempfile.TemporaryDirectory(prefix="owpp-tls-") as work:
                cert = _pem_file(client_cert, "OPEN_WEBUI_CLIENT_CERT", Path(work))
                key = (
                    _pem_file(client_key, "OPEN_WEBUI_CLIENT_KEY", Path(work))
                    if client_key
                    else None
                )
                context.load_cert_chain(cert, key)  # read now: the files can go
    except ssl.SSLError as e:
        raise OwppError(f"a certificate could not be loaded: {e}") from e
    return context


@dataclass
class Instance:
    """How to reach and sign in to an Open-WebUI: its URL, the credentials, TLS, and the HTTP
    adapter every call goes through. sign_in() replaces the credentials with a session."""

    base_url: str
    # An API key, or the session token signing in gave; empty: sign in first. Never shown.
    api_key: str = field(default="", repr=False)
    # Without an API key, the deploy signs in (sign_in): with a user name (an email, or an LDAP
    # user) and a password, with an OIDC token for an OAuth provider, or with nothing at all.
    username: str = ""
    password: str = field(default="", repr=False)
    oidc_token: str = field(default="", repr=False)
    oauth_provider: str = "oidc"
    # TLS (tls_context): a CA to trust, a client certificate (and key) to present.
    ca_cert: str = field(default="", repr=False)
    client_cert: str = field(default="", repr=False)
    client_key: str = field(default="", repr=False)
    fetch: Fetch = field(default=urllib_fetch, repr=False)

    def __post_init__(self) -> None:
        context = tls_context(self.ca_cert, self.client_cert, self.client_key)
        if context is not None and self.fetch is urllib_fetch:
            self.fetch = functools.partial(urllib_fetch, context=context)

    @property
    def open_webui(self) -> OpenWebUI:
        """The instance's API, as the account the API key (or the session) belongs to."""
        return OpenWebUI(self.base_url, self.fetch, self.api_key)


@dataclass
class Choices:
    """What to deploy, and how: the plugins (a folder, or a build), and the deploy's flags."""

    dir: Path = field(default_factory=lambda: Path("plugins"))
    # Deploy the build in this folder (`owpp build`) instead of bundling the plugins folder.
    from_dir: Path | None = None
    only: list[str] | None = None
    dry_run: bool = False
    # With dry_run: report against the latest commit each git-sourced plugin follows, not the
    # pinned one (as if `owpp pull` had run), without changing plugin.yaml.
    latest: bool = False
    # Deploy even where the live version is newer than the repository's (a downgrade).
    force: bool = False
    force_prune: bool = False
    # Create and update, but delete nothing: the functions a full deploy would prune are listed.
    no_prune: bool = False
    managed_by: str = MANAGED_BY
    # What the deploy reads plugin files from git through, and looks up the latest commits with.
    sources: Sources = field(default_factory=Sources, repr=False)


def instance_from_env(
    env: Mapping[str, str] | None = None,
    *,
    ca_cert: str | None = None,
    client_cert: str | None = None,
    client_key: str | None = None,
) -> Instance:
    """The instance and the credentials, from the environment (OPEN_WEBUI_*); a certificate
    flag wins over its variable."""
    env = os.environ if env is None else env
    return Instance(
        base_url=env.get("OPEN_WEBUI_URL", "").rstrip("/"),
        api_key=env.get("OPEN_WEBUI_API_KEY", ""),
        username=env.get("OPEN_WEBUI_USERNAME", ""),
        password=env.get("OPEN_WEBUI_PASSWORD", ""),
        oidc_token=env.get("OPEN_WEBUI_OIDC_TOKEN", ""),
        oauth_provider=env.get("OPEN_WEBUI_OAUTH_PROVIDER", "") or "oidc",
        ca_cert=ca_cert or env.get("OPEN_WEBUI_CA_CERT", ""),
        client_cert=client_cert or env.get("OPEN_WEBUI_CLIENT_CERT", ""),
        client_key=client_key or env.get("OPEN_WEBUI_CLIENT_KEY", ""),
    )


def choices_from_env(
    env: Mapping[str, str] | None = None,
    *,
    dir: str | os.PathLike | None = None,
    only: str | None = None,
    sources: Sources | None = None,
    from_dir: str | os.PathLike | None = None,
    managed_by: str | None = None,
    **flags: bool,
) -> Choices:
    """The deploy's choices: flags win over the environment (OWPP_*), which wins over the
    defaults. `flags` are Choices' booleans (dry_run, latest, force, force_prune, no_prune)."""
    env = os.environ if env is None else env
    return Choices(
        dir=Path(dir or env.get("OWPP_PLUGINS_DIR") or "plugins").resolve(),
        from_dir=Path(from_dir).resolve() if from_dir else None,
        only=[i for i in only.split(",") if i] if only else None,
        managed_by=managed_by or env.get("OWPP_MANAGED_BY") or MANAGED_BY,
        **flags,
        **({"sources": sources} if sources is not None else {}),
    )


# ---- signing in ---------------------------------------------------------------

IFRAME_REQUIREMENT = "iframe_sandbox_allow_same_origin"
IFRAME_SETTING = "iframeSandboxAllowSameOrigin"
IFRAME_FIX = "DEFAULT_INTERFACE_SETTINGS='{\"iframeSandboxAllowSameOrigin\": true}'"


def sign_in(instance: Instance) -> str:
    """The credential the deploy uses, and how it was obtained. An API key is used as it is.
    Otherwise it signs in, as the person opening Open-WebUI would, and uses the session token:

    - a user name and password: Open-WebUI's own accounts (the user name is the email), then,
      if that fails, LDAP;
    - an OIDC token: exchanged at /oauth/<provider>/token/exchange, which the instance must
      allow (ENABLE_OAUTH_TOKEN_EXCHANGE=true);
    - nothing: an empty sign-in, which Open-WebUI answers when sign-in is switched off
      (WEBUI_AUTH=False) or a proxy in front of it adds the trusted email header.

    The account must be an admin. Sets instance.api_key; raises OwppError when it cannot sign in."""
    if instance.api_key:
        return "an API key"
    if bool(instance.username) != bool(instance.password):
        raise OwppError("OPEN_WEBUI_USERNAME and OPEN_WEBUI_PASSWORD go together: set both")
    api = instance.open_webui
    if instance.username:
        how = f"user {instance.username}"
        try:
            result = api.sign_in(instance.username, instance.password)
        except SignInRefused as why:
            try:
                result = api.sign_in_ldap(instance.username, instance.password)
            except SignInRefused as ldap_why:
                raise OwppError(
                    f"could not sign in as {instance.username}: with a password ({why}), "
                    f"with LDAP ({ldap_why})"
                ) from None
            how = f"LDAP user {instance.username}"
    elif instance.oidc_token:
        provider = instance.oauth_provider.strip().lower()
        if not VALID_ID.fullmatch(provider.replace("-", "_")):
            raise OwppError(f"OPEN_WEBUI_OAUTH_PROVIDER {provider!r} is not a provider name")
        how = f"an OIDC token ({provider})"
        try:
            result = api.exchange_oidc(provider, instance.oidc_token)
        except SignInRefused as why:
            raise OwppError(
                f"could not exchange the OIDC token with provider {provider} ({why}). The "
                "instance must set ENABLE_OAUTH_TOKEN_EXCHANGE=true and have that provider "
                "configured; set OPEN_WEBUI_OAUTH_PROVIDER if it is not called oidc"
            ) from None
    else:
        how = "an open sign-in"
        try:
            result = api.sign_in("", "")
        except SignInRefused as why:
            raise OwppError(
                f"no credentials, and Open-WebUI did not sign in without them ({why}). Set "
                "OPEN_WEBUI_API_KEY (an admin's API key), OPEN_WEBUI_USERNAME and "
                "OPEN_WEBUI_PASSWORD, or OPEN_WEBUI_OIDC_TOKEN"
            ) from None
    role = result.get("role")
    if role is not None and role != "admin":
        who = result.get("email") or result.get("name") or "that account"
        raise OwppError(f"signed in with {how} as {who}, who is not an admin (role {role})")
    instance.api_key = str(result["token"])
    return how


# ---- planning -----------------------------------------------------------------


@dataclass
class PlanItem:
    file: FunctionFile
    action: str  # create | update | unchanged | invalid
    existing: dict | None = None


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
            meta = FunctionMeta.of(existing)
            same = (
                norm(existing.get("content")) == norm(replace_imports(f.content))
                and meta.managed_by == managed_by
                and meta.description == f.description
                and meta.sources == f.sources
                and (meta.requires or {}) == f.requires
            )
            plan.append(PlanItem(f, "unchanged" if same else "update", existing))
    return plan


def plan_prune(
    files: list[FunctionFile], live: list[dict], managed_by: str = MANAGED_BY
) -> list[dict]:
    """Marked functions whose folder is gone."""
    keep = {f.id for f in files}
    return [f for f in live if FunctionMeta.of(f).managed_by == managed_by and f["id"] not in keep]


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
    live_sources = FunctionMeta.of(existing).sources
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


def _with_content(instance: Instance, files: list[FunctionFile], live: list[dict]) -> list[dict]:
    """GET /functions/list returns no `content`, so the code comes from
    GET /functions/id/<id>, fetched only for functions that have a folder."""
    wanted = {f.id for f in files}
    out = []
    for fn in live:
        if fn["id"] in wanted:
            fn = {**fn, "content": field_of(instance.open_webui.function(fn["id"]), "content")}
        out.append(fn)
    return out


def _ensure_global(instance: Instance, fn_id: str, state: Any) -> list[str]:
    """Brings a function declared global to active + global. A toggle is only sent when
    the flag is off, so a run that is already right makes no call."""
    notes = []
    if not field_of(state, "is_active"):
        instance.open_webui.toggle(fn_id)
        notes.append("activated")
    if not field_of(state, "is_global"):
        instance.open_webui.toggle_global(fn_id)
        notes.append("made global")
    return notes


def _ensure_not_global(instance: Instance, fn_id: str, state: Any) -> list[str]:
    """Takes a function declared `global: false` (a toggle) out of global, when it is in."""
    if field_of(state, "is_global"):
        instance.open_webui.toggle_global(fn_id)
        return ["made not global"]
    return []


def _deploy_functions(instance: Instance, choices: Choices, plugins: Build) -> list[Result]:
    files, latest = plugins.files, plugins.latest
    # The list call is also the credential check: a bad key is a 401/403 here, before
    # anything is written. (A missing single function is a 401 too, so it cannot be used
    # to tell "absent" from "unauthorised".)
    api = instance.open_webui
    live = api.functions()

    bad = [f for f in files if not VALID_ID.fullmatch(f.id)]
    if bad:
        raise OwppError(
            "invalid function id(s): " + ", ".join(f'{f.file} -> "{f.id}"' for f in bad)
        )

    # Refuse a mass delete before writing anything: it points at renamed folders or an
    # emptied one rather than at functions that were really retired.
    managed_by = choices.managed_by
    # Only a deploy of every plugin prunes: --only, or a partial build, never does.
    pruned = plan_prune(files, live, managed_by) if plugins.complete and not choices.only else []
    orphans = [] if choices.no_prune else pruned
    managed = sum(1 for f in live if FunctionMeta.of(f).managed_by == managed_by)
    if len(orphans) > 1 and len(orphans) > managed / 2 and not choices.force_prune:
        raise OwppError(
            f"refusing to delete {len(orphans)} of {managed} git-controlled functions "
            f"({', '.join(o['id'] for o in orphans)}); check the folder names in the plugins "
            "folder (the id is the folder name), or re-run with --force-prune"
        )

    plan = plan_deploy(files, _with_content(instance, files, live), managed_by)
    changes = {p.file.id: describe_changes(p.file, p.existing, latest) for p in plan}
    # Going back a version is refused before anything is written, unless forced.
    older = {i: c.downgrades for i, c in changes.items() if c.downgrades}
    if older and not choices.dry_run and not choices.force:
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
        if p.action == "unchanged" or choices.dry_run:
            pending = []
            if f.want_global and p.existing:
                if not p.existing.get("is_active"):
                    pending.append("activate")
                if not p.existing.get("is_global"):
                    pending.append("make global")
            if f.not_global and p.existing and p.existing.get("is_global"):
                pending.append("make not global")
            action = p.action
            if choices.dry_run:
                steps = [*([] if p.action == "unchanged" else [p.action]), *pending]
                action = f"would {', '.join(steps)}" if steps else "unchanged"
            elif pending:
                notes = (
                    _ensure_global(instance, f.id, p.existing)
                    if f.want_global
                    else _ensure_not_global(instance, f.id, p.existing)
                )
                action = f"unchanged, {', '.join(notes)}"
            results.append(
                Result(f.id, f.file, action, f.kind, f.type, version, details, downgrades)
            )
            continue

        # The commit it was deployed from, for the next report; what plugin.yaml requires of
        # the instance, for `owpp import --instance`. A function stored without `requires` is
        # not updated for it: a missing one counts as {} above.
        meta = FunctionMeta(managed_by, f.description, f.sources, f.requires)
        if p.action == "update":
            updated = api.update_function(f.id, f.name, f.content, meta)
            state = updated if updated is not None else p.existing
            notes = (
                _ensure_global(instance, f.id, state)
                if f.want_global
                else _ensure_not_global(instance, f.id, state)
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

        created = api.create_function(f.id, f.name, f.content, meta)
        notes = []
        if not field_of(created, "is_active"):
            created = api.toggle(f.id)
            notes.append("activated")
        # A new filter is made global (unattached, it does nothing) unless it says
        # `global: false`: a toggle that each user switches on.
        default_global = field_of(created, "type") == "filter" and not f.not_global
        if (f.want_global or default_global) and not field_of(created, "is_global"):
            api.toggle_global(f.id)
            notes.append("made global")
        results.append(
            Result(f.id, f.file, ", ".join(["created", *notes]), f.kind, f.type, version, details)
        )

    _valves_pass(instance, choices, plan, results)

    for o in orphans:
        if choices.dry_run:
            results.append(Result(o["id"], "(no file)", "would delete"))
            continue
        api.delete_function(o["id"])
        results.append(Result(o["id"], "(no file)", "deleted"))
    if choices.no_prune:
        for o in pruned:
            results.append(Result(o["id"], "(no file)", "not deleted (--no-prune)"))
    return results


def _valves_pass(
    instance: Instance, choices: Choices, plan: list[PlanItem], results: list[Result]
) -> None:
    """A plugin can declare `valves:` for its function. Only the declared keys are written;
    every other valve keeps the value set in the UI. Secrets do not belong here (the file is
    in git): read them from the container environment instead."""
    for p in plan:
        f = p.file
        if not f.valves or not isinstance(f.valves, dict):
            continue
        row = next((r for r in results if r.id == f.id and r.kind == f.kind), None)
        if p.action == "create" and choices.dry_run:
            note = "would set valves"
        else:
            current = instance.open_webui.valves(f.id)
            differs = any(
                k not in current
                or json.dumps(current[k], sort_keys=True) != json.dumps(v, sort_keys=True)
                for k, v in f.valves.items()
            )
            if not differs:
                continue
            if choices.dry_run:
                note = "would set valves"
            else:
                instance.open_webui.update_valves(f.id, {**current, **f.valves})
                note = "set valves"
        if row:
            row.action = note if row.action == "unchanged" else f"{row.action}, {note}"


def latest_copy(directory: Path, sources: Sources, work: Path) -> tuple[Path, dict[str, str]]:
    """A copy of the plugins folder in `work` with each git-sourced plugin moved to the latest
    commit it tracks, as `owpp pull` would, and {source label: note} for the report."""
    from .manifest import read_text, set_key, text_of
    from .pull import followed
    from .sources import source_label

    copy = work / directory.name
    shutil.copytree(
        directory, copy, symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules")
    )
    notes: dict[str, str] = {}
    for folder in plugin_folders(copy):
        src = read_manifest(folder).get("source")
        if not isinstance(src, dict):
            continue
        ref, where = followed(folder)
        where = "the default branch" if where == "default branch" else where
        label, pinned = source_label(src), text_of(src.get("ref"))
        sha = sources.latest(text_of(src.get("git")), ref)
        if not sha:
            notes[label] = f"could not look up {where}: the pinned commit"
            continue
        path = folder / "plugin.yaml"
        if sha != pinned:
            text = set_key(read_text(path), "source.ref", sha, after="git")
            path.write_bytes(text.encode("utf-8"))
        notes[label] = (
            f"latest of {where}; plugin.yaml pins nothing yet"
            if not pinned
            else f"latest of {where}; plugin.yaml pins {pinned[:7]}"
            if sha != pinned
            else f"latest of {where}, as pinned"
        )
    return copy, notes


def plugins_for(choices: Choices) -> Build:
    """What the deploy writes: the build in `--from`, or the plugins folder bundled now (at the
    latest commits with `--latest`), narrowed to `--only`."""
    if choices.latest and not choices.dry_run:
        raise OwppError(
            "--latest only goes with --dry-run: to deploy the latest commits, run `owpp pull`, "
            "review and commit the change, then deploy"
        )
    if choices.from_dir is not None:
        if choices.latest:
            raise OwppError(
                "--latest needs the sources, which a build does not have: build it with "
                "`owpp build --latest`, then deploy that with --dry-run"
            )
        plugins = read_build(choices.from_dir)
        if plugins.latest and not choices.dry_run:
            raise OwppError(
                f"{choices.from_dir} was built at the latest commits (`owpp build --latest`), so it "
                "only deploys as a dry run: run `owpp pull`, review and commit the change, then build"
            )
        where = f"the build in {choices.from_dir}"
    else:
        plugins = build_plugins(choices.dir, choices.sources, latest=choices.latest)
        where = str(choices.dir)
    if choices.only:
        missing = [i for i in choices.only if not any(f.id == i for f in plugins.files)]
        if missing:
            raise OwppError(
                f"--only: no such plugin function {', '.join(missing)} "
                f"(have {', '.join(f.id for f in plugins.files)})"
            )
        plugins = replace(plugins, files=[f for f in plugins.files if f.id in choices.only])
    if not plugins.files:
        raise OwppError(
            "no functions (plugin folders with a function in plugin.yaml, or *.py files) "
            f"in {where}"
        )
    return plugins


def build_plugins(
    directory: Path, sources: Sources, ids: list[str] | None = None, latest: bool = False
) -> Build:
    """Every plugin in `directory` bundled (or only `ids`, a partial build), at the pinned
    commits, or with `latest` at the latest commit each git-sourced plugin follows."""
    if not latest:
        files, notes = load_function_files(directory, sources), {}
    else:
        with tempfile.TemporaryDirectory(prefix="owpp-latest-") as work:
            copy, notes = latest_copy(directory, sources, Path(work))
            files = load_function_files(copy, sources)
    if ids:
        missing = [i for i in ids if not any(f.id == i for f in files)]
        if missing:
            raise OwppError(f"no plugin {', '.join(missing)} in {directory}")
        files = [f for f in files if f.id in ids]
    return Build(files, complete=not ids, latest=notes)


def deploy(instance: Instance, choices: Choices, plugins: Build | None = None) -> list[Result]:
    """Deploy `plugins` (by default: plugins_for(choices)) to the signed-in `instance`, and
    report what changed."""
    return _deploy_functions(
        instance, choices, plugins if plugins is not None else plugins_for(choices)
    )


def iframe_sandbox_warning(instance: Instance, plugins: Build) -> str | None:
    """Warn when a plugin needs Open-WebUI's iframe Sandbox Allow Same Origin but the instance's
    default interface settings do not turn it on. Never changes the instance or stops a deploy:
    a user's own setting can still enable it. The deploy signs in as an admin, who can always
    read the admin config."""
    ids = [f.id for f in plugins.files if f.requires.get(IFRAME_REQUIREMENT) is True]
    if not ids:
        return None
    config = instance.open_webui.admin_config()
    if (config.get("DEFAULT_INTERFACE_SETTINGS") or {}).get(IFRAME_SETTING) is True:
        return None
    return (
        f"Warning: {', '.join(f'`{i}`' for i in ids)} need Open-WebUI's iframe Sandbox Allow Same "
        "Origin, and it is not on in this instance's default interface settings. Set it with "
        f"{IFRAME_FIX} or under Admin Settings > General > "
        "Default Interface Settings (each user can also turn it on in Settings > Interface). "
        "Deploying anyway."
    )


def render_report(
    results: list[Result], dry_run: bool, latest: bool = False, warnings: list[str] | None = None
) -> str:
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
    extra = [w for w in (warnings or []) if w]
    if extra:
        lines += ["", *extra]
    if dry_run:
        title = f"Dry run{' at the latest commits' if latest else ''}: {title}"
    return f"{title}\n\n" + "\n".join(lines) + "\n"


def run_deploy(instance: Instance, choices: Choices, env: Mapping[str, str] | None = None) -> int:
    """Health check, sign in, deploy, print the report (and append it to the GitHub step
    summary)."""
    env = os.environ if env is None else env
    if not instance.base_url:
        print(
            "error: OPEN_WEBUI_URL is not set (the base URL of your Open-WebUI, "
            "e.g. https://chat.example.com)",
            file=sys.stderr,
        )
        return 1
    try:
        with choices.sources:  # its upstream copies are deleted once the deploy is done
            instance.open_webui.wait_for_health()
            how = sign_in(instance)
            plugins = plugins_for(choices)
            warning = iframe_sandbox_warning(instance, plugins)  # before writing, never a refusal
            latest = choices.latest or bool(plugins.latest)
            results = deploy(instance, choices, plugins)
            report = render_report(results, choices.dry_run, latest, [warning])
    except OwppError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"(signed in with {how})\n")
    print(report)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"### {report}")
    return 0
