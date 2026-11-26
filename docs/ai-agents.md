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

## The test-existing-plugin skill

[`skills/test-existing-plugin/`](../skills/test-existing-plugin/SKILL.md) writes the tests for a function or plugin that already works: one pasted into Open-WebUI, a `.py` file, someone else's repository, or a plugin with no tests yet. It brings the code in with [`owpp import`](commands/import.md), lists every method, valve and branch, and writes a test for each against [the mock](testing/mock.md) that pins what the code does now. Where the code does something its author would not want, it reports a finding rather than changing the code. It also writes [live tests](testing/live.md#live-tests-in-your-repository) for what only a real Open-WebUI does, over its API or in the browser with Playwright, run by [`owpp live`](commands/live.md) on a throwaway Open-WebUI with aimock as its models. In this repository it also takes the example's [screenshots](screenshots.md).

```sh
npx skills add zmnatz/open-webui-plugin-protocol@test-existing-plugin
```

### Tried on Better Banners

To see what the skill gives, an agent ran it on Classic298's original [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) (1.0.4, commit `917c88f`), and the result was set beside the tests of [Page Banners](examples/page_banners.md), this repository's variant of it, which were written by hand while adapting it. The agent did not read Page Banners' tests until its own were done. In a new plugins repository, `owpp import <the folder's URL>`, then the skill's steps, on Open-WebUI v0.13.5:

| | Page Banners (adapted, tests written with it) | Better Banners (original, the skill) |
| --- | --- | --- |
| Against the mock | 11 tests | 17 (12 tests, one with 5 cases), all passing at the first run |
| On a real Open-WebUI | that it is deployed and active; 4 screenshot scripts that open the page but assert little | 10 live tests in the browser, passing at the first run (about 70 s) |
| Each one goes red when its expected value is changed | not checked | all 27 |
| Findings | | none in Better Banners; one in `owpp live`, fixed (below) |

The two sets test different things. Page Banners' tests are mostly about the adaptation: the script as an `assets/` file wrapped once in a `try`, a stylesheet in `/static/custom.css`, and names that cannot collide with the original's. The skill's go further into what the plugin itself does:

- **Against the mock**, beyond what Page Banners' tests cover: the 1.0.2 fragment dropped on upgrade, another deleted plugin's fragment withdrawn, the weak `W/` ETag a proxy sends back, the `Cache-Control` header, both ends of every valve's range, a stale block in the `loader.js` on disk not served twice, and events other than a banner edit sending nothing.
- **On a real Open-WebUI**, nothing of which was asserted before: the banners at the top of an open chat (in `#chat-pane`), or right above the message input with `position: bottom`. Not on the new-chat screen, where Open-WebUI shows its own (so each banner shows once). Seen by a user who is not an admin. A new banner reaching an open tab without a reload. The pill keeping the banners folded after a reload, with their count and the highest level's colour. A dismissal remembered in Open-WebUI's own `dismissedBannerIds`, and no close button on a banner that is not dismissible. Markdown rendered, and `<script>`, `onerror` and `javascript:` links that cannot run. The banner changing with the page's language. No banners, and no block in `/static/loader.js`, once the function is disabled.

Page Banners' By hand steps say the pill "stays folded after a reload". Until this experiment, only the skill's live tests checked that.

The finding was in `owpp live`: each browser page signed in again on the login page, and Open-WebUI answers a sign-in with 429 after a few a minute, so a suite with several browser tests failed in its fixtures. The `admin` and `user` pages now share one sign-in per account for the run ([the fixtures](testing/live.md#the-fixtures)).

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
