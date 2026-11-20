# FAQ

Short answers for newcomers. Each one links to the page that covers it in full.

## Do I need to fork Open-WebUI?

No. A plugin is deployed as an ordinary Open-WebUI function, through the admin API of an unmodified instance, and that function installs its own tool and skills from inside Open-WebUI. All you need is a way to sign in as an admin. See [install](install.md#requirements) and [runtime](runtime.md).

## Can I keep my existing functions?

Yes. A deploy only updates or deletes functions it marked itself (`meta.managed_by`); a function made by hand in the UI is never touched. To bring one under git, give its folder the id it already has: the first deploy updates it in place and marks it, keeping its valves and its active/global state. See [adopting](adopting.md#existing-functions-pasted-into-the-ui) and [the ownership marker](commands/deploy.md#the-ownership-marker).

## What happens when I disable or delete a plugin?

In Open-WebUI, disabling or deleting the function removes what it installed: its tool and skills go, its routes and static files answer 404, and its background jobs stop. See [runtime](runtime.md) and [libraries](libraries.md#routes).

The next deploy leaves a disabled function disabled, unless its manifest says `global: true`, which keeps it active on every run. A function deleted in the UI whose folder is still in the repository is created again. To remove a plugin for good, delete its folder: the next full deploy deletes the function. `owpp deploy --only` never deletes, and deleting more than half of the managed functions in one run needs `--force-prune`. See [what a deploy does](commands/deploy.md#what-a-deploy-does).

## Why are version bumps reviewed?

Because what you deploy runs inside Open-WebUI with admin rights.

- **Code from another repository** is pinned to a full commit SHA, never a branch or tag, so it changes only when `owpp pull` moves the SHA. That move is a change to `plugin.yaml` that you review, with the upstream diff it links to, and commit. See [`owpp pull`](commands/pull.md).
- **owpp itself** is pinned the same way: the runtime and libraries are copied into every bundle, so a new owpp changes your deployed code. See [upgrading](upgrading.md).
- **Your own plugins** get a new version with every change (`owpp check --since` fails on one without), so the deploy report says what moved, and a deploy refuses to go back a version without `--force`. See [versions](commands/version.md#versions).

## Does it work without CI?

Yes. Every command runs from a laptop: `owpp check`, `owpp test`, then `owpp deploy` with the instance's URL and an admin credential in the environment. The [GitHub Action](tooling.md#github-action) runs the same check and deploy on every push; it is a convenience, not a requirement. Without it, nothing checks a change for you, so run `owpp check` and `owpp deploy --dry-run` before you deploy. See [getting started](getting-started.md#5-deploy).
