# Clear thinking tags

**Adapted from [Clear thinking tags](https://github.com/Haervwe/open-webui-tools/blob/main/filters/clean_thinking_tags_filter.py) by Haervwe** (MIT; the licence is in `NOTICE.md`), written to this repository's conventions with the same behaviour: the header is in `plugin.yaml`, and the debug prints are gone. The list of changes is at the top of `function.py`.

A **filter** with only an outlet. Some models stop while they are still thinking, and the reply is then a Thinking block with no answer after it. This filter makes that thinking the answer, so the chat shows it as the reply:

- in Open-WebUI 0.12 and later, where a reply is a list of `output` items, a list that ends in reasoning has that item turned into a message, and `content` is set to match;
- in older replies, an unfinished `<details type="reasoning" done="false">` block in the text is replaced by its text, unquoted.

A reply with an answer after its reasoning is left alone. No valves. Global.

## Test

- `owpp check clear_thinking_tags` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines.
- `owpp bundle clear_thinking_tags out.py` writes the deployed code to read or diff.
- `owpp test clear_thinking_tags` runs `tests/` against a mock Open-WebUI (docs/testing.md).
- On a live Open-WebUI: with a model that sometimes stops while thinking, ask until a reply has a Thinking block and nothing after it. With the filter on, the thinking text is the reply. The live suite (`tools/screenshots/run.py --live`) and the screenshots do this with the scripted model.

## Deploy

- Function type: **filter**, global.
- `owpp deploy --only clear_thinking_tags --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
