# Plugin jobs library (docs/libraries.md), inserted by `include: [jobs]`.
# Run work in the background and on a repeat, once across all workers and
# replicas, and stop it when the function is disabled.

import asyncio as _asyncio
import json as _json
import logging as _logging
import sys as _sys
import time as _time
import types as _types

from .plugin_core import (
    plugin_app,
    plugin_env,
    plugin_function_id,
    plugin_is_active,
    plugin_stored_valves,
)
from .plugin_events import PluginEvents, on

_jlog = _logging.getLogger(__name__ + ".jobs")

# {"sync_every_minutes": 60 | "${NAME:-60}", "adopt_markers": [...]}, from plugin.yaml's `jobs:`
__JOBS_DATA__ = '{"sync_every_minutes": 60}'  # for imports; the bundler drops it
_JOBS = _json.loads(__JOBS_DATA__)


def plugin_sync_markers() -> set:
    """The `managed_by` markers a sync treats as its own: this function's id, plus the markers
    of an earlier sync that plugin.yaml's `jobs: adopt_markers` names. Entries carrying one are
    replaced and pruned like the sync's own; everything else is left alone. Empty when the
    function id is unknown, so nothing can match by accident."""
    own = plugin_function_id()
    if not own:
        return set()
    return {own, *_JOBS.get("adopt_markers", [])}


def _sync_valves(base):
    """`base` (the function's own Valves class, or None) plus the two valves the sync mixin
    needs, unless the function defines them itself."""
    from pydantic import BaseModel, Field, create_model

    existing = getattr(base, "model_fields", {})
    minutes = plugin_env(_JOBS["sync_every_minutes"])  # a number, or ${NAME:-60} from the container
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
        if minutes is not None:
            _jlog.warning(
                "jobs: sync_every_minutes %r is not a whole number of minutes, using 60",
                _JOBS["sync_every_minutes"],
            )
        minutes = 60
    fields = {}
    if "ENABLE" not in existing:
        fields["ENABLE"] = (bool, Field(default=True, description="Turn this sync on or off."))
    if "SYNC_INTERVAL_MINUTES" not in existing:
        fields["SYNC_INTERVAL_MINUTES"] = (
            int,
            Field(
                default=minutes,
                description=(
                    "Also re-sync this often, on one worker, so changes are picked up without a "
                    "restart. 0 syncs only at startup, on enable and when valves change."
                ),
            ),
        )
    if not fields:
        return base
    return create_model("Valves", __base__=base or BaseModel, **fields)


def _jobs_state():
    """Survives this module being loaded again (Open-WebUI reloads functions), so a
    new load replaces the old load's loops instead of doubling them."""
    key = f"_plugin_jobs_{plugin_function_id() or __name__}"
    state = _sys.modules.get(key)
    if state is None:
        state = _types.ModuleType(key)
        state.loops, state.tasks, state.claims, state.lock = {}, set(), {}, None
        _sys.modules[key] = state
    return state


def _jobs_redis():
    return getattr(getattr(plugin_app(), "state", None), "redis", None)


async def plugin_claim(key: str, ttl_seconds: float) -> bool:
    """True for exactly one caller across all workers within the ttl (Redis SET NX
    EX when Open-WebUI has Redis, else a per-process expiry map). The ttl doubles
    as a cooldown."""
    ttl = max(1, int(ttl_seconds))
    redis = _jobs_redis()
    if redis is not None:
        try:
            return bool(await redis.set(f"plugin:{plugin_function_id()}:{key}", "1", nx=True, ex=ttl))
        except Exception:
            _jlog.warning("jobs: Redis claim failed, using the in-process fallback", exc_info=True)
    claims, now = _jobs_state().claims, _time.time()
    if claims.get(key, 0) > now:
        return False
    claims[key] = now + ttl
    return True


async def plugin_unclaim(key: str) -> None:
    """Undo a claim whose work never ran, so the cooldown is not burned."""
    redis = _jobs_redis()
    if redis is not None:
        try:
            await redis.delete(f"plugin:{plugin_function_id()}:{key}")
            return
        except Exception:
            _jlog.debug("jobs: Redis unclaim failed", exc_info=True)
    _jobs_state().claims.pop(key, None)


