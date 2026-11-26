# Tests for plugins that already work

Two plugins repositories, each one plugin and the tests the [`test-existing-plugin`](../../skills/test-existing-plugin/SKILL.md) skill wrote for it, without reading the tests that already existed. What they found, and how many planted bugs they caught: [testing a plugin that already works](https://zmnatz.github.io/open-webui-plugin-protocol/testing/existing-plugins/).

| Folder | The plugin | Taken with |
| --- | --- | --- |
| `better-banners/` | Classic298's [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) 1.0.4, an event function whose behaviour is mostly a script on the chat page | its file from git (`function: file: event.py`) |
| `excalidraw/` | this repository's [Excalidraw](../plugins/excalidraw) example: a filter, a tool, an editor page in the Artifacts panel | the whole plugin from git (`plugin: true`) |

Each folder is laid out as a plugins repository: `plugins/<id>/tests/` for the tests against the mock, and `live/` for the tests on a real Open-WebUI (with, for Excalidraw, the aimock model that calls the tool and the compose file that turns on what the panel needs). From one of the folders, in a checkout of this repository:

```sh
uv run owpp test                      # against the mock (fetches the plugin from git)
uv run owpp live                      # on a throwaway Open-WebUI in Docker
```

`mutants.py` in each folder puts one bug at a time into the plugin and runs every test against it: start the stack with `uv run owpp live --up`, export the variables it prints, then `uv run python mutants.py` (or name some of its bugs). Its results go to `mutants.json`, which git ignores.
