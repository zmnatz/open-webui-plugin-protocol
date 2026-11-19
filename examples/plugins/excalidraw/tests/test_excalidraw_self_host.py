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
    html = page()
    assert 'type="importmap"' in html and "https://esm.sh/@excalidraw/excalidraw@0.18.0" in html
    assert "editor.js" not in html and "index.css" in html  # esm.sh's own stylesheet


def test_an_empty_value_is_the_default_too(page):
    assert page("") == page()


def test_self_hosted_the_page_has_nothing_from_the_internet_in_it(page):
    html = page("https://static.example.com/excalidraw")
    assert "esm.sh" not in html and "importmap" not in html
    assert 'href="https://static.example.com/excalidraw/index.css"' in html
    assert 'await import("https://static.example.com/excalidraw/editor.js")' in html
    assert 'window.EXCALIDRAW_ASSET_PATH = "https://static.example.com/excalidraw/";' in html


def test_a_trailing_slash_does_not_double_up(page):
    assert "excalidraw//" not in page("https://static.example.com/excalidraw/")


def test_a_path_on_the_same_host_works_too(page):
    html = page("/excalidraw-static")
    assert 'href="/excalidraw-static/index.css"' in html
    assert 'import("/excalidraw-static/editor.js")' in html


@pytest.mark.parametrize("mode", [None, "https://static.example.com/x"])
def test_the_token_and_version_are_filled_in_and_nothing_is_left_over(page, mode):
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
    with caplog.at_level(logging.WARNING):
        html = page(bad)
    assert html == page()  # fell back to esm.sh
    assert "is not a plain http(s) URL or path" in caplog.text


def test_the_setting_is_in_config_yaml_and_listed_by_check(plugin_dir):
    from owpp.bundle import env_references

    assert env_references(plugin_dir) == [("EXCALIDRAW_ASSETS_URL", "")]


# ---- the self-host build ----------------------------------------------------------------


def test_the_pinned_versions_are_the_ones_the_page_uses(plugin_dir):
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
    script = plugin_dir / "self-host" / "build.sh"
    assert os.access(script, os.X_OK) and (plugin_dir / "self-host" / "bun.lock").exists()
    text = script.read_text()
    assert "set -euo pipefail" in text and "--frozen-lockfile" in text
    assert "index.css" in text and "fonts" in text
