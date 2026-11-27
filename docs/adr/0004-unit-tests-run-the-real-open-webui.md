# Unit tests run the real Open-WebUI, with upstream's slim dependencies

`owpp test` runs a plugin's unit tests against the real Open-WebUI code. Until now, they ran against a mock Open-WebUI: about 1,370 lines in `owpp/testing/mock.py` that wrote again each `open_webui` name a plugin used. Each new call that a plugin needed was new mock code, and the mock could drift from the real Open-WebUI. The `owui` fixture stays, as the **test harness** (see the glossary). It now holds only the parts that a test must control: a fake model, a record of what was sent, and a fresh database for each test.

What this means:

- **The stand-ins are gone.** No `open_webui.*` module is written in owpp. The catch-all for missing names, `MockOpenWebUI` and the `open_webui-stubs` package are removed.
- **The dependencies are upstream's slim list.** The `test` extra holds the pins of Open-WebUI's `backend/requirements-slim.lock` at the pinned tag, and Open-WebUI's own Python range as markers. Open-WebUI builds its slim Docker image from the same list. A script copies the pins at each pin bump. A CI check fails if they drift. The tests run with `USE_SLIM=true`, as the slim image does.
- **Open-WebUI's code is a cached wheel, not an installed package.** The harness downloads the pinned pure-Python wheel once and checks its hash. Then it adds the wheel to `sys.path`. pip never resolves the 111 dependencies of the full package, so torch, CUDA and chromadb are never installed. The install command does not change.
- **One Open-WebUI for each test run.** Open-WebUI reads its settings and opens its database when it is imported. So the harness sets up `DATA_DIR` once for each run and empties the tables between tests.
- **The same pin as `owpp live`.** The unit tests and the live stack use one Open-WebUI version, and an owpp release changes both.
- **A package outside slim belongs to the plugin's repository.** If a plugin imports a part of Open-WebUI that slim does not install, the harness gives the name of the package and Open-WebUI's pin for it. The repository adds the package to its own test dependencies.
- **This replaces part of [ADR 0002](0002-plugin-source-is-python.md).** "Open-WebUI is not installed for development" is no longer true for tests. An editor finds `open_webui` through the cached wheel. `owpp test --editor` gives its path.

## Considered Options

- **Keep the mock** (the state before): a small, fast install on every Python, but each `open_webui` call that a plugin needs is hand-written again, and a test can pass on code that fails in Open-WebUI.
- **Keep the mock as a light path, with the real Open-WebUI as an option**: two harnesses to keep in step, so the maintenance cost stays.
- **The full `open-webui` package as the dependency**: completely standard, but it pins 111 packages, which resolve to 262 on Linux, among them torch, triton and 14 CUDA packages. That is several GB on each CI run.
- **A list of dependencies that owpp generates** from the modules the tests load: small, but owpp keeps the list itself. Upstream already keeps the slim list for its slim image.
- **Run the unit tests inside the slim Docker image**: the exact environment of a slim deploy, but unit tests need Docker. Each run installs pytest and the repository's test packages into the container. IDE test runners, debuggers and coverage also need remote setup. The live suite already tests what the image adds.
