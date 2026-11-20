

# =============================================================== plugin runtime
# Appended to a plugin's function by the bundler (src/owpp/bundle.py) when the
# plugin also declares a tool or skills (docs/runtime.md). The function is the parent:
# while it is enabled this installs (and keeps current) the plugin's tool and
# skills, and when it is disabled or deleted it removes them again. Edit this
# file in src/owpp/runtime/, not in a deployed copy.
import asyncio as _asyncio
import json as _json
import logging as _logging
import sys as _sys
import time as _time
import types as _types
from typing import Optional as _Optional

_plog = _logging.getLogger(__name__ + ".plugin")
# {"tools": [{id, name, access, self, valves, content}], "skills": [{id, name, description, access, files: [{path, content, encoding?}]}]}
_PLUGIN = _json.loads(__PLUGIN_DATA__)
_PLUGIN_TAG = "plugin:"  # skills carry plugin:<function id> in their tags
_PLUGIN_EVENTS = {
    "function.enabled",
    "function.disabled",
    "function.updated",
    "function.valves_updated",  # INSTALL_TOOLS, INSTALL_SKILLS, TOOL_VALVES apply on save
    "function.deleted",
}


def _plugin_module_id(prefix: str) -> _Optional[str]:
    """Open-WebUI names a module <prefix>_<id>_<32 hex chars>."""
    name = __name__
    if not name.startswith(prefix + "_"):
        return None
    return name[len(prefix) + 1 :].rsplit("_", 1)[0] or None


def _plugin_state(function_id: str) -> _types.ModuleType:
    """State that survives this module being loaded again (Open-WebUI reloads
    function modules), keyed by function id."""
    key = f"_plugin_runtime_{function_id}"
    module = _sys.modules.get(key)
    if module is None:
        module = _types.ModuleType(key)
        module.sink = None
        module.last = 0.0
        _sys.modules[key] = module
    return module


