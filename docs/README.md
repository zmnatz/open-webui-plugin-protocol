# Open-WebUI plugin protocol

owpp writes, tests and deploys Open-WebUI **plugins** from a git repository. A plugin is a function (the parent) with an optional tool and skills, which are installed and removed together. Its [libraries](libraries.md) supply what most plugins need: routes, background jobs, per-chat data and static files.

Open-WebUI stores a function or a tool as **one block of code**, and that code cannot import other files. This protocol makes a folder of files work as one plugin:

1. A **plugin** is a folder with a `plugin.yaml` manifest ([plugin format](plugin-format.md)).
2. The **bundler** makes the folder into the one file that Open-WebUI stores, in a fixed order. It can take function, tool and skill code from a git repository at a pinned commit ([bundling](bundling.md)).
3. The **runtime** goes at the end of the bundle and makes the function the parent. When you enable the function, it installs its tool and skills. When you disable or delete the function, it removes them ([runtime](runtime.md)).
4. **Libraries** are built-in code that owpp links into the bundle. A manifest asks for one with `include:`, or a file in the plugin turns it on ([libraries](libraries.md)).
5. The **CLI** and its **GitHub Action** check, bundle and deploy one plugin or all of them, from a laptop or from CI ([tooling](tooling.md)).

## Why this

The quickest way to run a function is to paste it into Open-WebUI's admin UI. owpp is worth the extra step when one of these is important to you:

- **Version control.** The plugins are in git. Each change is a commit that someone can review, and you can deploy an earlier version again ([deploying an older version](commands/deploy.md#deploying-an-older-version)). An edit in the admin UI replaces the code and keeps no history.
- **Reviewed upgrades of third-party code.** owpp takes someone else's function, tool or skill from their repository at a pinned commit, and does not copy it. [`owpp pull`](commands/pull.md) moves the pin and lists the files that changed. You review that change before the code runs with admin rights.
- **Shared libraries.** Routes, scheduled jobs, per-chat data, static files and templates come from [libraries](libraries.md), not from a copy in each function.
- **Tests.** [`owpp check`](commands/check.md) finds undefined names before you deploy. [`owpp test`](commands/test.md) runs each plugin's unit tests against a mock Open-WebUI. [`owpp live`](commands/live.md) runs a repository's live tests on a throwaway Open-WebUI in Docker, over its API and in the browser ([testing](testing.md)). [`owpp import`](commands/import.md) brings in a function that already works, and an agent can write its tests ([a plugin that already works](testing/existing-plugins.md)).
- **Repeatable deploys.** [`owpp deploy`](commands/deploy.md) makes the instance match the repository, from a laptop or from the [GitHub Action](tooling.md#github-action). `--dry-run` shows what it will change first. A plugin that did not change stays as it is ([what a deploy does](commands/deploy.md#what-a-deploy-does)).
- **A function with a tool and skills.** The runtime installs and removes them together ([runtime](runtime.md)). You do not do it by hand in three places.

It is not worth the extra step when:

- You have one or two functions of your own, you change them rarely and nobody else reviews them. The admin UI is sufficient.
- You want to continue to edit in the admin UI. The repository is the source of truth: the next deploy replaces a managed function's code with the repository's code.
- You cannot deploy as an admin of the instance. The deploy refuses all other accounts ([signing in](commands/deploy.md#signing-in)).

## Where to start

| You want to | Start with |
| --- | --- |
| Deploy a first plugin | [getting started](getting-started.md), or [with an AI agent](ai-agents.md) |
| Write a plugin | [creating a plugin](creating.md), then [authoring](authoring.md) and [plugin format](plugin-format.md) |
| Bring a repository or existing functions over | [adopting](adopting.md), and [`owpp import`](commands/import.md) |
| Test a plugin, or one that already works | [testing](testing.md), [live tests](testing/live.md), [a plugin that already works](testing/existing-plugins.md) |
| Deploy, or set up CI | [tooling](tooling.md) and its command pages |
| Fix an error that owpp printed | [troubleshooting](troubleshooting.md) |
| Move to a new owpp version | [upgrading](upgrading.md) |
| Review or contribute a change | [reviewing](reviewing.md), [contributing](contributing.md) |

The menu has all the other pages: the libraries, the runtime, testing, the environment variables, the examples and the project pages. The [FAQ](faq.md) has short answers.

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
protocol: "0.7"
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

- **Reproducible.** A bundle depends only on the plugin folder and the pinned git commits it names. Each library goes into the bundle as owpp ships it. The bundler removes only the library's imports and fills in its data.
- **Reviewed upgrades.** A manifest names remote code by its full commit SHA, never by a branch or tag, because that code runs inside Open-WebUI with admin rights. `owpp pull` moves the SHA to the latest commit, as a change that you review and commit.
- **Owned objects only.** The deploy marks each function it makes (`meta.managed_by`). It updates or deletes only the marked functions, and never touches a function made by hand.
- **No surprises on disable.** When you disable a function, all that it installed is removed or stops: tools, skills, routes and background jobs.

## Status and limits

owpp is written against Open-WebUI **v0.13.5**. It started on v0.13.4, and it continues to support that version. The API shapes (skills as `files` lists, tool valves, `Functions.get_function_valves_by_id`) come from that source. The libraries are tested against stubbed Open-WebUI modules. On each change, the [live suite](testing/live.md#this-repositorys-live-suite) deploys the examples to a real v0.13.5 and runs them end to end. It also takes their [screenshots](screenshots.md) there.

Known limits:

- **The live suite runs on v0.13.5 only.** In place of a real model and the services that the examples call, it uses aimock and fixed files ([the live suite](testing/live.md#this-repositorys-live-suite)). You check a newer Open-WebUI, or the behaviour of a real model, by hand.
- **The sign-in fallbacks are checked against the source, not against a live instance.** For a page opened with no session, the guard of the [routes](libraries.md#routes) library relies on two things in Open-WebUI:
    - `/api/v1/auths/signin` accepts empty credentials when trusted-header sign-in is configured. This route also needs `ENABLE_PASSWORD_AUTH` (on by default) and the trusted header.
    - Its login page obeys `?redirect=`.

    Both are true in the v0.13.4 and v0.13.5 source. Under a trusted header, they need no user name or password.
- **Redis** claims in the `jobs` library are tested with stubs only.
- **No example serves `static/` files or has a public mount.** The examples' pages are all templates that the function renders. The `static` library and the `public` access level have tests, and `owpp create` writes both, but no example shows them.
