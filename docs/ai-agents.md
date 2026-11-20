# With an AI agent

`owpp` is a command-line tool with plain-text output, so a coding agent (Claude Code, Codex, Cursor and the like) drives it the way a person does: it runs the commands, reads the output and edits the files. Three things help it do that well.

## The owpp skill

[`skills/owpp/`](../skills/owpp/SKILL.md) is an [agent skill](https://agentskills.io): instructions an agent loads when a task touches an Open-WebUI plugin. It walks through each kind of task (create, change, a plugin from git, deploy) with the commands to run and when each is done, and lists the rules the code is held to, such as library names being globals with no import, and the deploy waiting for the user's go-ahead.

Install it with the [skills CLI](https://skills.sh/):

```sh
npx skills add zmnatz/open-webui-plugin-protocol@owpp          # this project
npx skills add zmnatz/open-webui-plugin-protocol@owpp -g       # every project
```

or copy the folder into your agent's skills folder (for Claude Code, `.claude/skills/owpp/` in the repository, or `~/.claude/skills/owpp/`).

## A plugin spec instead of the wizard

`owpp create` asks questions at a terminal, which an agent cannot answer. `owpp create --spec <file>` takes the same answers as a YAML or JSON file (`-` reads stdin), writes the plugin and checks it:

```sh
uvx owpp create --spec notes.yaml
```

The format is in [creating a plugin](creating.md#from-a-spec).

## The documentation, for a model

The site publishes two files for language models, following [llms.txt](https://llmstxt.org/):

- **[`llms.txt`](https://zmnatz.github.io/open-webui-plugin-protocol/llms.txt)**: what owpp is, and every page of this site with its address and a one-line summary.
- **[`llms-full.txt`](https://zmnatz.github.io/open-webui-plugin-protocol/llms-full.txt)**: the whole of Getting started and the Guide as one text file, to give a model in one go.

Both are generated when the site is built, from the same pages, so they never drift from it.

## In a plugins repository's `AGENTS.md`

So that any agent working in the repository finds the skill and the rules, add a few lines to its `AGENTS.md` (or `CLAUDE.md`):

```markdown
## Open-WebUI plugins

The plugins in `plugins/` are built, tested, versioned and deployed with owpp (`uvx owpp`).
Use the owpp skill (`npx skills add zmnatz/open-webui-plugin-protocol@owpp`); without it, read
https://zmnatz.github.io/open-webui-plugin-protocol/llms-full.txt first.
Create plugins with `uvx owpp create --spec <file>`, give every change a new version with
`uvx owpp version <id> patch|minor|major`, and deploy only after `uvx owpp deploy --dry-run`
has been read to me.
```

## No MCP server

There is no MCP server for owpp. An agent that can run commands already has the whole of owpp through its shell, with the same output a person sees, and an MCP server would only wrap those commands again. It would also be a second place to hold deploy credentials, which today come only from the environment. A server would earn its place for an agent with no shell (a chat app with tools, say), which could check plugins or preview a deploy but could not edit a repository either. If that is how you work, [open an issue](https://github.com/zmnatz/open-webui-plugin-protocol/issues).
