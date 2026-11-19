"""EXCALIDRAW_ASSETS_URL makes the editor page load everything from a host you run, and the
self-host build matches what the page imports. Run with `owpp test excalidraw`."""

import json
import logging
import os
import re

import pytest


@pytest.fixture
def page(plugin, monkeypatch):
    """Render the editor page with EXCALIDRAW_ASSETS_URL set to `url` (None: unset)."""

    def render(url=None, token="s.1.abc"):
        if url is None:
            monkeypatch.delenv("EXCALIDRAW_ASSETS_URL", raising=False)
        else:
            monkeypatch.setenv("EXCALIDRAW_ASSETS_URL", url)
        return plugin.module._editor_page(token)

    return render


def test_by_default_it_comes_from_esm_sh(page):
    """With EXCALIDRAW_ASSETS_URL unset, the editor loads Excalidraw 0.18.0 from esm.sh through an
    import map, along with esm.sh's stylesheet.

    By hand: with the variable unset, open the editor with the network tab open. The scripts and
    index.css come from esm.sh.
    """
    html = page()
    assert 'type="importmap"' in html and "https://esm.sh/@excalidraw/excalidraw@0.18.0" in html
    assert "editor.js" not in html and "index.css" in html  # esm.sh's own stylesheet


def test_an_empty_value_is_the_default_too(page):
    """An empty EXCALIDRAW_ASSETS_URL is the same as leaving it unset.

    By hand: set `EXCALIDRAW_ASSETS_URL=` (empty) in Open-WebUI's environment and restart. The
    editor still loads from esm.sh.
    """
    assert page("") == page()


def test_self_hosted_the_page_has_nothing_from_the_internet_in_it(page):
    """With EXCALIDRAW_ASSETS_URL set to a URL, the page loads index.css, editor.js and the fonts
    (EXCALIDRAW_ASSET_PATH) from there, and nothing from esm.sh.

    By hand: build self-host/ with build.sh, serve the result, set EXCALIDRAW_ASSETS_URL to its
    URL and restart. Open the editor with the network tab open: every file comes from your host
    and none from esm.sh.
    """
    html = page("https://static.example.com/excalidraw")
    assert "esm.sh" not in html and "importmap" not in html
    assert 'href="https://static.example.com/excalidraw/index.css"' in html
    assert 'await import("https://static.example.com/excalidraw/editor.js")' in html
    assert 'window.EXCALIDRAW_ASSET_PATH = "https://static.example.com/excalidraw/";' in html


def test_a_trailing_slash_does_not_double_up(page):
    """A trailing slash on EXCALIDRAW_ASSETS_URL does not produce // in the paths.

    By hand: set the URL with a trailing slash and restart. The network tab shows
    .../excalidraw/editor.js, not .../excalidraw//editor.js.
    """
    assert "excalidraw//" not in page("https://static.example.com/excalidraw/")


def test_a_path_on_the_same_host_works_too(page):
    """A path on Open-WebUI's own host, such as /excalidraw-static, works as well as a full URL.

    By hand: serve the build at /excalidraw-static on the same host (behind your reverse proxy,
    say), set EXCALIDRAW_ASSETS_URL=/excalidraw-static and restart. The editor loads from that
    path.
    """
    html = page("/excalidraw-static")
    assert 'href="/excalidraw-static/index.css"' in html
    assert 'import("/excalidraw-static/editor.js")' in html


@pytest.mark.parametrize("mode", [None, "https://static.example.com/x"])
def test_the_token_and_version_are_filled_in_and_nothing_is_left_over(page, mode):
    """Either way (esm.sh or self-hosted), the token and version are filled in, and no
    __PLACEHOLDER__ or <!-- marker --> is left in the page.

    By hand: view the editor's source with the variable unset and again with it set. Neither has
    a __NAME__ placeholder or an HTML comment.
    """
    html = page(mode, token="s.123.sig")
    assert 'const token = "s.123.sig";' in html
    assert not re.search(r"__[A-Z_]+__", html) and "<!--" not in html


