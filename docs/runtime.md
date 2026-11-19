# Runtime: the function is the parent

`src/owpp/runtime/plugin_runtime.py` is appended to every bundle whose plugin declares a tool or skills. It is what makes enabling a function install its tool and skills, and disabling or deleting it remove them. A plugin with a tool or skills but no `function.py` gets a generated no-op **global Filter** as the parent, so there is always a function to toggle.

## Ownership markers

| Object | Marked with |
| --- | --- |
| Tool | `meta.manifest.parent_function_id = <function id>` |
| Skill | tag `plugin:<function id>` |

The runtime only updates or removes objects carrying its function's marker. A tool or skill with the same id that someone made by hand is left alone.

## When it syncs

- at Open-WebUI startup (a global function is loaded then);
- on every function lifecycle event (`function.enabled`, `.disabled`, `.updated`, `.deleted`), through `EVENT_SINKS`;
- when an admin saves the function's valves (`function.valves_updated`; a user saving their own UserValves does not count), so `INSTALL_TOOLS`, `INSTALL_SKILLS` and `TOOL_VALVES` apply on save;
- from a throttled `_plugin_ensure()` called in the function's `inlet` (retries a failed startup sync);
- when the tool's module loads (`_plugin_check_parent`), for a restart that happened while the function was disabled.

A sync **installs and updates** the tool and skills while the function is enabled, and **removes** them when it is disabled or deleted.

## Valves on the parent

A function's own valves only reach a running instance when a chat runs it, so the runtime reads the stored valves from the database.

| Valve | Default | Effect |
| --- | --- | --- |
| `INSTALL_TOOLS` | on | Off removes just the tools. |
| `INSTALL_SKILLS` | on | Off removes just the skills. |
| `TOOL_VALVES` | `{}` | JSON `{"<tool id>": {"<valve>": value}}`, applied to the tool's valves. Wins over the manifest's `tool.valves`. |

Only the generated parent declares these, so only it shows them in the Admin UI. A plugin with its own function code reads the same stored values if present.

Tool valves are enforced for the declared keys only, on every sync; other valves keep what the admin set. Values are validated against the tool's own `Valves` class first.

## What it never does

- It does not manage model presets.
- It does not create or delete the function itself (the deploy script does).
- It does not touch tools or skills it did not mark.

## Source of truth

The runtime is `src/owpp/runtime/plugin_runtime.py` in this package, never edited in a deployed copy. Tests: `tests/plugin_runtime_test.py` (Python, stubbed Open-WebUI).
