"""The test harness itself (owpp.testing.Harness): the parts plugins written elsewhere rely on,
beyond what the example plugins' own tests already exercise, and where owpp's copies of Open-WebUI
behaviour (the deploy adapter's fake, replace_imports) are checked against the real one."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from owpp.deploy import deploy
from owpp.sources import Sources
from owpp.testing import Harness

pytest_plugins = ["pytester"]


def plugin_folder(root: Path, code: str, manifest: str = "function:\n  title: Demo\n") -> Path:
    folder = root / "demo"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(manifest)
    (folder / "function.py").write_text(textwrap.dedent(code))
    return folder


def test_a_loose_file_is_refused_with_the_command_that_makes_it_a_plugin(tmp_path):
    """owui.load() takes a plugin folder; a single .py says how to make one of it."""
    loose = tmp_path / "plugins" / "shout.py"
    loose.parent.mkdir()
    loose.write_text('"""\ntitle: Shout\n"""\nclass Filter:\n    pass\n')
    with Harness() as owui, pytest.raises(ValueError, match=r"owpp import .*shout\.py"):
        owui.load(loose)


def test_open_webuis_directories_are_the_harnesss():
    """DATA_DIR, UPLOAD_DIR, CACHE_DIR and FRONTEND_BUILD_DIR are real folders of the harness."""
    with Harness() as owui:
        from open_webui.config import CACHE_DIR, UPLOAD_DIR  # noqa: PLC0415
        from open_webui.env import DATA_DIR, FRONTEND_BUILD_DIR  # noqa: PLC0415

        for path in (DATA_DIR, UPLOAD_DIR, CACHE_DIR, FRONTEND_BUILD_DIR):
            assert Path(path).is_dir() and Path(path).is_relative_to(owui.data_dir)


def test_open_webui_is_the_pinned_version():
    """A plugin that reads Open-WebUI's version gets the pinned one."""
    from owpp.testing import pin

    with Harness():
        from open_webui.env import VERSION  # noqa: PLC0415

        assert VERSION == pin.VERSION


def test_each_harness_starts_from_open_webui_just_after_its_startup(tmp_path):
    """What one harness changed (a function, a user, config, a file in the data folder, a route)
    is gone in the next."""
    folder = plugin_folder(tmp_path, "class Filter:\n    pass\n")
    with Harness() as owui:
        owui.load(folder)
        owui.add_user("Ada")
        owui.config["webui.url"] = "https://chat.example"
        (owui.data_dir / "uploads" / "left.txt").write_text("x")
        owui.app.add_api_route("/left-behind", lambda: "x")
    with Harness() as owui:
        assert owui.functions == {}
        assert [u.name for u in owui.users.values()] == ["Admin"]
        assert "webui.url" not in owui.config or owui.config["webui.url"] != "https://chat.example"
        assert not (owui.data_dir / "uploads" / "left.txt").exists()
        assert "<title>Open WebUI</title>" in owui.client(owui.admin).get("/left-behind").text


def test_a_fresh_harness_is_a_new_open_webui(tmp_path):
    """`fresh=True` imports and starts Open-WebUI again: new modules and a new data folder, and
    a change a plugin made to an Open-WebUI module is gone."""
    with Harness() as owui:
        import open_webui.utils.misc as misc  # noqa: PLC0415

        misc.PATCHED_BY_A_PLUGIN = True
        before = owui.data_dir
    with Harness(fresh=True) as owui:
        import open_webui.utils.misc as misc  # noqa: PLC0415

        assert not hasattr(misc, "PATCHED_BY_A_PLUGIN") and owui.data_dir != before
        folder = plugin_folder(tmp_path, "class Filter:\n    pass\n")
        assert owui.load(folder).type == "filter"


