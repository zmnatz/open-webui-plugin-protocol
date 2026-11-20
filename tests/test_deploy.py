"""Deploying against a stand-in Open-WebUI: create, update, global, prune, valves, --only."""

from __future__ import annotations

import json
import shutil
from urllib.parse import urlsplit

import pytest
from conftest import EXAMPLES, FILTER

from owpp.bundle import FunctionFile
from owpp.deploy import (
    MANAGED_BY,
    HttpResponse,
    Options,
    deploy,
    options_from_env,
    plan_deploy,
    plan_prune,
    render_report,
    wait_for_health,
)
from owpp.errors import OwppError

LIST = "GET /api/v1/functions/list"
CREATE = "POST /api/v1/functions/create"


class TestDeployAgainstMock:
    def test_creates_a_missing_filter_activates_it_and_makes_it_global(
        self, mock_server, functions_dir
    ):
        m = mock_server()
        res = deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [
            LIST,
            CREATE,
            "POST /api/v1/functions/id/demo/toggle",
            "POST /api/v1/functions/id/demo/toggle/global",
        ]
        assert res[0].action == "created, activated, made global"
        assert m.state["demo"]["is_active"] is True
        assert m.state["demo"]["is_global"] is True

    def test_only_activates_a_non_filter_and_does_not_double_toggle(
        self, mock_server, functions_dir
    ):
        m = mock_server(created_type="event", created_active=True)
        deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST, CREATE]

    def test_updates_changed_code_without_touching_active_global_state(
        self, mock_server, functions_dir
    ):
        m = mock_server(
            live=[
                {
                    "id": "demo",
                    "name": "Old",
                    "content": "old",
                    "type": "filter",
                    "is_active": True,
                    "is_global": True,
                }
            ]
        )
        res = deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [
            LIST,
            "GET /api/v1/functions/id/demo",
            "POST /api/v1/functions/id/demo/update",
        ]
        assert res[0].action == "updated"
        assert m.state["demo"]["is_active"] is True and m.state["demo"]["is_global"] is True
        assert m.state["demo"]["content"] == FILTER

    def test_writes_nothing_when_the_code_already_matches(self, mock_server, functions_dir, git_fn):
        m = mock_server(live=[git_fn("demo", FILTER)])
        res = deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST, "GET /api/v1/functions/id/demo"]
        assert res[0].action == "unchanged"

    def test_reads_the_live_code_by_id_since_the_list_has_no_content(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(live=[git_fn("demo", FILTER), git_fn("other", FILTER)])
        res = deploy(m.options(functions_dir({"demo.py": FILTER}), force_prune=True))
        # Only the function that has a folder is fetched; the orphan is not.
        assert [c for c in m.calls if c.startswith("GET")] == [
            LIST,
            "GET /api/v1/functions/id/demo",
        ]
        assert next(r for r in res if r.id == "demo").action == "unchanged"

    def test_import_rewriting_open_webui_applies_on_save_counts_as_unchanged(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(live=[git_fn("demo", f"{FILTER}from open_webui.config import X\n")])
        res = deploy(m.options(functions_dir({"demo.py": f"{FILTER}from config import X\n"})))
        assert res[0].action == "unchanged"
        assert not any("/update" in c for c in m.calls)

    def test_dry_run_lists_the_plan_and_writes_nothing(self, mock_server, functions_dir):
        m = mock_server()
        res = deploy(m.options(functions_dir({"demo.py": FILTER}), dry_run=True))
        assert m.calls == [LIST]
        assert res[0].action == "would create"
        assert render_report(res, True).startswith("Dry run:")

    def test_fails_on_a_bad_key_before_writing_anything(self, mock_server, functions_dir):
        m = mock_server()
        with pytest.raises(OwppError, match="HTTP 401"):
            deploy(m.options(functions_dir({"demo.py": FILTER}), api_key="sk-wrong"))
        assert m.calls == []

    def test_fails_on_an_empty_functions_directory(self, mock_server, functions_dir):
        m = mock_server()
        with pytest.raises(OwppError, match="no functions"):
            deploy(m.options(functions_dir({"README.md": "none"})))

    def test_waits_for_health_and_gives_up(self, mock_server):
        m = mock_server()
        wait_for_health(m.options("."), attempts=1, delay=0.001)
        down = Options(base_url="http://127.0.0.1:1", api_key="k", dir=".")
        with pytest.raises(OwppError, match="did not answer"):
            wait_for_health(down, attempts=2, delay=0.001)

    def test_marks_what_it_deploys_as_git_controlled_in_meta_and_description(
        self, mock_server, functions_dir
    ):
        m = mock_server()
        deploy(m.options(functions_dir({"demo.py": FILTER})))
        meta = m.state["demo"]["meta"]
        assert meta["managed_by"] == MANAGED_BY
        assert meta["description"].startswith("Git-controlled")
        assert meta["description"].endswith("A demo filter.")

    def test_adopts_an_unmarked_function_with_identical_code_by_updating_it(
        self, mock_server, functions_dir
    ):
        m = mock_server(
            live=[
                {
                    "id": "demo",
                    "name": "x",
                    "content": FILTER,
                    "meta": {"description": "old"},
                    "is_active": True,
                    "is_global": True,
                }
            ]
        )
        res = deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert res[0].action == "updated"
        assert m.state["demo"]["meta"]["managed_by"] == MANAGED_BY
        assert m.state["demo"]["is_global"] is True


class TestDeclaredGlobal:
    GLOBAL_FILTER = FILTER.replace("author: me\n", "author: me\nglobal: true\n")

    @pytest.fixture
    def run(self, functions_dir):
        def go(m, **extra):
            return deploy(m.options(functions_dir({"demo.py": self.GLOBAL_FILTER}), **extra))

        return go

    def test_makes_an_unchanged_function_global_when_active_but_not_global(
        self, mock_server, git_fn, run
    ):
        m = mock_server(live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=False)])
        res = run(m)
        assert res[0].action == "unchanged, made global"
        assert m.state["demo"]["is_global"] is True
        assert [c for c in m.calls if c.startswith("POST")] == [
            "POST /api/v1/functions/id/demo/toggle/global"
        ]

    def test_activates_and_makes_global_a_function_that_is_neither(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.GLOBAL_FILTER, is_active=False, is_global=False)])
        res = run(m)
        assert res[0].action == "unchanged, activated, made global"
        assert m.state["demo"]["is_active"] is True and m.state["demo"]["is_global"] is True

    def test_makes_no_toggle_call_when_already_active_and_global(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=True)])
        res = run(m)
        assert res[0].action == "unchanged"
        assert [c for c in m.calls if c.startswith("POST")] == []

    def test_also_fixes_the_flags_when_the_code_is_updated(self, mock_server, run):
        m = mock_server(
            live=[
                {
                    "id": "demo",
                    "name": "Old",
                    "content": "old",
                    "type": "filter",
                    "is_active": True,
                    "is_global": False,
                }
            ]
        )
        res = run(m)
        assert res[0].action == "updated, made global"
        assert m.state["demo"]["is_global"] is True

    def test_makes_a_created_non_filter_global_when_declared(self, mock_server, run):
        m = mock_server(created_type="event", created_active=True)
        res = run(m)
        assert res[0].action == "created, made global"
        assert m.state["demo"]["is_global"] is True

    def test_dry_run_reports_the_toggle_and_changes_nothing(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=False)])
        res = run(m, dry_run=True)
        assert res[0].action == "would make global"
        assert m.state["demo"]["is_global"] is False
        assert [c for c in m.calls if c.startswith("POST")] == []

    def test_leaves_a_function_not_declared_global_alone(self, mock_server, git_fn, functions_dir):
        m = mock_server(live=[git_fn("demo", FILTER, is_active=True, is_global=False)])
        res = deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert res[0].action == "unchanged"
        assert m.state["demo"]["is_global"] is False


