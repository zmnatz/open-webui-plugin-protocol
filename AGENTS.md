## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (zmnatz/open-webui-plugin-protocol), using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default triage labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Working an issue

- **`documentation` label:** review the docs the change touches, and the pages around them, for redundancy (the same thing explained in full in more than one place: keep one, link to it from the others) and stale information (anything that no longer matches the code). Do it without being asked.
- **Commit messages** start with a conventional-commit type chosen from the issue's labels. The mapping is in `docs/agents/triage-labels.md`.