@pytest.mark.parametrize(
    "bad",
    [
        'https://x.example.com/"><script>alert(1)</script>',
        "https://x.example.com/a b",
        "https://x.example.com/a'b",
        "https://x.example.com/a\\b",
        "javascript:alert(1)",
        "ftp://x.example.com/a",
        "static.example.com/excalidraw",
        "https://x.example.com/<b>",
    ],
)
def test_a_value_that_could_break_out_of_the_page_is_refused(page, bad, caplog):
    """A value that could break out of the HTML, or that is not a plain http(s) URL or path, is
    ignored with a warning, and the page falls back to esm.sh.

    By hand: set EXCALIDRAW_ASSETS_URL=javascript:alert(1), or any of the values listed above,
    and restart. The editor loads from esm.sh, and the log says the value "is not a plain
    http(s) URL or path".
    """
    with caplog.at_level(logging.WARNING):
        html = page(bad)
    assert html == page()  # fell back to esm.sh
    assert "is not a plain http(s) URL or path" in caplog.text


def test_the_setting_is_in_config_yaml_and_listed_by_check(plugin_dir):
    """EXCALIDRAW_ASSETS_URL is declared in config.yaml (default empty), so `owpp check` lists it.

    By hand: run `owpp check excalidraw`. It prints `env   EXCALIDRAW_ASSETS_URL`.
    """
    from owpp.bundle import env_references

    assert env_references(plugin_dir) == [("EXCALIDRAW_ASSETS_URL", "")]


# ---- the self-host build ----------------------------------------------------------------


def test_the_pinned_versions_are_the_ones_the_page_uses(plugin_dir):
    """self-host/package.json pins exact versions, and they match the page: @excalidraw/excalidraw
    is EXCALIDRAW_VERSION in shared.py, and react and react-dom are the esm.sh react version in
    templates/viewer.html.

    By hand: compare those three files.
    """
    package = json.loads((plugin_dir / "self-host" / "package.json").read_text())["dependencies"]
    shared = (plugin_dir / "shared.py").read_text()
    viewer = (plugin_dir / "templates" / "viewer.html").read_text()
    assert package["@excalidraw/excalidraw"] == re.search(
        r'EXCALIDRAW_VERSION = "([^"]+)"', shared
    ).group(1)
    assert (
        package["react"]
        == package["react-dom"]
        == re.search(r"esm\.sh/react@([\d.]+)", viewer).group(1)
    )
    assert all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in package.values()), "pin exact versions"


def test_the_built_module_exports_what_the_page_imports(plugin_dir):
    """self-host/editor.js exports exactly the names that the page's self-hosted branch imports:
    React, createRoot, Excalidraw, MainMenu, convertToExcalidrawElements.

    By hand: compare the `export { ... }` line in self-host/editor.js with the `const { ... } =
    await import(...)` in the <!--hosted--> block of templates/viewer.html.
    """
    viewer = (plugin_dir / "templates" / "viewer.html").read_text()
    hosted = re.search(r"<!--hosted-->\nwindow.*?<!--/hosted-->", viewer, re.S).group(0)
    wanted = set(
        re.search(r"const \{([^}]*)\} =\s*await import", hosted).group(1).replace(" ", "").split(",")
    )
    entry = (plugin_dir / "self-host" / "editor.js").read_text()
    exported = set(re.search(r"export \{([^}]*)\}", entry).group(1).replace(" ", "").split(","))
    assert (
        wanted
        == exported
        == {"React", "createRoot", "Excalidraw", "MainMenu", "convertToExcalidrawElements"}
    )


def test_the_build_is_reproducible_and_runnable(plugin_dir):
    """build.sh is executable, stops at the first error (set -euo pipefail), installs from bun.lock
    with --frozen-lockfile, and copies index.css and the fonts.

    By hand: run ./self-host/build.sh. It succeeds, bun.lock is unchanged, and the output holds
    index.css and the fonts.
    """
    script = plugin_dir / "self-host" / "build.sh"
    assert os.access(script, os.X_OK) and (plugin_dir / "self-host" / "bun.lock").exists()
    text = script.read_text()
    assert "set -euo pipefail" in text and "--frozen-lockfile" in text
    assert "index.css" in text and "fonts" in text
