# Open-WebUI plugin protocol

A way to write, test and deploy Open-WebUI **plugins** from a git repository: a function (the parent) plus an optional tool and skills, installed and removed together, with shared libraries for the things every plugin ends up needing (routes, background jobs, per-chat data, static files).

Open-WebUI stores a function or tool as **one code blob** and cannot import siblings. This protocol is the layer that makes a folder of files behave like one plugin:

1. A **plugin** is a folder with a `plugin.yaml` manifest ([plugin format](plugin-format.md)).
2. A **bundler** turns the folder into the single file Open-WebUI stores, in a fixed order, and can pull function, tool and skill code from any git repo at a pinned commit ([bundling](bundling.md)).
3. A **runtime**, appended to the bundle, makes the function the parent: enabling it installs its tool and skills, disabling or deleting it removes them ([runtime](runtime.md)).
4. **Libraries** are vendored Python blocks a manifest lists under `include:` ([libraries](libraries.md)).
5. A **CLI and a deploy script** check, bundle and deploy one plugin or all of them, from a laptop or CI ([tooling](tooling.md)).

## Reading order

| If you want to... | Read |
| --- | --- |
| Install it | [install](install.md) |
| Go from nothing to a deployed plugin | [getting started](getting-started.md) |
| Have an AI agent do it | [with an AI agent](ai-agents.md) |
| Start a plugin with the `owpp create` wizard | [creating a plugin](creating.md) |
| Write a plugin | [authoring guide](authoring.md), then [plugin format](plugin-format.md) |
| Know exactly what ends up in the deployed file | [bundling](bundling.md) |
| Understand install/remove, valves and sync | [runtime](runtime.md) |
| Use routes, jobs, chat data, static files and templates | [libraries](libraries.md) |
| Unit-test a plugin against a mock Open-WebUI | [testing](testing.md) |
| Test, deploy, set up CI | [tooling](tooling.md) |
| Use it in your repository, or move existing functions over | [adopting](adopting.md) |
| Move to a new owpp version | [upgrading](upgrading.md) |
| Review a change, or repeat the tests by hand | [reviewing](reviewing.md), [test catalogue](reference/test-catalogue.md) |
| See every change so far | [changelog](../CHANGELOG.md) |
| Make a change to this repository | [contributing](contributing.md) |
| Know what you are trusting, and how to report a problem | [security](../SECURITY.md) |
| Know the terms you may use it under | [license](../LICENSE) |

## At a glance

```
plugins/<id>/
  plugin.yaml      protocol: / function: (parent) / tool: / skills: / source: / include: / public:
  function.py      the function's code        (a Filter, Event, Action or Pipe)
  tool.py          optional tool code
  shared.py        optional code both need, placed in front of each
  skills/<id>/     optional skills, whole folders
  static/          optional files served at /<id>/<path>
  templates/       optional files the function renders itself (never served)
  tests/           optional unit tests, run by `owpp test` (never deployed)
  README.md        what it is, how to test it, how to deploy it
```

```yaml
# plugin.yaml
protocol: "0.2"
function:
  title: My Plugin
  author: me
  version: 1.0.0
  global: true            # filters and actions only
include: [routes, chat_data]
tool: { id: my_plugin, access: public }
```

```
owpp list                            # plugins and their function type
owpp check my_plugin                 # bundle, compile, find undefined names
owpp test my_plugin                  # its tests/, against a mock Open-WebUI
owpp deploy --only my_plugin --dry-run
```

## Guarantees

- **Reproducible.** A bundle depends only on the folder and the pinned git commits it names. Libraries are vendored byte for byte.
- **Reviewed upgrades.** Remote code is referenced by full commit SHA, never a branch or tag, because it runs inside Open-WebUI with admin rights. `owpp pull` moves the SHA to the latest commit, as a change to review and commit.
- **Owned objects only.** The deploy marks what it creates (`meta.managed_by`) and only ever updates or deletes those. Hand-made functions are never touched.
- **No surprises on disable.** Whatever a function installed (tools, skills, routes, background jobs) goes away or stops when it is disabled.

## Status and limits

Written against Open-WebUI **v0.13.4**. API shapes (skills as `files` lists, tool valves, `Functions.get_function_valves_by_id`) were read from that source, and the libraries are tested against stubbed Open-WebUI modules, not a live instance. The examples have been deployed and checked by hand on a real v0.13.4 ([screenshots](screenshots.md)).

Known limits:

- **No live test in CI.** Every change is tested against a mock Open-WebUI; a real one is started only by hand (the screenshot run). Planned for 1.0: [issue #14](https://github.com/zmnatz/open-webui-plugin-protocol/issues/14).
- **Sign-in fallbacks checked against source, not a live instance.** For a page opened with no session, the guard relies on Open-WebUI's `/api/v1/auths/signin` accepting empty credentials when trusted-header sign-in is configured, and on its login page honouring `?redirect=` ([routes](libraries.md#routes)). Verified in the v0.13.4 source: both hold, with no user name or password needed under a trusted header. The signin route needs `ENABLE_PASSWORD_AUTH` (on by default) and the trusted header to be present.
- **Redis** claims in the `jobs` library are tested with stubs only.
- **No example serves `static/` files or a public mount** (both example pages are templates the function renders). The `static` library and the `public` access level are tested, and `owpp create` writes both, but no example shows them.
