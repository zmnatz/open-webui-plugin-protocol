# The plugin spec: `owpp create --spec <file>`

A YAML (or JSON) mapping that describes the plugin; `-` reads it from stdin. Every key but `id` is optional, and an unknown key is refused. It is what the `owpp create` wizard builds from its answers.

```yaml
id: notes                  # the folder and the function id: [a-z_][a-z0-9_]*
type: filter               # filter | action | event | pipe | installer | upstream
title: Notes               # default: from the id
description: Keeps notes on the chat.
author: you
version: 0.1.0
license: MIT
required_open_webui_version: 0.10.0
```

## By type

| Type | Keys |
| --- | --- |
| filter | `hooks: [inlet, request, stream, outlet]` (default `[inlet, outlet]`), `toggle: true` (a switch each user turns on; never global), `global: true \| false` (left out: global on first deploy), `file_handler: true`, `priority: true` |
| action | `buttons: [summarize, {id: tr, name: Translate}]` (several buttons), `rich_ui: true` (returns an HTML page shown above the message), `global: true`, `priority: true` |
| pipe | `models: [fast, {id: slow, name: Slow}]` (several models), `stream: true` |
| event | `events: [system.startup.completed, function.valves_updated]` (an `@on` handler each), `sync: true` and `sync_minutes: 60` (a scheduled sync) |
| installer | no function code: needs a `tool`, `skills`, or both |
| upstream | the function itself from git: needs a `source` with `function_file` |

## A tool, skills, a page, libraries

```yaml
tool:
  id: notes                 # default title: from the id
  title: Notes
  description: Save and search the chat's notes.
  methods: [save, search]   # stubs, each taking `query: str`: rename and describe the parameters
  public: true              # every signed-in user may use it (default true)
  rich_ui: false            # a show_<id> method returning an HTML page shown in the chat
  chat_data: false          # the tool keeps data with the chat

skills:                     # skills/<id>/SKILL.md each
  - id: take-notes          # lowercase letters, digits and hyphens
    description: Use when the user asks to remember something.
    public: true
  - draw                    # an id alone

page: rendered              # "" (none) | static (static/index.html) | rendered (templates/page.html, a route)
page_access: user           # user | admin | public
chat_data: true             # the function keeps data with each chat
config: true                # a config.yaml read with plugin_config()
assets: true                # events only: assets/loader.js and assets/custom.css on every page
live_reload: true           # with assets: changes reach every container within a second (Redis)
```

## From git

Code from another repository, pinned to a full 40-character commit SHA. Get the SHA of a branch or tag with `git ls-remote <url> <branch>`, and put the branch in `track` so `owpp pull` follows it.

```yaml
id: viz
type: installer             # or upstream, with function_file
source:
  git: https://github.com/owner/repo.git     # https, ssh, or user@host:path
  ref: 917c88f3029c0c6500139ba7b7b061f358d8aaea
  path: plugins/viz         # the folder the paths below are in; "" for the root
  track: main               # optional: the branch or tag owpp pull follows
  function_file: ""         # type upstream: the function file, taken with its header
tool:
  id: viz
  file: tool.py             # in the repository
skills:
  - {id: visualize, path: skills/visualize}              # a folder holding a SKILL.md
  - {id: draw, path: draw/SKILL.md, is_dir: false}        # or the SKILL.md itself
```

A plugin from git writes no code of its own: only `plugin.yaml`, a README that records where the code comes from, tests that fetch the pinned files, and (for an installer) a CHANGELOG.
