# Plugin events library (docs/libraries.md), inserted by `include: [events]`.
# Handlers for Open-WebUI's lifecycle events by decorator, so an Event function does not
# need one event() method of `if __event_name__ ...` checks:
#
#     class Event(PluginEvents):
#         @on("system.startup.completed")
#         async def started(self): ...
#
#         @on("function.valves_updated", "function.enable_started", own=True)
#         async def reload(self, app): ...
#
# `owpp check` validates the event names (a typo would otherwise never fire) and that a
# class with handlers really inherits PluginEvents.

import inspect as _inspect
import logging as _logging

_events_log = _logging.getLogger(__name__ + ".events")


def on(*names, own: bool = False):
    """Mark a method of a PluginEvents class as the handler for these events. With
    `own=True` it ignores events about other functions (an event with no subject, such as
    startup, still counts). The method may take any of `event` (the event dict), `name`,
    `id` (this function's id), `app` and `request`, by name, and may be async."""
    if not names or not all(isinstance(name, str) for name in names):
        raise TypeError("@on() takes one or more event names as strings")

    def mark(method):
        method._plugin_on = [*getattr(method, "_plugin_on", []), (names, own)]
        return method

    return mark


class PluginEvents:
    """Mixin for an Event function: `class Event(PluginEvents)`. The library's other mixins
    (PluginAssets, PluginScheduledSync) already are PluginEvents classes, so `@on` works in them
    and they combine freely; if you override `event`, call `await super().event(...)`. It also
    creates `self.valves` from the class's `Valves`, so `__init__` is only needed for more."""

    _plugin_handlers: dict = {}

    def __init__(self):
        valves = getattr(type(self), "Valves", None)
        if valves is not None:  # `self.valves = self.Valves()`, so a class need not write it
            self.valves = valves()

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        table: dict = {}
        for klass in reversed(cls.__mro__):  # inherited handlers first, a subclass may add more
            for attr, value in vars(klass).items():
                for names, own in getattr(value, "_plugin_on", ()):
                    for name in names:
                        entry = (attr, own)
                        if entry not in table.setdefault(name, []):
                            table[name].append(entry)
        cls._plugin_handlers = table

    async def event(
        self,
        event: dict = None,
        __event_name__: str = None,
        __id__: str = None,
        __app__=None,
        __request__=None,
        **kwargs,
    ):
        handlers = self._plugin_handlers.get(__event_name__, ())
        if handlers:
            own_id = __id__ or plugin_function_id()
            subject = ((event or {}).get("subject") or {}).get("id")
            context = {
                "event": event,
                "name": __event_name__,
                "id": own_id,
                "request": __request__,
                "app": __app__ or getattr(__request__, "app", None) or plugin_app(),
            }
            for attr, own in handlers:
                if own and subject not in (None, own_id):
                    continue
                method = getattr(self, attr)
                accepted = _inspect.signature(method).parameters
                try:
                    result = method(**{k: v for k, v in context.items() if k in accepted})
                    if _inspect.isawaitable(result):
                        await result
                except Exception:  # one handler must not stop the others, or the mixins after it
                    _events_log.exception("handler %s for %s failed", attr, __event_name__)
        parent = getattr(super(), "event", None)
        if parent is not None:
            await parent(
                event,
                __event_name__=__event_name__,
                __id__=__id__,
                __app__=__app__,
                __request__=__request__,
                **kwargs,
            )


# end plugin events library
