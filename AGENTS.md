## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (zmnatz/open-webui-plugin-protocol), using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Working an issue

- **Example plugins:** adding or changing one in `examples/plugins/` (adapting someone else's function, its tests, screenshots, the live suite, its docs) follows `docs/agents/examples.md`.
- **`documentation` label:** review the docs the change touches, and the pages around them, for redundancy (the same thing explained in full in more than one place: keep one, link to it from the others) and stale information (anything that no longer matches the code). Do it without being asked. Write the changed prose in the style below.
- **Branches:** start from `develop` and open the pull request into `develop`, not `main`. Releases and hotfixes follow `docs/contributing.md#branches`.
- **Commit messages** start with a conventional-commit type chosen from the issue's labels. The mapping is in `docs/agents/triage-labels.md`.

## Writing docs

Write new or changed prose in `docs/` in Simplified Technical English (ASD-STE100's writing rules, not its restricted dictionary):

- One meaning and one instruction in each sentence, in the active voice.
- At most 25 words in a description, and 20 in a procedure.
- Numbered steps, with a caution or warning before the step it applies to.
- One term for one meaning. Keep `GLOSSARY.md` terms and technical names (`owpp`, `plugin.yaml`, valve, commands, flags, keys) as they are.
- One full explanation of each thing, with links from the other pages.

The full rules are in `docs/contributing.md#writing-the-guide`.
