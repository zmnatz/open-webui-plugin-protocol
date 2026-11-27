# FAQ

Short answers for new users. Each answer links to the page that has the full explanation.

## Do I need to fork Open-WebUI?

No. owpp deploys a plugin as an ordinary Open-WebUI function, through the admin API of an unmodified instance. That function then installs its own tool and skills from inside Open-WebUI. You need only a way to sign in as an admin. See [install](install.md#requirements) and [runtime](runtime.md).

## Can I keep my existing functions?

Yes. A deploy updates or deletes only the functions that it marked (`meta.managed_by`). It never touches a function made by hand in the UI. To move a function into git, give its folder the id that the function already has. The first deploy then updates the function and marks it, and keeps its valves and its active and global state. See [adopting](adopting.md#existing-functions-pasted-into-the-ui) and [the ownership marker](commands/deploy.md#the-ownership-marker).

## What happens when I disable or delete a plugin?

When you disable or delete the function in Open-WebUI, the runtime removes what the function installed. Its tool and skills are removed, its routes and static files answer 404, and its background jobs stop. See [runtime](runtime.md) and [libraries](libraries.md#routes).

The next deploy does not enable a disabled function, unless its manifest says `global: true`. If you delete a function in the UI and its folder is still in the repository, the next deploy creates it again. To remove a plugin permanently, delete its folder: the next full deploy deletes the function. [What a deploy does](commands/deploy.md#what-a-deploy-does) gives the limits on deletes.

## Why are version bumps reviewed?

Because the code that you deploy runs inside Open-WebUI with admin rights.

- **Code from another repository** is pinned to a full commit SHA, never to a branch or tag. It changes only when [`owpp pull`](commands/pull.md) moves the SHA. You review that change to `plugin.yaml`, with the upstream diff that it links to, and commit it.
- **owpp itself** is pinned in the same way. owpp copies the runtime and the libraries into each bundle, so a new owpp changes your deployed code. See [upgrading](upgrading.md).
- **Your own plugins** get a new version with each change, and [`owpp check --since`](commands/check.md) fails on a change without one. Thus the deploy report shows what changed. A deploy refuses to go back a version without `--force`. See [versions](commands/version.md#versions).

## Does it work without CI?

Yes. Each command runs from a laptop: [`owpp check`](commands/check.md), [`owpp test`](commands/test.md), then [`owpp deploy`](commands/deploy.md). The deploy needs the URL of the instance and an admin credential in the [environment](environment-variables.md). On each push, the [GitHub Action](tooling.md#github-action) runs the same check and deploy, but you do not have to use it. Without it, nothing checks a change for you. Thus run `owpp check` and `owpp deploy --dry-run` before you deploy. See [getting started](getting-started.md#5-deploy).
