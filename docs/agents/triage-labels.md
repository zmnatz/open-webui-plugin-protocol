# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Edit the "Label in our tracker" column to match whatever vocabulary you actually use.

## Type labels and commit messages

An issue's type label picks the conventional-commit type of its commit message (also on the [contributing page](../contributing.md#commit-messages)):

| Label | Commit type |
| --- | --- |
| `enhancement` | `feat` |
| `bug` | `fix` |
| `documentation` (alone) | `docs` |
| `refactor` | `refactor` |
| `test` | `test` |
| `chore` | `chore` / `ci` / `build` |
| `breaking` | add `!` to the type and a `BREAKING CHANGE:` footer |

`documentation` alongside another type label means the docs review applies (see AGENTS.md), not that the commit is `docs`.
