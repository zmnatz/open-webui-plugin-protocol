# Open-WebUI plugin protocol

A way to write, test and deploy Open-WebUI **plugins** from a git repository: a function (the parent) plus an optional tool and skills, installed and removed together, with shared libraries for the things every plugin ends up needing (routes, background jobs, per-chat data, static files).

Open-WebUI stores a function or tool as **one code blob** and cannot import siblings. This protocol is the layer that makes a folder of files behave like one plugin:

1. A **plugin** is a folder with a `plugin.yaml` manifest ([plugin format](plugin-format.md)).
2. A **bundler** turns the folder into the single file Open-WebUI stores, in a fixed order, and can pull function, tool and skill code from any git repo at a pinned commit ([bundling](bundling.md)).
3. A **runtime**, appended to the bundle, makes the function the parent: enabling it installs its tool and skills, disabling or deleting it removes them ([runtime](runtime.md)).
4. **Libraries** are vendored Python blocks a manifest lists under `include:` ([libraries](libraries.md)).
5. A **CLI and a deploy script** check, bundle and deploy one plugin or all of them, from a laptop or CI ([tooling](tooling.md)).

## Why this

Pasting a function into Open-WebUI's admin UI is the quickest way to run it. owpp is worth the extra step when one of these matters:

- **Version control.** The plugins live in git: each change is a commit someone can review, and an earlier version can be deployed again ([deploying an older version](commands/deploy.md#deploying-an-older-version)). An edit in the admin UI replaces the code and keeps no history.
- **Reviewed upgrades of third-party code.** Someone else's function, tool or skill is taken from their repository at a pinned commit instead of copied in. [`owpp pull`](commands/pull.md) moves the pin and lists the files that changed, so the upgrade is a change you review before it runs with admin rights ([`owpp pull`](commands/pull.md)).
- **Shared libraries.** Routes, scheduled jobs, per-chat data, static files and templates come from [libraries](libraries.md), not from a copy pasted into each function.
- **Tests.** [`owpp check`](commands/check.md) finds undefined names before anything is deployed, and [`owpp test`](commands/test.md) runs each plugin's unit tests against a mock Open-WebUI ([testing](testing.md)).
- **Repeatable deploys.** [`owpp deploy`](commands/deploy.md), from a laptop or the [GitHub Action](tooling.md#github-action), makes the instance match the repository, `--dry-run` shows what it would change first, and a plugin that has not changed is left alone ([what a deploy does](commands/deploy.md#what-a-deploy-does)).
- **A function with a tool and skills.** They are installed and removed together ([runtime](runtime.md)), instead of by hand in three places.

It is not worth it when:

- you have a function or two of your own, change them rarely and nobody else reviews them: the admin UI is enough;
- you want to keep editing in the admin UI: the repository is the source of truth, and the next deploy replaces a managed function's code with the repository's;
- you cannot deploy as an admin of the instance: the deploy refuses any other account ([signing in](commands/deploy.md#signing-in)).

## Where to start

| You want to | Start with |
| --- | --- |
| Deploy a first plugin | [getting started](getting-started.md), or [with an AI agent](ai-agents.md) |
| Write a plugin | [creating a plugin](creating.md), then [authoring](authoring.md) and [plugin format](plugin-format.md) |
| Bring a repository or existing functions over | [adopting](adopting.md) |
| Deploy, or set up CI | [tooling](tooling.md) and its command pages |
| Fix an error owpp printed | [troubleshooting](troubleshooting.md) |
| Move to a new owpp version | [upgrading](upgrading.md) |
| Review or contribute a change | [reviewing](reviewing.md), [contributing](contributing.md) |

Everything else (the libraries, the runtime, testing, the environment variables, the examples and the project pages) is in the menu, and short answers are in the [FAQ](faq.md).

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
protocol: "0.3"
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

Written against Open-WebUI **v0.13.4**. API shapes (skills as `files` lists, tool valves, `Functions.get_function_valves_by_id`) were read from that source, and the libraries are tested against stubbed Open-WebUI modules. The examples are deployed to a real v0.13.4 by the [live suite](testing/live.md#the-live-suite), an opt-in end-to-end run, and photographed there ([screenshots](screenshots.md)).

Known limits:

- **The live suite is opt-in, and only on v0.13.4.** Every change runs against the mock; the [live suite](testing/live.md#the-live-suite) runs by hand, on release tags and on pull requests labelled `e2e`.
- **Sign-in fallbacks checked against source, not a live instance.** For a page opened with no session, the guard relies on Open-WebUI's `/api/v1/auths/signin` accepting empty credentials when trusted-header sign-in is configured, and on its login page honouring `?redirect=` ([routes](libraries.md#routes)). Verified in the v0.13.4 source: both hold, with no user name or password needed under a trusted header. The signin route needs `ENABLE_PASSWORD_AUTH` (on by default) and the trusted header to be present.
- **Redis** claims in the `jobs` library are tested with stubs only.
- **No example serves `static/` files or a public mount** (both example pages are templates the function renders). The `static` library and the `public` access level are tested, and `owpp create` writes both, but no example shows them.
