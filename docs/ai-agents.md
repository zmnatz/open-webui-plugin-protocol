# With an AI agent

`owpp` is a command-line tool with plain-text output. Thus a coding agent (Claude Code, Codex, Cursor or a similar agent) uses it as a person does. The agent runs the commands, reads the output and edits the files. Three things help it to do this well: two skills and a plugin spec.

## The owpp skill

[`skills/owpp/`](../skills/owpp/SKILL.md) is an [agent skill](https://agentskills.io). An agent loads these instructions when a task has an Open-WebUI plugin in it. For each type of task (create, change, a plugin from git, deploy), the skill gives the commands to run and when the task is done. It also lists the rules for the code. Examples are that each file imports what it uses, and that the deploy waits until the user says to start.

To install it with the [skills CLI](https://skills.sh/), run one of these commands:

```sh
npx skills add zmnatz/open-webui-plugin-protocol@owpp          # this project
npx skills add zmnatz/open-webui-plugin-protocol@owpp -g       # every project
```

You can also copy the folder into the skills folder of your agent. For Claude Code, that is `.claude/skills/owpp/` in the repository, or `~/.claude/skills/owpp/`.

## The test-existing-plugin skill

[`skills/test-existing-plugin/`](../skills/test-existing-plugin/SKILL.md) writes the tests for a function or plugin that already works. The code can be in Open-WebUI, in a `.py` file, in the repository of someone else, or in a plugin that has no tests.

- It brings the code in with [`owpp import`](commands/import.md).
- It lists each method, valve and branch. For each one, it writes a test on the [test harness](testing/harness.md) that records what the code does now.
- Where the code does something that its author does not want, it reports a finding. It does not change the code.
- It writes [live tests](testing/live.md#live-tests-in-your-repository) for what the harness cannot reach: the page in a browser, a deploy to a running Open-WebUI, and several workers. They run over the API or in the browser with Playwright. [`owpp live`](commands/live.md) runs them on a throwaway Open-WebUI, with aimock as its models.
- In this repository, it also takes the example's [screenshots](screenshots.md).

```sh
npx skills add zmnatz/open-webui-plugin-protocol@test-existing-plugin
```

## A plugin spec instead of the wizard

`owpp create` asks questions at a terminal, and an agent cannot answer them. `owpp create --spec <file>` takes the same answers as a YAML or JSON file (`-` reads stdin). It writes the plugin and checks it:

```sh
uvx owpp create --spec notes.yaml
```

[Creating a plugin](creating.md#from-a-spec) gives the format.

## The documentation, for a model

The site publishes two files for language models, as [llms.txt](https://llmstxt.org/) specifies:

- **[`llms.txt`](https://zmnatz.github.io/open-webui-plugin-protocol/llms.txt)**: what owpp is, and each page of this site with its address and a one-line summary.
- **[`llms-full.txt`](https://zmnatz.github.io/open-webui-plugin-protocol/llms-full.txt)**: all of the Getting started, Guide and Commands pages as one text file, to give to a model at one time.

The site build generates both files from the same pages, so they always agree with the site.

## In a plugins repository's `AGENTS.md`

To let all agents in the repository find the skill and the rules, add these lines to its `AGENTS.md` (or `CLAUDE.md`):

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

owpp has no MCP server. An agent that can run commands already has all of owpp through its shell, with the same output that a person sees. An MCP server only wraps those commands again. It is also a second place to keep deploy credentials, which now come only from the environment.

A server is useful only for an agent with no shell, for example a chat app with tools. That agent can check plugins or preview a deploy, but it cannot edit a repository. If you work in this way, [open an issue](https://github.com/zmnatz/open-webui-plugin-protocol/issues).