def _plugin_public_read() -> list:
    """Read for every signed-in user: Open-WebUI's `user:*` grant. (Not its `anyone:*` grant,
    which is a separate no-auth audience that its tool and skill access checks ignore.)"""
    return [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def _plugin_grant(grant) -> tuple:
    if isinstance(grant, dict):
        return (grant.get("principal_type"), grant.get("principal_id"), grant.get("permission"))
    return (
        getattr(grant, "principal_type", None),
        getattr(grant, "principal_id", None),
        getattr(grant, "permission", None),
    )


async def _plugin_repair_public(resource_type: str, item: dict, grants) -> None:
    """Runtimes before this one granted a public tool or skill to `anyone:*`, which
    Open-WebUI does not honour for them, so only admins could use it. Swap exactly that
    grant for `user:*` read, once, and leave any other grants as the admin set them."""
    if item["access"] != "public":
        return
    triples = [_plugin_grant(g) for g in grants or []]
    if ("anyone", "*", "read") not in triples or ("user", "*", "read") in triples:
        return
    from open_webui.models.access_grants import AccessGrants

    kept = [
        {"principal_type": a, "principal_id": b, "permission": c}
        for a, b, c in triples
        if (a, b, c) != ("anyone", "*", "read")
    ]
    await AccessGrants.set_access_grants(resource_type, item["id"], kept + _plugin_public_read())
    _plog.info("plugin: %s %r made readable by every user", resource_type, item["id"])


async def _plugin_valves(function_id: str) -> dict:
    """The function's stored valves that steer this runtime: INSTALL_TOOLS and
    INSTALL_SKILLS (default on) and TOOL_VALVES, a JSON {tool id: {valve: value}}.
    Read from the database because a function's own valves are only applied to
    its instance when a chat runs it."""
    from open_webui.models.functions import Functions

    stored = await Functions.get_function_valves_by_id(function_id) or {}
    overrides = {}
    raw = stored.get("TOOL_VALVES")
    if raw:
        try:
            overrides = _json.loads(raw) if isinstance(raw, str) else dict(raw)
            if not isinstance(overrides, dict):
                raise ValueError("not an object")
        except ValueError:
            _plog.warning("plugin %s: TOOL_VALVES is not a JSON object; ignored", function_id)
            overrides = {}
    return {
        "tools": stored.get("INSTALL_TOOLS", True) is not False,
        "skills": stored.get("INSTALL_SKILLS", True) is not False,
        "tool_valves": overrides,
    }


async def _plugin_sync(function_id: str) -> None:
    """Make Open-WebUI match the function's state. Never raises."""
    try:
        from open_webui.models.functions import Functions

        function = await Functions.get_function_by_id(function_id)
        if function is None or not function.is_active:
            await _plugin_remove(function_id)
            return
        valves = await _plugin_valves(function_id)
        if valves["tools"]:
            await _plugin_install_tools(function, valves["tool_valves"])
        else:
            await _plugin_remove(function_id, skills=False)
        if valves["skills"]:
            await _plugin_install_skills(function)
        else:
            await _plugin_remove(function_id, tools=False)
    except Exception:
        _plog.exception("plugin %s: could not sync its tool and skills", function_id)


async def _plugin_apply_valves(item: dict, overrides: dict) -> None:
    """Set the valves plugin.yaml and TOOL_VALVES declare on the tool; other
    valves keep whatever the admin set."""
    wanted = {**(item.get("valves") or {}), **(overrides.get(item["id"]) or {})}
    if not wanted:
        return
    from open_webui.models.tools import Tools
    from open_webui.utils.plugin import load_tool_module_by_id

    current = await Tools.get_tool_valves_by_id(item["id"]) or {}
    merged = {**current, **wanted}
    if merged == current:
        return
    tool = await Tools.get_tool_by_id(item["id"])
    module, _, _ = await load_tool_module_by_id(item["id"], content=tool.content)
    if hasattr(module, "Valves"):
        try:
            module.Valves(**merged)  # refuse values the tool would reject
        except Exception as error:
            _plog.warning("plugin: valves for tool %r not applied: %s", item["id"], error)
            return
    await Tools.update_tool_valves_by_id(item["id"], merged)
    _plog.info("plugin: set valves %s on tool %r", sorted(wanted), item["id"])


async def _plugin_install_tools(function, overrides: dict) -> None:
    if not _PLUGIN["tools"]:
        return
    # Imported lazily: these only exist inside Open-WebUI.
    from open_webui.models.tools import ToolForm, ToolMeta, Tools
    from open_webui.utils.plugin import load_tool_module_by_id, replace_imports
    from open_webui.utils.tools import get_tool_specs

    for item in _PLUGIN["tools"]:
        content = replace_imports(function.content if item["self"] else item["content"])
        tool = await Tools.get_tool_by_id(item["id"])
        if tool is not None:
            parent = (tool.meta.manifest or {}).get("parent_function_id")
            if parent != function.id:
                _plog.warning(
                    "plugin %s: tool %r exists and is not this plugin's; left alone",
                    function.id,
                    item["id"],
                )
                continue
            await _plugin_repair_public("tool", item, getattr(tool, "access_grants", None))
            if tool.content == content:
                await _plugin_apply_valves(item, overrides)
                continue
        module, frontmatter, _ = await load_tool_module_by_id(item["id"], content=content)
        meta = ToolMeta(
            description=(frontmatter or {}).get("description"),
            # The parent id lets the tool's own module notice, after a restart,
            # that the function was disabled while Open-WebUI was down.
            manifest={**(frontmatter or {}), "parent_function_id": function.id},
            has_user_valves=hasattr(module, "UserValves"),
        )
        specs = get_tool_specs(module)
        if tool is None:
            form = ToolForm(
                id=item["id"],
                name=item["name"],
                content=content,
                meta=meta,
                access_grants=_plugin_public_read() if item["access"] == "public" else [],
            )
            await Tools.insert_new_tool(function.user_id, form, specs, module=module)
            _plog.info("plugin %s: installed tool %r", function.id, item["id"])
        else:
            # Access grants are left as the admin set them.
            await Tools.update_tool_by_id(
                item["id"],
                {"content": content, "meta": meta.model_dump(), "specs": specs},
                user_id=function.user_id,
                module=module,
            )
            _plog.info("plugin %s: updated tool %r", function.id, item["id"])
        await _plugin_apply_valves(item, overrides)


async def _plugin_install_skills(function) -> None:
    if not _PLUGIN["skills"]:
        return
    from open_webui.models.skills import SkillForm, SkillMeta, Skills

    tag = _PLUGIN_TAG + function.id
    for item in _PLUGIN["skills"]:
        skill = await Skills.get_skill_by_id(item["id"])
        meta = SkillMeta(tags=[tag])
        # The whole skill folder: SKILL.md plus any supporting files, sorted by path
        # the way Open-WebUI stores them.
        files = sorted(item["files"], key=lambda f: f["path"])
        if skill is None:
            await Skills.insert_new_skill(
                function.user_id,
                SkillForm(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    files=files,
                    meta=meta,
                    is_active=True,
                    access_grants=_plugin_public_read() if item["access"] == "public" else [],
                ),
            )
            _plog.info("plugin %s: installed skill %r (%d files)", function.id, item["id"], len(files))
        elif tag not in (skill.meta.tags or []):
            _plog.warning(
                "plugin %s: skill %r exists and is not this plugin's; left alone",
                function.id,
                item["id"],
            )
            continue
        else:
            await _plugin_repair_public("skill", item, getattr(skill, "access_grants", None))
        if skill is not None and (skill.name, skill.description, (skill.data or {}).get("files")) != (
            item["name"],
            item["description"],
            files,
        ):
            await Skills.update_skill_by_id(
                item["id"],
                {
                    "name": item["name"],
                    "description": item["description"],
                    "files": files,
                    "meta": meta.model_dump(),
                    # File updates must name the version they were based on.
                    "expected_version_id": skill.version_id,
                },
                user_id=function.user_id,
            )
            _plog.info("plugin %s: updated skill %r (%d files)", function.id, item["id"], len(files))


async def _plugin_remove(function_id: str, tools: bool = True, skills: bool = True) -> None:
    """Remove what this plugin installed (the tools, the skills or both). Safe to
    call repeatedly; only things marked as this function's are touched."""
    from open_webui.models.skills import Skills
    from open_webui.models.tools import Tools

    for item in _PLUGIN["tools"] if tools else []:
        tool = await Tools.get_tool_by_id(item["id"])
        if tool is not None and (tool.meta.manifest or {}).get("parent_function_id") == function_id:
            await Tools.delete_tool_by_id(item["id"])
            _plog.info("plugin %s: removed tool %r (function disabled or gone)", function_id, item["id"])
    for item in _PLUGIN["skills"] if skills else []:
        skill = await Skills.get_skill_by_id(item["id"])
        if skill is not None and (_PLUGIN_TAG + function_id) in (skill.meta.tags or []):
            await Skills.delete_skill_by_id(item["id"])
            _plog.info("plugin %s: removed skill %r (function disabled or gone)", function_id, item["id"])


async def _plugin_ensure() -> None:
    """Sync now unless a sync ran in the last few seconds. Cheap enough to call
    from a Filter's inlet, which retries a sync that failed at startup."""
    function_id = _plugin_module_id("function")
    if not function_id:
        return
    state = _plugin_state(function_id)
    if _time.monotonic() - state.last < 10:
        return
    state.last = _time.monotonic()
    await _plugin_sync(function_id)


class _PluginSink:
    """Open-WebUI stops loading a function once it is disabled, so the function's
    own code never sees that. An event sink is the hook that still runs; it
    resyncs when this function is enabled, disabled, updated or deleted, or when an
    admin saves its valves (a user saving their own UserValves is not a reason)."""

    function_id: _Optional[str] = None

    # Open-WebUI 0.10.0 calls handle_event(app, event, request=...); newer
    # versions call handle_event(request, event). Accept either.
    async def handle_event(self, first, event, **kwargs) -> None:
        if not self.function_id:
            return
        get = event.get if isinstance(event, dict) else lambda key: getattr(event, key, None)
        if (get("subject") or {}).get("id") != self.function_id:
            return
        if get("event") not in _PLUGIN_EVENTS:
            return
        if (get("data") or {}).get("scope") == "user":
            return
        await _plugin_sync(self.function_id)


async def _plugin_check_parent() -> None:
    """Run when the tool's module loads: remove the plugin if its function was
    disabled while Open-WebUI was down (the function never loaded to notice)."""
    tool_id = _plugin_module_id("tool")
    if not tool_id:
        return
    try:
        from open_webui.models.functions import Functions
        from open_webui.models.tools import Tools

        tool = await Tools.get_tool_by_id(tool_id)
        parent = ((tool.meta.manifest or {}) if tool else {}).get("parent_function_id")
        if not parent:
            return
        function = await Functions.get_function_by_id(parent)
        if function is None or not function.is_active:
            await _plugin_remove(parent)
    except Exception:
        _plog.exception("plugin: could not check the tool's parent function")


def _plugin_start() -> None:
    try:
        loop = _asyncio.get_running_loop()
    except RuntimeError:
        return
    function_id = _plugin_module_id("function")
    if function_id:
        try:
            from open_webui.events import EVENT_SINKS
        except Exception:
            EVENT_SINKS = None
        state = _plugin_state(function_id)
        if EVENT_SINKS is not None and not isinstance(state.sink, _PluginSink):
            if state.sink is not None:
                try:
                    EVENT_SINKS.remove(state.sink)
                except ValueError:
                    pass
            state.sink = _PluginSink()
            EVENT_SINKS.append(state.sink)
        if state.sink is not None:
            state.sink.function_id = function_id
        loop.create_task(_plugin_ensure())
    elif _plugin_module_id("tool"):
        loop.create_task(_plugin_check_parent())


_plugin_start()
