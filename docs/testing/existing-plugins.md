# Testing a plugin that already works

A function pasted into Open-WebUI, or someone else's plugin, already works: its tests pin what it does now. The [`test-existing-plugin` skill](../ai-agents.md#the-test-existing-plugin-skill) has an agent write them: it brings the code in with [`owpp import`](../commands/import.md), lists every method, valve, branch and field, writes a test against [the mock](mock.md) for each, and [live tests](live.md) for what only a real Open-WebUI does. This page is what that gave on two plugins, and how many bugs the tests then caught.

Both are in the repository as plugins repositories, with their tests and a script that plants the bugs: [`examples/existing-plugins/`](https://github.com/zmnatz/open-webui-plugin-protocol/tree/develop/examples/existing-plugins).

| | Better Banners | Excalidraw |
| --- | --- | --- |
| The plugin | Classic298's [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) 1.0.4: an event function whose behaviour is mostly a script on the chat page | This repository's [Excalidraw](../examples/excalidraw.md): a filter, a tool and an editor page in the Artifacts panel |
| Brought in with | `owpp import <the folder's URL>` | the folder, its tests removed: `owpp import --instance` could not bring it back then (see [what the experiments found](#what-the-experiments-found)) |
| Tests against the mock | 17 (13 tests), all passing at the first run | 34 (26 tests), 33 passing at the first run (two expected status codes were wrong) |
| Live tests | 11, in the browser | 7, in the browser and over the API, after four rounds of fixing the tests |
| Tests that already existed | [Page Banners](../examples/page_banners.md)' (a variant of it): 11 against the mock, none live | Excalidraw's own: 50 (41 tests) against the mock, 4 live |

Everything ran on Open-WebUI v0.13.5, with [`owpp live`](../commands/live.md).

## Did the tests catch bugs?

A test that goes red when its expected value changes can fail, which is not the same as catching a bug. So bugs a developer could plausibly write were put into each plugin, one at a time: each was deployed to the live Open-WebUI and run against every test.

| | Better Banners: 16 bugs | Excalidraw: 19 bugs |
| --- | --- | --- |
| Caught against the mock | 4 | 14 |
| Caught live | 12 | 6 |
| Caught by either | **14** | **16** |
| Caught by the tests that already existed, against the mock | (other code) | 13 |

The two kinds of test catch different things, and a plugin needs the kind its behaviour lives in:

- **Against the mock**: everything on the server. Excalidraw's tool, its outlet, its routes and their tokens are Python, and the mock caught 14 of their 15 bugs.
- **Live**: everything on the page. Better Banners is almost all a script in the browser, and the mock caught only its 4 server-side bugs; the live tests caught 12, among them dismissals stored under the wrong key, `position: bottom` ignored, collapsing not saved, and `javascript:` links let through. Excalidraw's editor saving without saying which editor it is, and polling once and stopping, were caught only live.

### What the tests missed

| Plugin | Bug | Why it was missed |
| --- | --- | --- |
| Better Banners | the sanitizer keeps `onclick` | The skill tested the behaviours it listed, and "a field shows hostile markup safely" was not one: its HTML test used an `<img onerror>`, which the sanitizer drops anyway. |
| Better Banners | a banner's title set as HTML | Every test banner had an empty title. |
| Excalidraw | the `SESSION_TOKEN_HOURS` valve ignored (always 1 hour) | No test of the token's lifetime. |
| Excalidraw | the editor reapplies its own saves | Only visible as a flicker. |
| Excalidraw | the editor applies a change from the model while the user is mid-stroke | Needs a stroke and a change to land together. |

One more live test, of markup in every field, caught both Better Banners bugs; the skill now asks for that test for each field a plugin shows to a person. Excalidraw's own tests missed the token bug too: their test sets the valve to 1, the very value the bug hard-codes, so the skill now asks for a valve value no constant in the code has. The two editor bugs are timing, which neither set tested.

Excalidraw's own tests, set against the same 19 bugs, caught 13 against the mock. They missed `show` replacing the drawing instead of adding to it, an unchecked chat id, the token bug, and every bug in the editor page. They cover what the skill's do not: the self-hosted build, grants an earlier runtime set, a tool someone made by hand with the same id. Their live tests were not run against the bugs; they check that the model is offered the tool and that the chat page runs it, not what the editor does.

## What the experiments found

None of the tests found a bug in either plugin: every prediction about what the code does held, except two status codes Excalidraw answers 404 to (someone else's chat, and one shared read-only), so as not to say the chat exists. They found these, in owpp and in the tests:

- **`owpp live` signed in again for every browser test**, and Open-WebUI refuses more than a few sign-ins a minute (429), so a suite with several browser tests failed in its fixtures. Fixed: each account signs in once per run ([the fixtures](live.md#the-fixtures)).
- **`owpp import <file>` of a plugin that uses the Shared Assets Protocol** made a folder `owpp check` refuses: the protocol's byte-identical block replaces a route in `app.routes`, which owpp forbids in a plugin's own code (imported from git, the same code is not checked that way). Fixed: a byte-identical block becomes `include: [shared_assets]` ([what owpp put into it](../commands/import.md#what-owpp-put-into-it-taken-back-out)). Better Banners imported from its file passes `owpp check --strict`, its 17 tests against the mock and its 11 live tests.
- **`owpp import --instance` of a function owpp deployed** took the whole bundle, owpp's libraries and runtime included, which `owpp check` then refuses (`.include_router()` in the routes library), and left out the tool the runtime installs. Fixed: the libraries, their data, the tool and the skills come back out as `include:`, files and `tool.py`, and bundling the import gives the same function again (tested on every example). Excalidraw imported from the instance passes `owpp check --strict`, the 63 tests against the mock (the skill's and its own), and, deployed back, the 7 live tests.
- **Excalidraw's CORS header** on its scene API is not needed on v0.13.5 with iframe Sandbox Allow Same Origin on, which the editor needs anyway: with the header removed, every live test passed. The mock's test of the header is what caught that bug. Open.

## What it cost

The mock's tests needed no fixing for Better Banners, and two expected values for Excalidraw. Excalidraw's live tests took four rounds, each a mistake in the test, not in the plugin: the shape of Open-WebUI's chat API, the keyboard focus being in the chat input rather than the editor, a model left from an earlier run, and aimock's journal keeping Open-WebUI's own title requests, which quote the chat. A run of all the live tests takes about a minute and a half each.

## Reading it

Two plugins, not a benchmark. The same agent wrote the skill, the tests and the bugs, and had read the README of each plugin; the bugs are ones it thought plausible, none of them in Excalidraw's self-hosted build, which only its own tests cover. Page Banners' tests were written before `owpp live` existed, when screenshots were the only way into a browser, so its having no live tests says more about the tools than about the people. To run any of it again: [`examples/existing-plugins/`](https://github.com/zmnatz/open-webui-plugin-protocol/tree/develop/examples/existing-plugins).