def test_the_fresh_open_webui_marker_gives_a_test_a_new_open_webui(pytester):
    pytester.makepyfile(
        """
        import pytest

        dirs = []

        def test_one(owui):
            dirs.append(owui.data_dir)

        @pytest.mark.fresh_open_webui
        def test_two(owui):
            assert owui.data_dir != dirs[0]
        """
    )
    # In a child process: an inline run puts sys.modules back afterwards, which would bring
    # back the Open-WebUI that the fresh one replaced.
    pytester.runpytest_subprocess("-p", "no:cacheprovider").assert_outcomes(passed=2)


def test_only_one_harness_is_open_at_a_time():
    with Harness(), pytest.raises(RuntimeError, match="another Harness is open"):
        Harness()


def test_model_configs_are_open_webuis():
    """Model configs are Open-WebUI's own: tags normalised to [{"name": ...}], unknown meta keys
    kept, and the row is what insert and update wrote."""
    with Harness() as owui:
        from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models  # noqa: PLC0415

        form = ModelForm(
            id="m",
            name="M",
            meta=ModelMeta(tags=["a", {"name": " b "}, ""], managed_by="me"),
            params=ModelParams(temperature=0.2),
        )
        owui.run(Models.insert_new_model(form, owui.admin.id))
        row = owui.models["m"]
        assert row.meta.model_dump()["tags"] == [{"name": "a"}, {"name": "b"}]
        assert row.meta.model_dump()["managed_by"] == "me"
        assert row.params.model_dump()["temperature"] == 0.2
        assert owui.run(Models.delete_model_by_id("m")) and owui.models == {}


PINNED = "a" * 40
EVENT = "class Event:\n    async def event(self, *a, **k):\n        pass\n"


def recording_sources(calls: list) -> Sources:
    """Sources whose git holds an event function at every path, noting what was fetched."""

    def fetcher(git, ref, paths):
        calls.append((git, ref, tuple(paths)))
        return {p: EVENT for p in paths}

    return Sources(fetcher)


def source_folder(root: Path) -> Path:
    """A plugin whose function is taken from git."""
    folder = root / "upstream"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(
        f"source:\n  git: https://example.com/repo.git\n  ref: {PINNED}\n  path: p\n"
        "function:\n  file: event.py\n"
    )
    return folder


def test_a_source_plugin_is_loaded_through_the_sources_the_harness_was_given(tmp_path):
    """Without `sources=`, load() fetches what a `source:` plugin takes from git, as the deploy
    does, through the harness's Sources: once for every harness that shares it. Closing a
    harness leaves that Sources open, for whoever made it."""
    calls = []
    folder = source_folder(tmp_path)
    with recording_sources(calls) as sources:
        for _ in range(2):
            with Harness(sources=sources) as owui:
                assert owui.load(folder).type == "event"
                owui.load(folder)
        assert not sources.closed
    assert calls == [("https://example.com/repo.git", PINNED, ("p/event.py",))]


def test_a_harness_given_no_sources_makes_its_own_and_closes_it():
    """A harness made without a Sources, as outside pytest, has one for as long as it is open."""
    with Harness() as owui:
        assert not owui.sources.closed
    assert owui.sources.closed


def test_what_stand_ins_do_not_hold_is_fetched_through_the_harnesss_sources(tmp_path):
    """A whole plugin from git whose upstream takes its function from another repository:
    `sources=` stands in for the upstream folder, and the other repository is read through the
    harness's Sources."""
    folder = tmp_path / "whole"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(
        f"source:\n  git: https://example.com/repo.git\n  ref: {PINNED}\n  path: p\n"
        "  plugin: true\n"
    )
    stand_ins = {
        "plugin.yaml": f"source:\n  git: https://example.com/other.git\n  ref: {PINNED}\n"
        "function:\n  file: event.py\n"
    }
    calls = []
    with recording_sources(calls) as sources, Harness(sources=sources) as owui:
        assert owui.load(folder, sources=stand_ins).type == "event"
    assert calls == [("https://example.com/other.git", PINNED, ("event.py",))]


