"""The routes and static libraries on the real Open-WebUI (the test harness): where a plugin's
routes go among Open-WebUI's own, the guard on them, and the `static/` files it serves. A plugin
is bundled and deployed as `owpp deploy` does, and fetched over HTTP."""

from __future__ import annotations

from pathlib import Path

import pytest

from owpp.testing import Harness

FUNCTION = '''"""
title: Demo
"""
from fastapi import APIRouter

from owpp.lib import plugin_mount

router = APIRouter()


@router.get("{prefix}/api/hello")
async def hello():
    return {{"hi": True}}


def _mount():
    from open_webui.main import app

    plugin_mount(app, router, "{prefix}")


_mount()


class Event:
    async def event(self, *args, **kwargs):
        pass
'''

JSON = {"accept": "application/json"}  # a fetch, not a page: signed out is a 401


def plugin(root: Path, id: str = "demo", access: str = "user") -> Path:
    folder = root / id
    (folder / "static" / "img").mkdir(parents=True)
    manifest = f'protocol: "0.7"\nfunction:\n  title: {id}\nstatic:\n  access: {access}\n'
    (folder / "plugin.yaml").write_text(manifest)
    (folder / "function.py").write_text(FUNCTION.format(prefix=f"/{id}"))
    (folder / "static" / "app.js").write_text("console.log(1)\n")
    (folder / "static" / "img" / "b.bin").write_bytes(b"\xff\x00")
    (folder / "static" / "index.html").write_text("<p>home</p>\n")
    return folder


def paths(app) -> list[str]:
    return [getattr(r, "path", "") for r in app.router.routes]


@pytest.fixture
def owui():
    with Harness() as harness:
        yield harness


def test_a_plugins_routes_go_after_open_webuis_and_before_its_web_app(owui, tmp_path):
    """plugin_mount leaves every route of Open-WebUI's own where it was and puts the plugin's
    just before the web app's catch-all, so they are reached."""
    before = list(owui.app.router.routes)
    owui.load(plugin(tmp_path))
    routes = owui.app.router.routes
    assert [r for r in routes if r in before] == before  # Open-WebUI's, in their order
    spa = next(i for i, r in enumerate(routes) if getattr(r, "name", "") == "spa-static-files")
    ours = [i for i, p in enumerate(paths(owui.app)) if p.startswith("/demo")]
    assert ours and max(ours) < spa
    ada = owui.add_user("Ada")
    assert owui.client(ada).get("/demo/api/hello").json() == {"hi": True}


def test_a_new_version_replaces_its_routes_and_leaves_another_plugins_alone(owui, tmp_path):
    owui.load(plugin(tmp_path / "a", "demo"))
    owui.load(plugin(tmp_path / "b", "other"))
    owui.update("demo")
    owui.update("demo")
    assert paths(owui.app).count("/demo/api/hello") == 1
    assert paths(owui.app).count("/demo/app.js") == 1
    assert paths(owui.app).count("/other/api/hello") == 1


def test_the_root_prefix_is_refused(owui, tmp_path):
    from fastapi import APIRouter

    loaded = owui.load(plugin(tmp_path))
    with pytest.raises(ValueError):
        loaded.module.plugin_mount(owui.app, APIRouter(), "/")


def test_the_routes_answer_404_once_the_function_is_off_or_gone(owui, tmp_path):
    owui.load(plugin(tmp_path))
    client = owui.client(owui.add_user("Ada"))
    owui.disable("demo")
    assert client.get("/demo/api/hello").status_code == 404
    owui.enable("demo")
    assert client.get("/demo/api/hello").status_code == 200
    owui.delete("demo")
    assert client.get("/demo/api/hello").status_code == 404


def test_static_files_are_served_with_a_type_an_etag_and_a_304(owui, tmp_path):
    owui.load(plugin(tmp_path))
    client = owui.client(owui.add_user("Ada"))
    js = client.get("/demo/app.js")
    assert (js.status_code, js.text) == (200, "console.log(1)\n")
    assert "javascript" in js.headers["content-type"] and "utf-8" in js.headers["content-type"]
    assert js.headers["x-content-type-options"] == "nosniff"
    assert (
        client.get("/demo/app.js", headers={"if-none-match": js.headers["etag"]}).status_code == 304
    )
    binary = client.get("/demo/img/b.bin")
    assert binary.headers["content-type"] == "application/octet-stream"
    assert binary.content == b"\xff\x00"


def test_index_html_is_the_page_at_the_prefix_and_the_bare_prefix_redirects(owui, tmp_path):
    owui.load(plugin(tmp_path))
    client = owui.client(owui.add_user("Ada"), follow_redirects=False)
    assert client.get("/demo/").text == "<p>home</p>\n"
    bare = client.get("/demo")
    assert (bare.status_code, bare.headers["location"]) == (307, "/demo/")


@pytest.mark.parametrize(
    ("access", "signed_out", "user", "admin"),
    [("user", 401, 200, 200), ("admin", 401, 403, 200), ("public", 200, 200, 200)],
)
def test_static_access_is_who_may_fetch_the_files(owui, tmp_path, access, signed_out, user, admin):
    owui.load(plugin(tmp_path, access=access))
    got = {
        "signed out": owui.client().get("/demo/app.js", headers=JSON).status_code,
        "user": owui.client(owui.add_user("Ada")).get("/demo/app.js").status_code,
        "admin": owui.client(owui.admin).get("/demo/app.js").status_code,
    }
    assert got == {"signed out": signed_out, "user": user, "admin": admin}


def test_the_test_plugin_bundles(tmp_path):
    """The plugin these tests deploy is a valid one (owpp check)."""
    from owpp.cli import main

    plugin(tmp_path)
    assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 0
