# Open-WebUI Event function: a read-only dashboard of chats, notes and files older than
# a threshold, served at DASHBOARD_PATH (default /stale-data) for admins. It mounts
# through the `routes` library (plugin.yaml: include), which replaces its own earlier
# routes on every load and keeps them ahead of the SPA catch-all.

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


_INDEX = plugin_template_text("index.html")  # templates/index.html, filled in per request below


def _fmt_ts(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M:%S")


def _fmt_age(epoch_seconds: float, now_ts: float) -> str:
    delta = max(0.0, now_ts - epoch_seconds)
    if delta >= 86400 * 30:
        return f"{delta / (86400 * 30):.0f} mo"
    if delta >= 86400:
        return f"{delta / 86400:.0f} d"
    if delta >= 3600:
        return f"{delta / 3600:.0f} h"
    return f"{delta / 60:.0f} m"


def _fmt_size(num: Any) -> str:
    if not num:
        return "—"
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return "—"


def _flags(*pairs: tuple) -> str:
    on = [label for label, flag in pairs if flag]
    return ", ".join(on) if on else "—"


def _message_count(chat_json: Any) -> int:
    if not isinstance(chat_json, dict):
        return 0
    history = chat_json.get("history")
    if isinstance(history, dict) and isinstance(history.get("messages"), dict):
        return len(history["messages"])
    top = chat_json.get("messages")
    if isinstance(top, (dict, list)):
        return len(top)
    return 0


def _note_markdown(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if isinstance(content, dict) and isinstance(content.get("md"), str):
        return content["md"]
    return ""


def _dashboard_html(payload: dict[str, Any]) -> str:
    cutoff_date = payload.get("cutoff_date")
    stale_chats = payload.get("chats", [])
    stale_notes = payload.get("notes", [])
    stale_files = payload.get("files", [])
    error_msg = payload.get("error")
    threshold = payload.get("threshold_hours")
    scanned = payload.get("scanned", {})

    error_banner = (
        f"<div style='background: #7f1d1d; color: #fca5a5; padding: 12px; border-radius: 6px; margin-bottom: 20px;'><strong>Debug Error:</strong> {html.escape(error_msg)}</div>"
        if error_msg
        else ""
    )

    scan_line = (
        f"Scanned {scanned.get('chats', 0)} chat(s), "
        f"{scanned.get('notes', 0)} note(s), {scanned.get('files', 0)} file(s)."
    )

    def esc(value: Any) -> str:
        return html.escape(str(value)) if value not in (None, "") else "—"

    def td(value: Any, full: Any = None, cls: str = "") -> str:
        cls_attr = f" class='{cls}'" if cls else ""
        title_src = full if full not in (None, "") else value
        title_attr = (
            f" title='{html.escape(str(title_src))}'"
            if title_src not in (None, "")
            else ""
        )
        return f"<td{cls_attr}{title_attr}>{esc(value)}</td>"

    def td_html(content: str, full: Any = None, cls: str = "") -> str:
        cls_attr = f" class='{cls}'" if cls else ""
        title_attr = (
            f" title='{html.escape(str(full))}'" if full not in (None, "") else ""
        )
        return f"<td{cls_attr}{title_attr}>{content}</td>"

    def chat_row(c: dict) -> str:
        title = c.get("title") or "Untitled Chat"
        link = f"<a href='/c/{c.get('id')}' target='_blank'>{html.escape(title)}</a>"
        return (
            "<tr>"
            + td_html(link, title, cls="id")
            + td(c.get("owner"))
            + td(c.get("messages", 0))
            + td(c.get("flags"))
            + td(c.get("created_at"))
            + td(c.get("updated_at"))
            + td(c.get("age"))
            + "</tr>"
        )

    def note_row(n: dict) -> str:
        title = n.get("title") or "Untitled Note"
        link = f"<a href='/n/{n.get('id')}' target='_blank'>{html.escape(title)}</a>"
        return (
            "<tr>"
            + td_html(link, title, cls="id")
            + td(n.get("owner"))
            + td(n.get("preview"))
            + td(n.get("chars", 0))
            + td(n.get("flags"))
            + td(n.get("created_at"))
            + td(n.get("updated_at"))
            + td(n.get("age"))
            + "</tr>"
        )

    def file_row(f: dict) -> str:
        fname = f.get("filename") or "Unnamed File"
        link = f"<a href='/api/v1/files/{f.get('id')}/content' target='_blank'>{html.escape(fname)}</a>"
        chats = f.get("chats") or []
        chat_titles = [c.get("title") or "Untitled Chat" for c in chats]
        chat_full = ", ".join(chat_titles) if chat_titles else None
        chat_html = (
            ", ".join(
                f"<a href='/c/{c.get('id')}' target='_blank'>{html.escape(t)}</a>"
                for c, t in zip(chats, chat_titles)
            )
            or "<span class='unk'>—</span>"
        )
        return (
            "<tr>"
            + td_html(link, fname, cls="id")
            + td_html(chat_html, chat_full, cls="id")
            + td(f.get("owner"))
            + td(f.get("size"))
            + td(f.get("content_type"))
            + td(f.get("path"))
            + td(f.get("hash"))
            + td(f.get("created_at"))
            + td(f.get("age"))
            + "</tr>"
        )

    chats_rows = (
        "".join(chat_row(c) for c in stale_chats)
        or "<tr><td colspan='7' class='unk'>No stale chats found! Yahoo!</td></tr>"
    )

    notes_rows = (
        "".join(note_row(n) for n in stale_notes)
        or "<tr><td colspan='8' class='unk'>No stale notes found!</td></tr>"
    )

    files_rows = (
        "".join(file_row(f) for f in stale_files)
        or "<tr><td colspan='9' class='unk'>No stale files found!</td></tr>"
    )

    values = {
        "THRESHOLD": str(threshold),
        "CUTOFF": html.escape(cutoff_date or ""),
        "SCAN": scan_line,
        "ERROR": error_banner,
        "N_CHATS": str(len(stale_chats)),
        "N_NOTES": str(len(stale_notes)),
        "N_FILES": str(len(stale_files)),
        "CHATS_ROWS": chats_rows,
        "NOTES_ROWS": notes_rows,
        "FILES_ROWS": files_rows,
    }
    # One pass, so text inside a value (a chat titled "__N_NOTES__") is never filled in.
    return re.sub(r"__([A-Z_]+)__", lambda m: values.get(m.group(1), m.group(0)), _INDEX)


def _epoch_seconds(value: Any) -> float:
    """Normalize an Open-WebUI epoch timestamp to seconds.

    Chats/files store ``int(time.time())`` (seconds), but notes store
    ``int(time.time_ns())`` (nanoseconds), and some callers have used
    milliseconds/microseconds. Detect by magnitude.
    """
    value = float(value or 0)
    if value > 1e17:
        return value / 1e9
    if value > 1e14:
        return value / 1e6
    if value > 1e12:
        return value / 1e3
    return value


async def _paginated(fetch, page_size: int = 500) -> list:
    items, seen, skip = [], set(), 0
    while True:
        batch = await fetch(skip=skip, limit=page_size)
        fresh = [i for i in batch if i.id not in seen]
        if not fresh:
            break
        items.extend(fresh)
        seen.update(i.id for i in fresh)
        if len(batch) < page_size:
            break
        skip += len(batch)
    return items


async def _file_chat_map() -> dict[str, list[str]]:
    """Map file_id -> [chat_id] using the ``chat_file`` join table."""
    from sqlalchemy import select

    from open_webui.internal.db import get_async_db_context
    from open_webui.models.chats import ChatFile

    mapping: dict[str, list[str]] = {}
    async with get_async_db_context() as db:
        result = await db.execute(select(ChatFile.file_id, ChatFile.chat_id))
        for file_id, chat_id in result.all():
            chat_ids = mapping.setdefault(file_id, [])
            if chat_id not in chat_ids:
                chat_ids.append(chat_id)
    return mapping


def _file_chat_map_from_chats(raw_chats: list) -> dict[str, list[str]]:
    """Fallback: derive file -> chat links by scanning message ``files`` lists."""
    mapping: dict[str, list[str]] = {}
    for c in raw_chats:
        chat = getattr(c, "chat", None)
        if not isinstance(chat, dict):
            continue
        messages = []
        history = chat.get("history")
        if isinstance(history, dict) and isinstance(history.get("messages"), dict):
            messages.extend(history["messages"].values())
        top = chat.get("messages")
        if isinstance(top, dict):
            messages.extend(top.values())
        elif isinstance(top, list):
            messages.extend(top)
        for m in messages:
            if not isinstance(m, dict):
                continue
            for fl in m.get("files") or []:
                if isinstance(fl, dict) and fl.get("id"):
                    chat_ids = mapping.setdefault(fl["id"], [])
                    if c.id not in chat_ids:
                        chat_ids.append(c.id)
    return mapping


async def _user_map(user_ids: set) -> dict[str, str]:
    """Resolve user_ids -> display name (or email/id) in one batched query."""
    from open_webui.models.users import Users

    ids = [uid for uid in user_ids if uid]
    if not ids:
        return {}

    def display(u: Any) -> str:
        return (
            getattr(u, "name", None)
            or getattr(u, "email", None)
            or getattr(u, "id", "")
        )

    try:
        result = await Users.get_users(filter={"user_ids": ids}, limit=len(ids))
        users = result.get("users", []) if isinstance(result, dict) else (result or [])
        return {u.id: display(u) for u in users}
    except Exception:
        out: dict[str, str] = {}
        for uid in ids:
            try:
                u = await Users.get_user_by_id(uid)
                if u:
                    out[uid] = display(u)
            except Exception:
                pass
        return out


async def _load_stale_data(stale_hours: int) -> dict[str, Any]:
    cutoff_date = datetime.now() - timedelta(hours=stale_hours)
    cutoff_timestamp = int(cutoff_date.timestamp())
    now_ts = datetime.now().timestamp()

    stale_chats, stale_notes, stale_files = [], [], []
    scanned = {"chats": 0, "notes": 0, "files": 0}
    error_str = None

    try:
        from open_webui.models.chats import Chats
        from open_webui.models.files import Files
        from open_webui.models.notes import Notes

        raw_chats = await _paginated(Chats.get_chats)
        raw_notes = await _paginated(Notes.get_notes)
        raw_files = await Files.get_files()
        scanned = {
            "chats": len(raw_chats),
            "notes": len(raw_notes),
            "files": len(raw_files),
        }

        chat_titles = {c.id: c.title for c in raw_chats}
        try:
            file_chats = await _file_chat_map()
        except Exception:
            file_chats = _file_chat_map_from_chats(raw_chats)

        for c in raw_chats:
            updated = _epoch_seconds(c.updated_at)
            if updated < cutoff_timestamp:
                stale_chats.append(
                    {
                        "id": c.id,
                        "title": c.title,
                        "user_id": c.user_id,
                        "messages": _message_count(c.chat),
                        "flags": _flags(
                            ("pinned", c.pinned),
                            ("archived", c.archived),
                            ("shared", bool(c.share_id)),
                        ),
                        "created_at": _fmt_ts(_epoch_seconds(c.created_at)),
                        "updated_at": _fmt_ts(updated),
                        "age": _fmt_age(updated, now_ts),
                    }
                )

        for n in raw_notes:
            updated = _epoch_seconds(n.updated_at)
            if updated < cutoff_timestamp:
                md = _note_markdown(n.data)
                stale_notes.append(
                    {
                        "id": n.id,
                        "title": n.title,
                        "user_id": n.user_id,
                        "preview": md,
                        "chars": len(md),
                        "flags": _flags(
                            ("pinned", n.is_pinned),
                            ("shared", bool(n.access_grants)),
                        ),
                        "created_at": _fmt_ts(_epoch_seconds(n.created_at)),
                        "updated_at": _fmt_ts(updated),
                        "age": _fmt_age(updated, now_ts),
                    }
                )

        for f in raw_files:
            created = _epoch_seconds(f.created_at)
            if created < cutoff_timestamp:
                meta = f.meta if isinstance(f.meta, dict) else {}
                chat_ids = file_chats.get(f.id, [])
                stale_files.append(
                    {
                        "id": f.id,
                        "filename": f.filename,
                        "user_id": f.user_id,
                        "chats": [
                            {"id": cid, "title": chat_titles.get(cid, cid)}
                            for cid in chat_ids
                        ],
                        "size": _fmt_size(meta.get("size")),
                        "content_type": meta.get("content_type"),
                        "path": f.path,
                        "hash": f.hash,
                        "created_at": _fmt_ts(created),
                        "age": _fmt_age(created, now_ts),
                    }
                )

        user_map = await _user_map(
            {r.get("user_id") for r in (*stale_chats, *stale_notes, *stale_files)}
        )
        for r in (*stale_chats, *stale_notes, *stale_files):
            uid = r.get("user_id")
            r["owner"] = user_map.get(uid) or uid or "—"

    except Exception as e:
        error_str = str(e)

    return {
        "cutoff_date": cutoff_date.strftime("%Y-%m-%d %H:%M:%S"),
        "threshold_hours": stale_hours,
        "chats": stale_chats,
        "notes": stale_notes,
        "files": stale_files,
        "scanned": scanned,
        "error": error_str,
    }


def _path(valves) -> str:
    return "/" + (valves.DASHBOARD_PATH or "/stale-data").strip().strip("/")


async def _page(user: PluginAdmin):  # admins only: the page lists every user's chat titles, notes and file names
    valves = await plugin_stored_valves(Event.Valves, ttl=5)
    payload = await _load_stale_data(stale_hours=valves.STALE_THRESHOLD_HOURS)
    return HTMLResponse(_dashboard_html(payload))


def _ensure_routes(app, valves) -> None:
    router = APIRouter()
    # `_page` is marked `user: PluginAdmin`, so plugin_mount's guard lets only admins in. Mounting
    # again replaces the earlier mount, also when DASHBOARD_PATH changed and the path moved.
    router.add_api_route(_path(valves), _page, methods=["GET"], include_in_schema=False)
    plugin_mount(app, router, _path(valves))


class Event(PluginEvents):
    class Valves(BaseModel):
        DASHBOARD_PATH: str = Field(
            default="/stale-data",
            description="URL path where the dashboard is served.",
        )
        STALE_THRESHOLD_HOURS: int = Field(
            default=1,
            description="Show content older than this many hours.",
        )

    # Open-WebUI started, or this function was enabled, updated or had its valves saved
    # (`own`: not when another function was). Each of those (re)mounts the dashboard route.
    @on(
        "system.startup.completed",
        "function.enable_started",
        "function.updated",
        "function.valves_updated",
        own=True,
    )
    async def mount(self, app):
        if app is not None:
            _ensure_routes(app, self.valves)