def test_the_owui_fixture_gives_every_harness_the_sessions_sources(pytester):
    """The pytest plugin owns one Sources for the session: each test's `owui` is built with it,
    and it is closed when the session ends."""
    pytester.makepyfile(
        """
        seen = []

        def test_one(owui):
            seen.append(owui.sources)

        def test_two(owui):
            assert owui.sources is seen[0] and not owui.sources.closed
        """
    )
    run = pytester.inline_run()
    run.assertoutcome(passed=2)
    module = run.getcalls("pytest_collection_modifyitems")[0].items[0].module
    assert module.seen[0].closed


FILTER_WITH_MODEL = """
from open_webui.utils.misc import get_last_user_message_item


class Filter:
    def inlet(self, body, __model__=None):
        last = get_last_user_message_item(body["messages"])
        return {**body, "seen": [__model__["id"], last["content"]]}
"""


def test_a_filter_is_told_the_model_and_can_find_the_last_user_message(tmp_path):
    """A filter gets `__model__`, the model the chat is with: "mock-model" unless a test names
    one. Open-WebUI's own `get_last_user_message_item` finds the last user message."""
    folder = plugin_folder(tmp_path, FILTER_WITH_MODEL)
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a reply"},
        {"role": "user", "content": "last"},
        {"role": "assistant", "content": "another reply"},
    ]
    with Harness() as owui:
        plugin = owui.load(folder)
        assert plugin.inlet({"messages": messages})["seen"] == ["mock-model", "last"]
        assert plugin.inlet({"messages": messages}, model="gpt-x")["seen"] == ["gpt-x", "last"]


def test_an_event_can_be_about_something_other_than_a_function(tmp_path):
    """Open-WebUI sends events about users and models too (`user.deleted`, `model.updated`), with
    that thing as the subject. `emit` takes the subject itself for those; a plain id is still a
    function, and a `*_started` event about a function still reaches it before it is enabled."""
    folder = plugin_folder(
        tmp_path,
        """
        SEEN = []


        class Event:
            async def event(self, event, __event_name__=None, **kwargs):
                SEEN.append((__event_name__, event["subject"]))
        """,
    )
    with Harness() as owui:
        plugin = owui.load(folder, active=False)
        seen = plugin.module.SEEN
        owui.emit("user.deleted", {"type": "user", "id": "u1"})
        owui.emit("function.enable_started", "demo")
        owui.emit("function.updated", "demo")  # not enabled, not starting: not sent
        assert seen == [("function.enable_started", {"type": "function", "id": "demo"})]
        owui.enable("demo")
        owui.emit("user.deleted", {"type": "user", "id": "u1"})
        assert seen[-1] == ("user.deleted", {"type": "user", "id": "u1"})


def test_a_session_token_decodes_to_its_user():
    """A user's `token` is an Open-WebUI session token: `decode_token` gives its claims, as Theme
    Designer Pro uses it to tell whose live-update stream a cookie opened; anything else is None."""
    with Harness() as owui:
        from open_webui.utils.auth import decode_token  # noqa: PLC0415

        ada = owui.add_user("Ada")
        assert decode_token(ada.token)["id"] == ada.id
        assert decode_token("forged") is None and decode_token("") is None
        assert owui.client(ada).get("/api/v1/auths/").json()["id"] == ada.id


def test_open_webuis_model_is_aimock():
    """Open-WebUI's own chat completion reaches the harness's model, aimock, over the OpenAI
    API: it answers `owui.model_reply`, streamed or not, and `owui.completions` holds each
    request as Open-WebUI sent it. `mock-model` is served, and `serve_model` adds another."""
    with Harness() as owui:
        from open_webui.utils.chat import generate_chat_completion  # noqa: PLC0415

        owui.model_reply = "blue"
        user = owui.admin.model
        asked = {"model": "mock-model", "messages": [{"role": "user", "content": "a colour?"}]}
        reply = owui.run(generate_chat_completion(owui.request(owui.admin), asked, user))
        assert reply["choices"][0]["message"]["content"] == "blue"
        (sent,) = owui.completions
        assert sent["model"] == "mock-model" and sent["messages"][-1]["content"] == "a colour?"
        with pytest.raises(Exception, match="Model not found"):
            owui.run(
                generate_chat_completion(owui.request(owui.admin), {**asked, "model": "x"}, user)
            )
        owui.serve_model("x")
        reply = owui.run(
            generate_chat_completion(owui.request(owui.admin), {**asked, "model": "x"}, user)
        )
        assert reply["choices"][0]["message"]["content"] == "blue"

        async def streamed():
            response = await generate_chat_completion(
                owui.request(owui.admin), {**asked, "stream": True}, user
            )
            return b"".join([chunk async for chunk in response.body_iterator]).decode()

        events = [line[6:] for line in owui.run(streamed()).splitlines() if line[6:7] == "{"]
        text = "".join(
            choice["delta"].get("content") or ""
            for event in map(json.loads, events)
            for choice in event.get("choices", [])
        )
        assert text == "blue"


