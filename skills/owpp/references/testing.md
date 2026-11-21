# Testing a plugin

A plugin's tests are its **spec**: each one names a behaviour in the plugin's terms (pages, valves, chats, replies) and proves it against the mock Open-WebUI. Each docstring's **By hand** steps are how a person sees the same behaviour on a live instance, and the README's `## Test` list is built from them. Mock reference (fixtures, every call, what it cannot do): https://zmnatz.github.io/open-webui-plugin-protocol/testing/

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
3. **Make it green**, through the mock rather than around it: `plugin.inlet(body, user=, model=)`, `plugin.outlet(...)`, `owui.set_valves(id, ...)`, `owui.tool(id).call(...)`, `owui.client(user).get(...)`, `owui.disable(id)`. A helper called directly skips the guards and the runtime the real plugin goes through.
4. **Write the README's `## Test` list** from the By hand steps: the `owpp check`, `owpp bundle` and `owpp test` lines `owpp create` wrote, then one line of live checks.

Done when every behaviour on the list has a test with both paragraphs, `owpp test <id>` passes, and `owpp check <id> --strict` reports no `FAIL` and no `warn`.

## When the mock lacks something

A name the mock does not implement still imports, and calling it raises `NotImplementedError` naming it. Code that needs it is then out of the mock's reach: test what you can, and put the rest in By hand. In the owpp repository itself, add the name to `src/owpp/testing/mock.py`, with a test in `tests/test_mock.py`.
