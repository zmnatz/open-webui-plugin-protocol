# Testing a plugin

A plugin's tests are its **spec**: each one names a behaviour in the plugin's terms (pages, valves, chats, replies) and proves it on the test harness, the real Open-WebUI in the test process (run `owpp test` on Python 3.12). Each docstring's **By hand** steps are how a person sees the same behaviour on a live instance, and the README's `## Test` list is built from them. The full guide is at https://zmnatz.github.io/open-webui-plugin-protocol/testing/: [writing a test](https://zmnatz.github.io/open-webui-plugin-protocol/testing/writing/), [recipes for each kind of plugin](https://zmnatz.github.io/open-webui-plugin-protocol/testing/kinds/) (filters, actions, pipes, tools, events, pages, installers, code from git), and [the harness's reference](https://zmnatz.github.io/open-webui-plugin-protocol/testing/harness/).

## Steps

1. **List the behaviours.** One per sentence of the README, one per valve, one per branch in the code (each early `return` is one): what happens, and when it is left alone. Done when every valve and every branch is on the list.
2. **For each behaviour, write the test first and see it go red**: `uvx --from 'owpp[test]' owpp test <id> -- -k <name>`. Name it as a sentence about the plugin (`test_a_message_without_an_image_stays_with_its_model`), and give it the docstring:

   ```python
   def test_admins_are_left_alone_unless_it_is_turned_on_for_them(owui, plugin):
       """By default only users who are not admins are rerouted; `enabled_for_admins` turns it on
       for admins.

       By hand: send a picture as an admin. The chosen model answers. Turn enabled_for_admins on
       and send it again: the vision model answers.
       """
   ```

   The first paragraph says what it checks. **By hand** says where to click, what to set and what you should see on a live Open-WebUI; when the behaviour cannot be reached by hand, it says why ("not repeatable on Open-WebUI 0.13, which no longer writes replies this way").
3. **Make it green**, through the harness rather than around it: `plugin.inlet(body, user=, model=)`, `plugin.outlet(...)`, `owui.set_valves(id, ...)`, `owui.tool(id).call(...)`, `owui.client(user).get(...)`, `owui.disable(id)`. A helper called directly skips the guards and the runtime the real plugin goes through. Pure logic with no Open-WebUI in it can be tested directly: `plugin_source(plugin_dir)` (from `owpp.testing`) imports the plugin's files as modules, each with its own `shared` and libraries, as `.shared`, `.function` and `.tool`.
4. **Write the README's `## Test` list** from the By hand steps: the `owpp check`, `owpp bundle` and `owpp test` lines `owpp create` wrote, then one line of live checks.

Done when every behaviour on the list has a test with both paragraphs, `owpp test <id>` passes, and `owpp check <id> --strict` reports no `FAIL` and no `warn`.

## What the harness does not reach

The model is aimock (set `owui.model_reply`, add ids with `owui.serve_model`; it needs Bun, Node or Docker); `owui.send(user, text)` runs Open-WebUI's whole chat pipeline (its filters, the model, the outlets); the harness fakes the socket (`owui.emitted`), `__event_emitter__` and `__event_call__` (`owui.chat_events`), and has no sign-in provider or browser: test those in By hand or with `owpp live`. Rows in `owui.tools`, `owui.models` and the other tables are copies: change them through `owui.set_valves`, `owui.set_tool_valves`, Open-WebUI's models in `owui.run(...)`, or its API with `owui.client(owui.admin)`; compare grants with `grants(row)` from `owpp.testing`. A package Open-WebUI's slim image lacks stops the load with its name and pin: add it to the repository's test dependencies.
