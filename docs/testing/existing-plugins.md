# Testing a plugin that already works

A function that someone pasted into Open-WebUI, or a plugin from another person, already works. Its tests record what it does now. The [`test-existing-plugin` skill](../ai-agents.md#the-test-existing-plugin-skill) tells an agent how to write these tests, on the [test harness](harness.md) and as [live tests](live.md). This page gives the results for two plugins, and the number of bugs that the tests then caught.

The experiments ran with owpp 0.7. At that time, the unit tests ran against a mock Open-WebUI, so the results below say "against the mock". From owpp 0.8, the same tests run on the test harness, and they all pass there.

Both plugins are in the repository, as plugins repositories with their tests and a script that plants the bugs: [`examples/existing-plugins/`](https://github.com/zmnatz/open-webui-plugin-protocol/tree/develop/examples/existing-plugins).

| | Better Banners | Excalidraw |
| --- | --- | --- |
| The plugin | [Better Banners](https://github.com/Classic298/open-webui-plugins/tree/main/better-banners) 1.0.4 by Classic298: an event function whose behaviour is mostly a script on the chat page | [Excalidraw](../examples/excalidraw.md) 3.1.0 from this repository: a filter, a tool and an editor page in the Artifacts panel |
| Brought in with | `owpp import <the folder's URL>` | the folder, with its tests removed. At that time, `owpp import --instance` could not bring it back ([what the experiments found](#what-the-experiments-found)). |
| Tests against the mock | 17 (13 tests). All passed in the first run. | 34 (26 tests). 33 passed in the first run (two expected status codes were wrong). |
| Live tests | 11, in the browser | 7, in the browser and over the API, after four rounds of test fixes |
| Tests that already existed | The [Page Banners](../examples/page_banners.md) tests (a variant of this plugin): 11 against the mock, none live | Excalidraw's own tests: 50 (41 tests) against the mock, 4 live |

All tests ran on Open-WebUI v0.13.5, with [`owpp live`](../commands/live.md). The experiment found a problem in Excalidraw, which 3.1.1 fixes ([what the experiments found](#what-the-experiments-found)), and the example now uses 3.1.1. The numbers on this page are for 3.1.0. On 3.1.1, one assertion needed a change, because 3.1.1 removed the CORS header that it checked. After that change, the skill's tests and the 7 live tests pass.

## Did the tests catch bugs?

A test that fails when you change its expected value can fail. That does not show that it catches a bug. So we put bugs that a developer could write into each plugin, one at a time. We deployed each bug to the live Open-WebUI and ran every test against it. For 3.1.1, `mutants.py` has 18 of the 19 Excalidraw bugs: the other bug was about the CORS header.

| | Better Banners: 16 bugs | Excalidraw: 19 bugs |
| --- | --- | --- |
| Caught against the mock | 4 | 14 |
| Caught live | 12 | 6 |
| Caught by either | **14** | **16** |
| Caught by the tests that already existed, against the mock | (other code) | 13 |

The two kinds of test catch different things. A plugin needs the kind of test that matches where its behaviour is:

- **Against the mock:** all code on the server. The tool, outlet, routes and tokens of Excalidraw are Python, and the mock caught 14 of their 15 bugs.
- **Live:** all code on the page. Better Banners is almost all a script in the browser. The mock caught only its 4 server bugs, and the live tests caught 12 bugs. These included dismissals stored under the wrong key, an ignored `position: bottom`, a collapsed state that was not saved, and accepted `javascript:` links.
- **Only live:** two bugs in Excalidraw's editor. In one, the editor saved without its editor id. In the other, the editor polled once and stopped.

### What the tests missed

| Plugin | Bug | Why the tests missed it |
| --- | --- | --- |
| Better Banners | The sanitizer keeps `onclick`. | The skill tested the behaviours that it listed. "A field shows hostile markup safely" was not in the list. The HTML test used an `<img onerror>`, which the sanitizer removes in all cases. |
| Better Banners | The code sets a banner's title as HTML. | Every test banner had an empty title. |
| Excalidraw | The code ignores the `SESSION_TOKEN_HOURS` valve (always 1 hour). | No test examined the lifetime of the token. |
| Excalidraw | The editor applies its own saves again. | You can see this only as a flicker. |
| Excalidraw | The editor applies a change from the model while the user draws a line. | The bug needs a line and a change at the same time. |

One more live test, with markup in every field, caught both Better Banners bugs. The skill now asks for that test for each field that a plugin shows to a person.

Excalidraw's own tests also missed the token bug. Their test set the valve to 1, which is the value that the bug puts in the code. The test now sets 2. So the skill now asks for a valve value that no constant in the code has. The two editor bugs in the table depend on timing, which neither set of tests examined.

Against the same 19 bugs, Excalidraw's own tests caught 13 with the mock. They missed these:

- `show` replaced the drawing and did not add to it;
- the tool did not check the chat id;
- the token bug;
- every bug in the editor page.

Excalidraw's own tests cover things that the skill's tests do not. These are the self-hosted editor, grants from an earlier runtime, and a hand-made tool with the same id. We did not run its own live tests against the bugs. They check that the model gets the tool and that the chat page runs it, not what the editor does.

## What the experiments found

The tests found no bug in either plugin. Every prediction about the code was correct, except two status codes. Excalidraw answers 404 for another person's chat and for a chat shared as read-only, so that it does not show that the chat exists.

The experiments found these things in owpp and in the tests:

- **`owpp live` signed in again for every browser test.** Open-WebUI refuses more than a few sign-ins a minute (429), so a suite with several browser tests failed in its fixtures. Fixed: each account signs in once in each run ([the fixtures](live.md#the-fixtures)).
- **`owpp import <file>` made a folder that `owpp check` refuses**, for a plugin that uses the Shared Assets Protocol. The protocol's byte-identical block replaces a route in `app.routes`, which owpp does not allow in a plugin's own code. (For an import from git, owpp does not check that code in this way.) Fixed: a byte-identical block becomes `include: [shared_assets]` ([what owpp put into it](../commands/import.md#what-owpp-put-into-it-taken-back-out)). Better Banners, imported from its file, passes `owpp check --strict`, its 17 tests against the mock and its 11 live tests.
- **`owpp import --instance` took the whole bundle** of a function that owpp deployed, with owpp's libraries and runtime. `owpp check` then refused it (`.include_router()` in the routes library). The import also did not bring the tool that the runtime installs. Fixed: the libraries, their data, the tool and the skills come back as `include:`, files and `tool.py`. A bundle of the import gives the same function again (tested on every example). Excalidraw, imported from the instance, passes `owpp check --strict` and the 63 tests against the mock (the skill's tests and its own). After a deploy, it also passes the 7 live tests.
- **Excalidraw did not need the CORS header** on its scene API. The editor needs **iframe Sandbox Allow Same Origin**, so it runs at Open-WebUI's own origin. Without the header, every live test passed. The mock's test of the header caught the bug that removed it. Fixed in Excalidraw 3.1.1, which removes the header, and also the text/plain saves that prevented a CORS preflight.

## What it cost

For Better Banners, the tests against the mock needed no fixes. For Excalidraw, they needed two new expected values. Excalidraw's live tests needed four rounds of fixes. Each cause was a mistake in a test, not in the plugin:

- the shape of Open-WebUI's chat API;
- the keyboard focus, which was in the chat input and not in the editor;
- a model that an earlier run left;
- aimock's journal, which keeps Open-WebUI's title requests, and these quote the chat.

One run of all live tests takes about a minute and a half for each plugin.

## Reading it

These are two plugins, not a benchmark. The same agent wrote the skill, the tests and the bugs, and it read the README of each plugin. The bugs are bugs that the agent thought possible. None of them is in Excalidraw's self-hosted editor, which only its own tests cover.

The Page Banners tests are older than `owpp live`. At that time, screenshots were the only way into a browser. So the lack of live tests there tells you about the tools of that time, not about the authors.

To run the experiments again, use [`examples/existing-plugins/`](https://github.com/zmnatz/open-webui-plugin-protocol/tree/develop/examples/existing-plugins).
