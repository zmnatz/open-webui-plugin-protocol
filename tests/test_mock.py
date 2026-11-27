"""The mock Open-WebUI itself (owpp.testing): the parts plugins written elsewhere rely on, beyond
what the example plugins' own tests already exercise."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from owpp.deploy import deploy
from owpp.sources import Sources
from owpp.testing import MockOpenWebUI

pytest_plugins = ["pytester"]


def plugin_folder(root: Path, code: str, manifest: str = "function:\n  title: Demo\n") -> Path:
    folder = root / "demo"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(manifest)
    (folder / "function.py").write_text(textwrap.dedent(code))
    return folder


def test_a_module_the_mock_lacks_still_imports_and_says_what_is_missing(tmp_path):
    """Third-party plugins import parts of Open-WebUI the mock does not implement. The import
    works; using the name fails, naming exactly what to add to the mock."""
    folder = plugin_folder(
        tmp_path,
        """
        from open_webui.models.messages import Messages
        from open_webui.models.users import NotInTheMock


        class Event:
            async def event(self, *args, **kwargs):
                pass

            def use(self):
                return Messages.get_message_by_id("x")
        """,
    )
    with MockOpenWebUI() as owui:
        plugin = owui.load(folder)
        with pytest.raises(NotImplementedError, match=r"open_webui\.models\.messages\.Messages"):
            plugin.instance.use()
    assert "open_webui.models.messages" not in sys.modules  # taken out again


def test_a_missing_name_used_as_a_path_says_what_is_missing():
    with MockOpenWebUI():
        from open_webui.env import NOT_A_REAL_DIR  # noqa: PLC0415

        with pytest.raises(NotImplementedError, match="NOT_A_REAL_DIR"):
            Path(NOT_A_REAL_DIR)


def test_a_loose_file_is_refused_with_the_command_that_makes_it_a_plugin(tmp_path):
    """owui.load() takes a plugin folder; a single .py says how to make one of it."""
    loose = tmp_path / "plugins" / "shout.py"
    loose.parent.mkdir()
    loose.write_text('"""\ntitle: Shout\n"""\nclass Filter:\n    pass\n')
    with MockOpenWebUI() as owui, pytest.raises(ValueError, match=r"owpp import .*shout\.py"):
        owui.load(loose)


def test_open_webuis_directories_exist():
    """DATA_DIR, UPLOAD_DIR, CACHE_DIR and FRONTEND_BUILD_DIR point at real (temporary) folders,
    removed again when the mock closes."""
    with MockOpenWebUI() as owui:
        from open_webui.config import CACHE_DIR, UPLOAD_DIR  # noqa: PLC0415
        from open_webui.env import DATA_DIR, FRONTEND_BUILD_DIR  # noqa: PLC0415

        for path in (DATA_DIR, UPLOAD_DIR, CACHE_DIR, FRONTEND_BUILD_DIR):
            assert Path(path).is_dir()
        data = owui.data_dir
    assert not data.exists()


def test_model_configs_behave_like_open_webuis():
    """Tags are normalised to [{"name": ...}], unknown meta keys are kept, and the row is what
    insert and update wrote."""
    with MockOpenWebUI() as owui:
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
        assert row.params.model_dump() == {"temperature": 0.2}
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


def test_a_source_plugin_is_loaded_through_the_sources_the_mock_was_given(tmp_path):
    """Without `sources=`, load() fetches what a `source:` plugin takes from git, as the deploy
    does, through the mock's Sources: once for every mock that shares it. Closing a mock leaves
    that Sources open, for whoever made it."""
    calls = []
    folder = source_folder(tmp_path)
    with recording_sources(calls) as sources:
        for _ in range(2):
            with MockOpenWebUI(sources=sources) as owui:
                assert owui.load(folder).type == "event"
                owui.load(folder)
        assert not sources.closed
    assert calls == [("https://example.com/repo.git", PINNED, ("p/event.py",))]


def test_a_mock_given_no_sources_makes_its_own_and_closes_it():
    """A mock made without a Sources, as outside pytest, has one for as long as it is open."""
    with MockOpenWebUI() as owui:
        assert not owui.sources.closed
    assert owui.sources.closed


def test_what_stand_ins_do_not_hold_is_fetched_through_the_mocks_sources(tmp_path):
    """A whole plugin from git whose upstream takes its function from another repository:
    `sources=` stands in for the upstream folder, and the other repository is read through the
    mock's Sources."""
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
    with recording_sources(calls) as sources, MockOpenWebUI(sources=sources) as owui:
        assert owui.load(folder, sources=stand_ins).type == "event"
    assert calls == [("https://example.com/other.git", PINNED, ("event.py",))]