class TestDeclaredNotGlobal:
    """`global: false`: a filter that each user switches on (a toggle) is never made global."""

    TOGGLE = FILTER.replace("author: me\n", "author: me\nglobal: false\n")

    @pytest.fixture
    def run(self, functions_dir):
        def go(m, **extra):
            return deploy(m.options(functions_dir({"demo.py": self.TOGGLE}), **extra))

        return go

    def test_a_new_toggle_is_activated_but_not_made_global(self, mock_server, run):
        m = mock_server()
        res = run(m)
        assert m.calls == [LIST, CREATE, "POST /api/v1/functions/id/demo/toggle"]
        assert res[0].action == "created, activated"
        assert m.state["demo"]["is_global"] is False

    def test_a_toggle_someone_made_global_is_taken_out_again(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=True)])
        res = run(m)
        assert res[0].action == "unchanged, made not global"
        assert m.state["demo"]["is_global"] is False

    def test_dry_run_says_so_and_changes_nothing(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=True)])
        res = run(m, dry_run=True)
        assert res[0].action == "would make not global"
        assert m.state["demo"]["is_global"] is True

    def test_a_toggle_already_out_of_global_makes_no_call(self, mock_server, git_fn, run):
        m = mock_server(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=False)])
        res = run(m)
        assert res[0].action == "unchanged"
        assert not any("toggle" in c for c in m.calls)