def test_a_plugins_requirements_are_recorded_not_installed(tmp_path):
    folder = plugin_folder(
        tmp_path,
        "class Filter:\n    pass\n",
        manifest="function:\n  title: Demo\n  requirements: some-package\n",
    )
    with Harness() as owui:
        owui.load(folder)
        assert "some-package" in owui.requirements


def test_a_package_open_webuis_slim_set_lacks_is_named_with_its_pin(tmp_path):
    """A plugin that imports a package the slim set does not install is told which one to add,
    at the version the full Open-WebUI pins."""
    folder = plugin_folder(tmp_path, "import sentence_transformers\n\nclass Filter:\n    pass\n")
    with Harness() as owui, pytest.raises(ModuleNotFoundError, match=r"sentence-transformers=="):
        owui.load(folder)


UPSTREAM_FILTER = '''"""
title: Upstream Filter
description: Reads its settings from config.
"""

from utils.misc import get_last_user_message_item


class Filter:
    def inlet(self, body):
        return {**body, "last": get_last_user_message_item(body["messages"])}
'''


def test_a_function_is_stored_as_the_deploy_adapters_fake_stores_it(tmp_path, open_webui):
    """The same plugin, deployed to the adapter's in-memory fake and loaded into the harness, is
    the same row in both: the meta a deploy writes (the ownership marker, the description with
    its note, the commit of the git source, `requires:`) beside the header Open-WebUI adds as
    `manifest`, and the code with its imports rewritten as Open-WebUI rewrites them on save."""
    folder = tmp_path / "plugins" / "demo"
    folder.mkdir(parents=True)
    (folder / "plugin.yaml").write_text(
        f"source:\n  git: https://example.com/repo.git\n  ref: {PINNED}\n  path: p\n"
        "function:\n  file: filter.py\n  global: true\n"
        "requires:\n  iframe_sandbox_allow_same_origin: true\n"
    )
    fake = open_webui()
    with Sources(lambda git, ref, paths: {p: UPSTREAM_FILTER for p in paths}) as sources:
        deploy(*fake.options(folder.parent, sources=sources))
        with Harness(sources=sources) as owui:
            plugin = owui.load(folder)
            row = plugin.row.model_dump()
            assert plugin.inlet({"messages": [{"role": "user", "content": "hi"}]})["last"]
    deployed = fake.state["demo"]
    assert {key: row[key] for key in deployed} == deployed
    assert deployed["meta"]["sources"] == {"https://example.com/repo.git p": PINNED}
    assert deployed["meta"]["requires"] == {"iframe_sandbox_allow_same_origin": True}
    assert "from open_webui.utils.misc import" in deployed["content"]


def test_owpps_replace_imports_is_open_webuis():
    """The deploy adapter's fake rewrites imports with owpp's copy of Open-WebUI's
    `replace_imports`: it gives what the real one gives."""
    from owpp.openwebui import replace_imports

    with Harness():
        from open_webui.utils.plugin import replace_imports as real  # noqa: PLC0415

        code = "from utils.a import b\nfrom apps.c import d\nfrom main import e\nfrom config import f\n"
        assert replace_imports(code) == real(code)
        assert replace_imports(real(code)) == real(code)