def test_the_owui_fixture_gives_every_mock_the_sessions_sources(pytester):
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
    """Open-WebUI passes a filter `__model__`, the model the chat is with, and plugins use its
    `get_last_user_message_item`. The mock gives both: the model is "mock-model" unless a test
    names one."""
    folder = plugin_folder(tmp_path, FILTER_WITH_MODEL)
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a reply"},
        {"role": "user", "content": "last"},
        {"role": "assistant", "content": "another reply"},
    ]
    with MockOpenWebUI() as owui:
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
    with MockOpenWebUI() as owui:
        plugin = owui.load(folder, active=False)
        owui.emit("user.deleted", {"type": "user", "id": "u1"})
        owui.emit("function.enable_started", "demo")
        owui.emit("function.updated", "demo")  # not enabled, not starting: not sent
        assert plugin.module.SEEN == [
            ("function.enable_started", {"type": "function", "id": "demo"})
        ]
        owui.functions["demo"].is_active = True
        owui.emit("user.deleted", {"type": "user", "id": "u1"})
        assert plugin.module.SEEN[-1] == ("user.deleted", {"type": "user", "id": "u1"})


def test_a_session_token_decodes_to_its_user(tmp_path):
    """`decode_token` gives a token's claims without a database read, as Theme Designer Pro
    uses it to tell whose live-update stream a cookie opened; anything else is None."""
    with MockOpenWebUI() as owui:
        from open_webui.utils.auth import decode_token

        ada = owui.add_user("Ada")
        assert decode_token(ada.token) == {"id": ada.id}
        assert decode_token("forged") is None and decode_token("") is None


def test_a_plugin_can_ask_a_model(tmp_path):
    """A plugin that asks a model itself (Theme Designer Pro's AI Consultant) goes through the
    pipelines' inlet, which the mock has none of, and gets `owui.model_reply`; what it asked is
    in `owui.completions`."""
    with MockOpenWebUI() as owui:
        from open_webui.routers.pipelines import process_pipeline_inlet_filter
        from open_webui.routers.tasks import (
            apply_task_model_params,
            get_task_model_generation_config,
        )
        from open_webui.utils.chat import generate_chat_completion

        owui.model_reply = "blue"
        asked = {"model": "m", "messages": [{"role": "user", "content": "a colour?"}]}
        assert owui.run(process_pipeline_inlet_filter(None, asked, None, {})) is asked
        assert owui.run(get_task_model_generation_config("m", {})) == ("m", None)
        assert apply_task_model_params(asked, {}, "m", {"temperature": 0})["temperature"] == 0
        reply = owui.run(generate_chat_completion(None, form_data=asked, user=None))
        assert reply["choices"][0]["message"]["content"] == "blue"
        assert owui.completions == [asked]


UPSTREAM_FILTER = '''"""
title: Upstream Filter
description: Reads its settings from config.
"""

from utils.misc import get_last_user_message_item


class Filter:
    def inlet(self, body):
        return {**body, "last": get_last_user_message_item(body["messages"])}
'''


def test_the_mock_stores_a_function_as_a_deploy_leaves_it_on_open_webui(tmp_path, open_webui):
    """The same plugin, deployed to the adapter's in-memory fake and loaded into the mock, is the
    same row in both: the meta a deploy writes (the ownership marker, the description with its
    note, the commit of the git source, `requires:`) beside the header Open-WebUI adds as
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
        with MockOpenWebUI(sources=sources) as owui:
            plugin = owui.load(folder)
            row = plugin.row.model_dump()
            assert plugin.inlet({"messages": [{"role": "user", "content": "hi"}]})["last"]
    deployed = fake.state["demo"]
    assert {key: row[key] for key in deployed} == deployed
    assert deployed["meta"]["sources"] == {"https://example.com/repo.git p": PINNED}
    assert deployed["meta"]["requires"] == {"iframe_sandbox_allow_same_origin": True}
    assert "from open_webui.utils.misc import" in deployed["content"]


def test_the_mocks_replace_imports_rewrites_what_open_webuis_does():
    """The runtime installs a plugin's tool through `replace_imports`, so the mock's rewrites the
    old import prefixes as Open-WebUI's does."""
    with MockOpenWebUI():
        from open_webui.utils.plugin import replace_imports  # noqa: PLC0415

        old = "from utils.a import b\nfrom apps.c import d\nfrom main import e\nfrom config import f\n"
        new = old.replace("from ", "from open_webui.")
        assert replace_imports(old) == new
        assert replace_imports(new) == new