class TestPruning:
    def test_deletes_a_git_controlled_function_whose_folder_is_gone_and_leaves_hand_made_ones(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(
            live=[
                git_fn("demo", FILTER),
                git_fn("retired", FILTER),
                git_fn("retired2", FILTER),
                {
                    "id": "handmade",
                    "name": "mine",
                    "content": "x",
                    "meta": {"description": ""},
                    "is_active": True,
                    "is_global": False,
                },
            ]
        )
        # 2 of 3 managed would go: over half, so the guard stops it.
        with pytest.raises(OwppError, match="refusing to delete 2 of 3"):
            deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST]
        # one orphan out of three is fine
        res = deploy(m.options(functions_dir({"demo.py": FILTER, "retired2.py": FILTER})))
        assert any(r.id == "retired" and r.action == "deleted" for r in res)
        assert "retired" not in m.state
        assert "handmade" in m.state and "demo" in m.state

    def test_deletes_a_single_orphan_even_when_it_is_the_only_managed_function(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(live=[git_fn("retired", FILTER)])
        deploy(m.options(functions_dir({"demo.py": FILTER})))
        assert "retired" not in m.state and "demo" in m.state

    def test_force_prune_overrides_the_mass_delete_guard(self, mock_server, functions_dir, git_fn):
        m = mock_server(live=[git_fn("demo", FILTER), git_fn("a", FILTER), git_fn("b", FILTER)])
        deploy(m.options(functions_dir({"demo.py": FILTER}), force_prune=True))
        assert list(m.state) == ["demo"]

    def test_dry_run_reports_what_it_would_delete_and_deletes_nothing(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(live=[git_fn("demo", FILTER), git_fn("retired", FILTER)])
        res = deploy(m.options(functions_dir({"demo.py": FILTER}), dry_run=True))
        assert any(r.id == "retired" and r.action == "would delete" for r in res)
        assert "retired" in m.state
        assert m.calls == [LIST, "GET /api/v1/functions/id/demo"]

    def test_fails_if_the_server_does_not_confirm_a_delete(
        self, mock_server, functions_dir, git_fn
    ):
        m = mock_server(live=[git_fn("demo", FILTER), git_fn("retired", FILTER)], fail_delete=True)
        with pytest.raises(OwppError, match="not confirmed"):
            deploy(m.options(functions_dir({"demo.py": FILTER})))

    def test_plan_prune_only_returns_marked_functions_that_have_no_folder(self, git_fn):
        live = [
            git_fn("a", FILTER),
            git_fn("gone", FILTER),
            {"id": "mine", "meta": {}},
            {"id": "noMeta"},
        ]
        assert [f["id"] for f in plan_prune([FunctionFile(id="a")], live)] == ["gone"]


class TestValves:
    PLUGIN = "function:\n  title: T\n  valves: {LEVEL: strict, N: 2}\n"

    def make(self, functions_dir):
        return functions_dir(
            {"p/plugin.yaml": self.PLUGIN, "p/function.py": "class Event:\n    pass\n"}
        )

    def test_sets_only_the_declared_valves_and_keeps_the_rest(self, mock_server, functions_dir):
        m = mock_server(created_type="event", created_active=True)
        m_valves = {"LEVEL": "loose", "OTHER": "keep"}
        # The mock has no valves routes, so serve them from a fetch wrapper.
        sent = []

        def fetch(method, url, headers=None, body=None):
            path = urlsplit(url).path
            if path.endswith("/valves") and method == "GET":
                return HttpResponse(200, json.dumps(m_valves))
            if path.endswith("/valves/update"):
                sent.append(json.loads(body))
                return HttpResponse(200, "{}")
            return opts_fetch(method, url, headers, body)

        opts = m.options(self.make(functions_dir))
        opts_fetch = opts.fetch
        opts.fetch = fetch
        res = deploy(opts)
        assert sent == [{"LEVEL": "strict", "OTHER": "keep", "N": 2}]
        assert res[0].action == "created, set valves"

    def test_makes_no_call_when_the_valves_already_match(self, mock_server, functions_dir):
        m = mock_server(created_type="event", created_active=True)
        sent = []

        def fetch(method, url, headers=None, body=None):
            path = urlsplit(url).path
            if path.endswith("/valves") and method == "GET":
                return HttpResponse(200, json.dumps({"LEVEL": "strict", "N": 2}))
            sent.append(path)
            return opts_fetch(method, url, headers, body)

        opts = m.options(self.make(functions_dir))
        opts_fetch = opts.fetch
        opts.fetch = fetch
        res = deploy(opts)
        assert not any(p.endswith("/valves/update") for p in sent)
        assert res[0].action == "created"


class TestOnly:
    def test_deploys_only_the_named_plugins_and_never_prunes_then(self, tmp_path):
        for n in ("mcpo_sync", "stale_data"):  # no git sources: nothing to fetch
            shutil.copytree(EXAMPLES / n, tmp_path / n)
        calls = []

        def fetch(method, url, headers=None, body=None):
            calls.append(f"{method} {urlsplit(url).path}")
            if url.endswith("/functions/list"):
                body_out = [{"id": "gone", "meta": {"managed_by": MANAGED_BY}}]
            else:
                body_out = {"id": "x", "is_active": True, "is_global": False}
            return HttpResponse(200, json.dumps(body_out))

        opts = Options(
            base_url="http://x",
            api_key="k",
            dir=tmp_path,
            dry_run=True,
            only=["mcpo_sync"],
            fetch=fetch,
        )
        assert [r.id for r in deploy(opts)] == ["mcpo_sync"]
        assert not any(c.startswith("DELETE") for c in calls)
        opts.only = ["nope"]
        with pytest.raises(OwppError, match="no such plugin function nope"):
            deploy(opts)


class TestStandaloneUse:
    ENV = {
        "OPEN_WEBUI_URL": "https://chat.example.com/",
        "OPEN_WEBUI_API_KEY": "k",
        "OWPP_PLUGINS_DIR": "/srv/p",
        "OWPP_MANAGED_BY": "git:me/repo",
    }

    def test_flags_win_over_the_environment(self):
        a = options_from_env(self.ENV, only="a,b", dry_run=True)
        assert a.base_url == "https://chat.example.com"
        assert str(a.dir) == "/srv/p"
        assert a.managed_by == "git:me/repo"
        assert a.only == ["a", "b"]
        assert a.dry_run is True
        b = options_from_env(self.ENV, dir="/x", managed_by="m")
        assert str(b.dir) == "/x" and b.managed_by == "m"
        assert options_from_env({}).managed_by == MANAGED_BY

    def test_marks_compares_and_prunes_with_the_configured_marker_only(self):
        files = [FunctionFile(id="a", content="x", description="d")]
        live = [
            {"id": "a", "content": "x", "meta": {"managed_by": "mine", "description": "d"}},
            {"id": "gone", "meta": {"managed_by": "mine"}},
            {"id": "theirs", "meta": {"managed_by": MANAGED_BY}},
        ]
        assert plan_deploy(files, live, "mine")[0].action == "unchanged"
        assert plan_deploy(files, live)[0].action == "update"  # the default marker does not own it
        assert [f["id"] for f in plan_prune(files, live, "mine")] == ["gone"]


# ---- what a deploy reports, in versions ------------------------------------------------

PINNED = "a1" * 20
LATEST = "b2" * 20
REPO_GIT = "https://github.com/owner/repo.git"


def versioned(version: str, tool_version: str = "1.0", skill: str = "Draw.") -> dict:
    """A plugin folder with a function, a tool and a skill, each at a version."""
    return {
        "viz/plugin.yaml": (
            f"function:\n  title: Viz\n  version: {version}\n"
            f"tool:\n  id: viz\n  title: Viz Tool\n  version: '{tool_version}'\n"
        ),
        "viz/function.py": "class Filter:\n    pass\n",
        "viz/tool.py": "class Tools:\n    pass\n",
        "viz/skills/draw/SKILL.md": f"---\nname: draw\n---\n{skill}\n",
    }


def sourced(ref: str = PINNED) -> dict:
    return {
        "up/plugin.yaml": (
            f"source:\n  git: {REPO_GIT}\n  ref: {ref}\n  path: ''\n  track: main\n"
            "function:\n  title: Up\n  version: 1.0.0\n  global: true\n"
            "tool:\n  id: up\n  file: tool.py\n"
        )
    }


def repo_fetcher(git, ref, paths):
    """The upstream tool.py: version 1.0 at the pinned commit, 2.0 at the latest."""
    version = "2.0" if ref == LATEST else "1.0"
    return {p: f'"""\ntitle: Up\nversion: {version}\n"""\nclass Tools:\n    pass\n' for p in paths}


class TestVersionReport:
    """A deploy (and above all a dry run) says what changes in versions: the function, each
    tool and skill it installs, and the commit of the repository it takes code from."""

    def deployed(self, mock_server, directory, **kw):
        m = mock_server()
        deploy(m.options(directory, git_fetcher=repo_fetcher, **kw))
        return m

    def test_a_dry_run_lists_the_versions_that_change(self, mock_server, functions_dir):
        m = self.deployed(mock_server, functions_dir(versioned("1.0.0")))
        newer = functions_dir(versioned("1.1.0", tool_version="2.0", skill="Draw better."))
        res = deploy(m.options(newer, dry_run=True))
        (r,) = res
        assert r.action == "would update"
        assert r.details == [
            "function: 1.0.0 -> 1.1.0",
            "tool `viz`: 1.0 -> 2.0",
            "skill `draw`: changed, still (no version)",
        ]
        report = render_report(res, True)
        assert (
            "- filter function `viz` (viz/): would update\n  - function: 1.0.0 -> 1.1.0" in report
        )

    def test_code_that_changed_without_a_new_version_is_flagged(self, mock_server, functions_dir):
        m = self.deployed(mock_server, functions_dir(versioned("1.0.0")))
        files = versioned("1.0.0")
        files["viz/function.py"] += "X = 1\n"
        (r,) = deploy(m.options(functions_dir(files), dry_run=True))
        assert r.details == ["function: code changed, still 1.0.0"]

    def test_an_unchanged_function_shows_its_version(self, mock_server, functions_dir):
        d = functions_dir(versioned("1.0.0"))
        m = self.deployed(mock_server, d)
        res = deploy(m.options(d, dry_run=True))
        assert res[0].details == []
        assert "`viz` (viz/): unchanged (1.0.0)" in render_report(res, True)

    def test_a_new_plugin_lists_everything_it_brings(self, mock_server, functions_dir):
        m = mock_server()
        (r,) = deploy(m.options(functions_dir(versioned("1.0.0")), dry_run=True))
        assert r.details == ["function: new (1.0.0)", "tool `viz`: new (1.0)", "skill `draw`: new"]

    def test_the_source_commit_is_recorded_and_reported(self, mock_server, functions_dir):
        m = self.deployed(mock_server, functions_dir(sourced()))
        assert m.state["up"]["meta"]["sources"] == {REPO_GIT: PINNED}
        again = deploy(m.options(functions_dir(sourced()), git_fetcher=repo_fetcher))
        assert again[0].action == "unchanged" and again[0].details == []
        moved = deploy(
            m.options(functions_dir(sourced(LATEST)), git_fetcher=repo_fetcher, dry_run=True)
        )
        assert moved[0].details == [
            "tool `up`: 1.0 -> 2.0",
            f"source {REPO_GIT}: {PINNED[:7]} -> {LATEST[:7]}",
        ]

    def test_sync_reports_against_the_latest_commits_and_changes_no_file(
        self, mock_server, functions_dir
    ):
        d = functions_dir(sourced())
        m = self.deployed(mock_server, d)
        before = (d / "up" / "plugin.yaml").read_text()
        looked_up = []
        res = deploy(
            m.options(
                d,
                git_fetcher=repo_fetcher,
                dry_run=True,
                sync=True,
                resolve=lambda git, ref: looked_up.append((git, ref)) or LATEST,
            )
        )
        assert looked_up == [(REPO_GIT, "main")]
        assert res[0].action == "would update"
        assert res[0].details == [
            "tool `up`: 1.0 -> 2.0",
            f"source {REPO_GIT}: {PINNED[:7]} -> {LATEST[:7]} "
            f"(latest of main; plugin.yaml pins {PINNED[:7]})",
        ]
        assert render_report(res, True, sync=True).startswith("Dry run at the latest commits:")
        assert (d / "up" / "plugin.yaml").read_text() == before
        assert not any("/update" in c for c in m.calls[-3:])

    def test_sync_without_a_dry_run_is_refused(self, mock_server, functions_dir):
        m = mock_server()
        with pytest.raises(OwppError, match="only goes with --dry-run"):
            deploy(m.options(functions_dir(sourced()), sync=True))
        assert m.calls == []
