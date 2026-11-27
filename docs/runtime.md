# Runtime: the function is the parent

owpp appends the plugin runtime (`src/owpp/runtime/plugin_runtime.py`) to the bundle of each plugin that declares a tool or skills. With the runtime, the function installs its tool and skills when you enable it. It removes them when you disable or delete it.

If such a plugin has no `function.py`, owpp generates the parent function: a **global Filter** that only installs and removes. Thus there is always a function to switch on or off.

## Ownership markers

The runtime marks what it installs:

| Object | Marked with |
| --- | --- |
| Tool | `meta.manifest.parent_function_id = <function id>` |
| Skill | tag `plugin:<function id>` |

The runtime updates or removes only objects that have its function's marker. It does not change a tool or skill with the same id that someone made by hand.

## When it syncs

A sync **installs and updates** the tool and skills while the function is enabled. It **removes** them when the function is disabled or deleted. The runtime acts at these times:

- when Open-WebUI loads the function, which for a global function is at startup;
- on each of these function events, through `EVENT_SINKS`: `function.enabled`, `.disabled`, `.updated` and `.deleted`;
- when an admin saves the function's valves (`function.valves_updated`), so `INSTALL_TOOLS`, `INSTALL_SKILLS` and `TOOL_VALVES` apply on save. A user who saves their own UserValves does not start a sync;
- when the function's `inlet` calls `plugin_ensure()` (`from owpp.lib import plugin_ensure`). This tries a failed startup sync again, at most once in 10 seconds;
- when the tool's module loads (`_plugin_check_parent`). If the function was disabled during a restart, the tool then removes what the plugin installed.

## Valves on the parent

Open-WebUI applies a function's valves to its running instance only when a chat runs it. For this reason, the runtime reads the stored valves from the database.

| Valve | Default | Effect |
| --- | --- | --- |
| `INSTALL_TOOLS` | on | If off, the runtime removes only the tools. |
| `INSTALL_SKILLS` | on | If off, the runtime removes only the skills. |
| `TOOL_VALVES` | `{}` | JSON `{"<tool id>": {"<valve>": value}}`. The runtime sets these on the tool's valves. They win over the manifest's `tool.valves`. |

Only the generated parent declares these valves (those for what it installs), so only it shows them in the Admin UI. For a plugin with its own function code, the runtime reads the same stored values, if there are any.

On every sync, the runtime sets the tool valves that `tool.valves` or `TOOL_VALVES` declares. All other valves keep the values that the admin set. First, the runtime checks the new values against the tool's `Valves` class. If the class rejects them, the runtime logs a warning and does not change that tool's valves.

## Public tools and skills

A tool or skill with `access: public` gets Open-WebUI's `user:*` read grant, so every signed-in user can use it. The runtime adds the grant when it first installs the item, and keeps later changes from the UI. Without `access: public`, only admins can use the item.

Earlier copies of the runtime (in portainer, before it moved to owpp) granted `public` items to Open-WebUI's `anyone:*` audience. Open-WebUI uses that no-auth audience for shared chats, and its tool and skill access checks ignore it. Thus only admins could use those items. On the next sync of a `public` item that it installed, the runtime replaces exactly that grant with `user:*`. It does not change any other grant.

## What it never does

- It does not manage model presets.
- It does not create or delete the function itself: the deploy does that.

## Source of truth

The runtime is `src/owpp/runtime/plugin_runtime.py` in this package. Change it there, never in a deployed copy. Its tests are in `tests/plugin_runtime_test.py` (Python, with a stand-in for Open-WebUI).
