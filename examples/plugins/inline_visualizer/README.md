# Inline Visualizer

[Classic298/open-webui-plugins `inline-visualizer-v2`](https://github.com/Classic298/open-webui-plugins/tree/main/inline-visualizer-v2): renders interactive HTML/SVG inline in chat. This folder only pins the upstream commit (`plugin.yaml`); the tool and the `visualize` skill are fetched from it at deploy time.

Enabling the function (it is global) installs the tool `inline_visualizer` and the skill `visualize`; disabling or deleting it removes them.

## Settings the deploy cannot make

- Admin Settings > General > **Skill Read Limit**: raise to 50000 or more (default 20000 can cut the skill short).
- Each user: Settings > Interface > **iframe Sandbox Allow Same Origin**, or live rendering shows "Streaming visualization unavailable".
- The tool's valves (`security_level`, `chime`) are changed in Workspace > Tools; the deploy does not set them.

## Upgrading

Read the upstream diff between the pinned `ref` and the new commit (this code runs in Open-WebUI with admin rights), then change `ref` in `plugin.yaml` to the new full commit SHA.

## Test

- `owpp check inline_visualizer` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines (the function and any tool it embeds).
- `owpp bundle inline_visualizer out.py` writes the deployed code to read or diff.
- `owpp test inline_visualizer` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI: enable the function: the log shows the tool and skill being installed; disable it and they are removed.

## Deploy

- Function type: **filter (generated global parent)**.
- `owpp deploy --only inline_visualizer --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
