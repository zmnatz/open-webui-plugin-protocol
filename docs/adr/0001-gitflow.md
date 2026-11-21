# Gitflow, with merge commits into main

Work merges into `develop`, and `main` moves only when a release or hotfix branch merges into it, so `main` and the docs site published from it are always the latest release. Changes squash into `develop`, which keeps its history one commit per change, but anything that goes into `main`, and `main` back into `develop`, is a merge commit: a squash would give `main` commits that `develop` never has, and each later release would conflict with them. That is why `main` has no linear-history rule while the rest of the history mostly looks linear.

## Considered Options

- **One branch, a release is a tag on it** (until 0.4.0): simplest, but unreleased changes reached the docs site and `main` before they shipped.
- **`develop` without release branches**: a release would be a pull request from `develop` to `main`, but it gives no place to finish a release while other changes keep merging.