async def _jobs_run(name: str, factory, on_skip=None) -> None:
    state = _jobs_state()
    if state.lock is None:
        state.lock = _asyncio.Lock()
    if state.lock.locked():
        _jlog.info("jobs: skipping %r, another job is running", name)
        if on_skip:
            on_skip()
        return
    async with state.lock:
        try:
            await factory()
        except Exception:
            _jlog.exception("jobs: %r failed", name)


def plugin_spawn(name: str, factory, on_skip=None):
    """Run `factory()` (an async function) in the background, one job at a time
    per function in this process. Needs a running event loop; returns the task or
    None."""
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return None
    task = loop.create_task(_jobs_run(name, factory, on_skip))
    state = _jobs_state()
    state.tasks.add(task)
    task.add_done_callback(state.tasks.discard)
    return task


def plugin_every(name: str, seconds: float, factory, first_after: float = None):
    """Run `factory()` every `seconds`, on one worker per period (a claim, so extra
    workers and replicas skip), until the function is disabled or deleted (checked
    each period; a later load or enable starts it again). Calling it again with the
    same name replaces the earlier loop, so re-running it on every load is safe.
    The claim lasts at least a second (Redis expiry is whole seconds), so a period
    shorter than that still runs at most once a second. Needs a running event
    loop; returns the task or None."""
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return None
    state = _jobs_state()
    previous = state.loops.pop(name, None)
    if previous is not None:
        previous.cancel()

    async def repeat():
        await _asyncio.sleep(seconds if first_after is None else first_after)
        while await plugin_is_active():
            if await plugin_claim(f"every:{name}", seconds * 0.9):
                await _jobs_run(name, factory)
            await _asyncio.sleep(seconds)

    task = loop.create_task(repeat())
    state.loops[name] = task
    return task


def plugin_stop_jobs() -> None:
    """Cancel this function's repeating jobs."""
    state = _jobs_state()
    for task in list(state.loops.values()):
        task.cancel()
    state.loops.clear()


class PluginScheduledSync(PluginEvents):
    """Mixin for an Event function that repeats one job: `class Event(PluginScheduledSync)`.
    It needs `self.valves` (`self.valves = self.Valves()`) and an async `sync()`. It runs
    `sync()` on those lifecycle events and then every interval, on one worker, and stops
    when ENABLE is off or the function is disabled. It is a PluginEvents class, so `@on`
    handlers of your own work beside it.

    The `ENABLE` and `SYNC_INTERVAL_MINUTES` valves are added to the class's `Valves` for you
    (the default interval is plugin.yaml's `jobs.sync_every_minutes`); define either yourself
    to change its description or default."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.Valves = _sync_valves(getattr(cls, "Valves", None))

    async def event(
        self,
        event: dict = None,
        __event_name__: str = None,
        __id__: str = None,
        __app__=None,
        __request__=None,
        **kwargs,
    ):
        if not self.valves.ENABLE:
            plugin_stop_jobs()
            return
        await super().event(
            event,
            __event_name__=__event_name__,
            __id__=__id__,
            __app__=__app__,
            __request__=__request__,
            **kwargs,
        )

    @on("system.startup.completed", "function.enable_started", "function.valves_updated", own=True)
    async def _sync_on_lifecycle(self):
        """Open-WebUI started, or this function was enabled or had its valves saved."""
        await self.sync()
        self._schedule()

    def _schedule(self):
        minutes = int(self.valves.SYNC_INTERVAL_MINUTES or 0)
        if minutes > 0:
            plugin_every("sync", minutes * 60, self._scheduled)  # replaces an earlier loop
        else:
            plugin_stop_jobs()

    async def _scheduled(self):
        valves = await plugin_stored_valves(self.Valves)  # fresh: no event applied them
        if not valves.ENABLE:
            return
        self.valves = valves
        await self.sync()


# end plugin jobs library
