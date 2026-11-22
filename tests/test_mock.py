"""The mock Open-WebUI itself (owpp.testing): the parts plugins written elsewhere rely on, beyond
what the example plugins' own tests already exercise."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from owpp.testing import MockOpenWebUI


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


def test_a_source_plugin_is_loaded_from_its_pinned_commit(tmp_path, monkeypatch):
    """Without `sources=`, load() fetches what a `source:` plugin takes from git, as the deploy
    does, once per run."""
    from owpp.sources import Sources
    from owpp.testing import mock

    calls = []

    def fetcher(git, ref, paths, protocols="https:ssh"):
        calls.append((git, ref, tuple(paths)))
        return {
            p: "class Event:\n    async def event(self, *a, **k):\n        pass\n" for p in paths
        }

    monkeypatch.setattr(mock, "_SESSION", Sources(fetcher))
    folder = tmp_path / "upstream"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(
        "source:\n  git: https://example.com/repo.git\n  ref: " + "a" * 40 + "\n  path: p\n"
        "function:\n  file: event.py\n"
    )
    with MockOpenWebUI() as owui:
        assert owui.load(folder).type == "event"
        owui.load(folder)
    assert calls == [("https://example.com/repo.git", "a" * 40, ("p/event.py",))]


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
        assert plugin.module.SEEN == [("function.enable_started", {"type": "function", "id": "demo"})]
        owui.functions["demo"].is_active = True
        owui.emit("user.deleted", {"type": "user", "id": "u1"})
        assert plugin.module.SEEN[-1] == ("user.deleted", {"type": "user", "id": "u1"})
