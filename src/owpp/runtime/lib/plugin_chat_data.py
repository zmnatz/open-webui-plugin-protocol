# Plugin chat data library (docs/libraries.md), inserted by `include: [chat_data]`.
# Save and read a JSON value that lives with a chat, under a key of your own, in
# that chat's metadata (so it is deleted with the chat). A temporary chat has no
# database row, so its values are kept in memory until Open-WebUI restarts.

import asyncio as _asyncio
import inspect as _inspect
import json as _json
import re as _re
import sys as _sys
import types as _types


class ChatNotSaved(RuntimeError):
    """The chat has no database row (yet). The message is what a model sees."""

    def __init__(self, chat_id: str):
        super().__init__(f"Chat {chat_id} is not saved yet: send a message first, then retry.")


def _chat_state() -> _types.ModuleType:
    """State shared by every plugin's copy of this code (the function's and the
    tool's are separate modules): the temporary chats' values and the locks."""
    state = _sys.modules.get("_plugin_chat_data")
    if state is None:
        state = _types.ModuleType("_plugin_chat_data")
        state.temp, state.locks = {}, {}
        _sys.modules["_plugin_chat_data"] = state
    return state


def _chat_key(key: str) -> str:
    """The key goes into SQL, so it is restricted to a plain identifier. Pick one
    per plugin (its id is a good choice); two plugins must not share one."""
    if not isinstance(key, str) or not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", key):
        raise ValueError("a chat data key must be a plain identifier (letters, digits, _)")
    return key


def plugin_chat_is_temp(chat_id: str) -> bool:
    return str(chat_id).startswith("local:")


async def plugin_chat_read(chat_id: str, key: str):
    """The value saved under `key` for the chat, or None. Raises ChatNotSaved if
    the chat has no row."""
    key = _chat_key(key)
    if plugin_chat_is_temp(chat_id):
        return _chat_state().temp.get((key, chat_id))
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.chats import Chat
    from sqlalchemy import select

    async with get_async_db_context() as session:
        row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()
    if row is None:
        raise ChatNotSaved(chat_id)
    meta = row[0] or {}
    if isinstance(meta, str):
        meta = _json.loads(meta)
    return meta.get(key)


async def plugin_chat_write(chat_id: str, value, key: str) -> None:
    """Save a JSON-serialisable value under `key`. Raises ChatNotSaved if the chat
    has no row."""
    key = _chat_key(key)
    if plugin_chat_is_temp(chat_id):
        _chat_state().temp[(key, chat_id)] = value
        return
    from open_webui.internal.db import get_async_db_context
    from open_webui.models.chats import Chat
    from sqlalchemy import select, text, update

    encoded = _json.dumps(value)
    table = Chat.__tablename__
    async with get_async_db_context() as session:
        dialect = session.get_bind().dialect.name
        # Set only our key, in place, so this never overwrites what Open-WebUI keeps
        # in meta (tags and the like), and leave updated_at alone so a write does
        # not reorder the chat list.
        if dialect == "sqlite":
            result = await session.execute(
                text(f"UPDATE {table} SET meta = json_set(COALESCE(meta, '{{}}'), '$.{key}', json(:v)) WHERE id = :id"),
                {"v": encoded, "id": chat_id},
            )
        elif dialect == "postgresql":
            result = await session.execute(
                text(
                    f"UPDATE {table} SET meta = CAST(COALESCE(CAST(meta AS jsonb), CAST('{{}}' AS jsonb)) "
                    f"|| jsonb_build_object('{key}', CAST(:v AS jsonb)) AS json) WHERE id = :id"
                ),
                {"v": encoded, "id": chat_id},
            )
        else:
            row = (await session.execute(select(Chat.meta).filter_by(id=chat_id))).one_or_none()
            if row is None:
                raise ChatNotSaved(chat_id)
            result = await session.execute(
                update(Chat).filter_by(id=chat_id).values(meta={**(row[0] or {}), key: value})
            )
        await session.commit()
    if result.rowcount == 0:
        raise ChatNotSaved(chat_id)


async def plugin_chat_update(chat_id: str, change, key: str, default=None):
    """Read-modify-write under a lock for this chat and key, so concurrent changes
    do not lose each other (within one process). `change(current, is_new)` gets the
    saved value, or `default` when nothing is saved, and returns the new value, or
    None to keep things as they are. Returns the value now in effect."""
    key = _chat_key(key)
    locks = _chat_state().locks
    lock = locks.get((key, chat_id))
    if lock is None:
        lock = locks[(key, chat_id)] = _asyncio.Lock()
    async with lock:
        saved = await plugin_chat_read(chat_id, key)
        current = default if saved is None else saved
        new = change(current, saved is None)
        if _inspect.isawaitable(new):
            new = await new
        if new is None:
            return current
        await plugin_chat_write(chat_id, new, key)
        return new


# end plugin chat data library
