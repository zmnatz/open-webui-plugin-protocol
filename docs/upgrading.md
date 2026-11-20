# Upgrading owpp

The runtime and libraries are copied into every bundle, so a new owpp changes the code you deploy. Upgrade on a branch, check it, review the report of a dry run, and deploy from the merged change.

## Steps

1. **Move the pin.** Change the version wherever you run owpp: `uvx owpp@0.2.1`, `uv tool install owpp==0.2.1`, or the action's `uses: zmnatz/open-webui-plugin-protocol@v0.2.1`.
2. **Migrate the manifests.** See what would change, then write it:

   ```sh
   uvx owpp@0.2.1 migrate --dry-run
   uvx owpp@0.2.1 migrate
   ```

   `migrate` rewrites only what each version step changes, keeps comments and layout, and lists every `plugin.yaml` it writes. A manifest already at the current version is left alone. Pass ids to migrate only some plugins.
3. **Check.** `uvx owpp@0.2.1 check --strict` bundles every plugin as the deploy would. `check` notes any manifest still on an older protocol and warns about one with no `protocol:` key; `--strict` makes that warning fail.
4. **Dry run.** `owpp deploy --dry-run` against your instance shows which functions, tools and skills the new bundles would update.
5. **Commit** the pin and the manifest changes together, and deploy.

## 0.2 -> 0.3

- **Manifests:** `source: track:` is now `branch:` or `tag:`, whichever the name is in the repository, as other tools that follow a git ref write it. `owpp migrate` asks the repository (`git ls-remote`) and rewrites the key, keeping its value and comment, and sets `protocol: "0.3"`. When it cannot reach the repository, or the name is neither, it says so and leaves that manifest: write `branch:` or `tag:` yourself. A 0.2 manifest with `track:` still works with owpp 0.3 until it is migrated; a 0.3 manifest with `track:` is refused.
- **Renamed:** `owpp sync` is now `owpp pull`, and `owpp deploy --dry-run --sync` is now `--dry-run --latest`. The action's `sync` input is now `latest`. The old names are removed, not aliased: change your scripts and workflows.

## 0.1 -> 0.2

- **Manifests:** add `protocol: "0.2"`. That is the whole step (`owpp migrate` does it): everything else 0.2 added is optional. A manifest with no key is read as 0.1, so it still deploys, but `owpp check` warns and `owpp check --strict` fails until it has one.
- **First deploy:** a function that takes its code from a `source:` updates once, because the deploy now records the upstream commit in its meta (`meta.sources`). Its valves and active/global state are kept.
- **New refusals:** `owpp deploy` refuses to put back an older version than the instance runs, unless given `--force` (action input `force`). If a dry run warns about it, check that you are on the right branch.

The full list of what changed is in the [changelog](../CHANGELOG.md).

## How versions relate

`protocol:` in `plugin.yaml` is a quoted major.minor that tracks owpp's major.minor. It changes only when a release changes what a manifest key means or takes one away, so a patch release never needs a migration. An owpp older than a manifest's protocol refuses it: upgrade owpp first. See [the protocol key](plugin-format.md#protocol).
