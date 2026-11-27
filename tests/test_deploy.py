"""Deploying: create, update, global, prune, valves, --only, against the real Open-WebUI (the
test harness, `real_open_webui`); sign-in methods and faults it cannot give on demand against
the fake (`open_webui`)."""

from __future__ import annotations

import shutil

import pytest
from conftest import EXAMPLES, FILTER

from owpp.bundle import FunctionFile
from owpp.deploy import (
    MANAGED_BY,
    choices_from_env,
    deploy,
    iframe_sandbox_warning,
    instance_from_env,
    plan_deploy,
    plan_prune,
    plugins_for,
    render_report,
    run_deploy,
    sign_in,
)
from owpp.errors import OwppError
from owpp.sources import Sources

LIST = "GET /api/v1/functions/list"
CREATE = "POST /api/v1/functions/create"


class TestDeploy:
    def test_creates_a_missing_filter_activates_it_and_makes_it_global(
        self, real_open_webui, functions_dir
    ):
        m = real_open_webui()
        res = deploy(*m.options(functions_dir({"demo.py": FILTER})))
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
        self, open_webui, functions_dir
    ):
        m = open_webui(created_type="event", created_active=True)
        deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST, CREATE]

    def test_updates_changed_code_without_touching_active_global_state(
        self, real_open_webui, functions_dir
    ):
        m = real_open_webui(
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
        res = deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [
            LIST,
            "GET /api/v1/functions/id/demo",
            "POST /api/v1/functions/id/demo/update",
        ]
        assert res[0].action == "updated"
        assert m.state["demo"]["is_active"] is True and m.state["demo"]["is_global"] is True
        assert m.state["demo"]["content"] == FILTER

    def test_writes_nothing_when_the_code_already_matches(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER)])
        res = deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST, "GET /api/v1/functions/id/demo"]
        assert res[0].action == "unchanged"

    def test_reads_the_live_code_by_id_since_the_list_has_no_content(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER), git_fn("other", FILTER)])
        res = deploy(*m.options(functions_dir({"demo.py": FILTER}), force_prune=True))
        # Only the function that has a folder is fetched; the orphan is not.
        assert [c for c in m.calls if c.startswith("GET")] == [
            LIST,
            "GET /api/v1/functions/id/demo",
        ]
        assert next(r for r in res if r.id == "demo").action == "unchanged"

    def test_import_rewriting_open_webui_applies_on_save_counts_as_unchanged(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", f"{FILTER}from open_webui.config import X\n")])
        res = deploy(*m.options(functions_dir({"demo.py": f"{FILTER}from config import X\n"})))
        assert res[0].action == "unchanged"
        assert not any("/update" in c for c in m.calls)

    def test_dry_run_lists_the_plan_and_writes_nothing(self, real_open_webui, functions_dir):
        m = real_open_webui()
        res = deploy(*m.options(functions_dir({"demo.py": FILTER}), dry_run=True))
        assert m.calls == [LIST]
        assert res[0].action == "would create"
        assert render_report(res, True).startswith("Dry run:")

    def test_fails_on_a_bad_key_before_writing_anything(self, real_open_webui, functions_dir):
        m = real_open_webui()
        with pytest.raises(OwppError, match="HTTP 401"):
            deploy(*m.options(functions_dir({"demo.py": FILTER}), api_key="sk-wrong"))
        assert m.calls == []

    def test_fails_on_an_empty_functions_directory(self, real_open_webui, functions_dir):
        m = real_open_webui()
        with pytest.raises(OwppError, match="no functions"):
            deploy(*m.options(functions_dir({"README.md": "none"})))

    def test_marks_what_it_deploys_as_git_controlled_in_meta_and_description(
        self, real_open_webui, functions_dir
    ):
        m = real_open_webui()
        deploy(*m.options(functions_dir({"demo.py": FILTER})))
        meta = m.state["demo"]["meta"]
        assert meta["managed_by"] == MANAGED_BY
        assert meta["description"].startswith("Git-controlled")
        assert meta["description"].endswith("A demo filter.")

    def test_adopts_an_unmarked_function_with_identical_code_by_updating_it(
        self, real_open_webui, functions_dir
    ):
        m = real_open_webui(
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
        res = deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert res[0].action == "updated"
        assert m.state["demo"]["meta"]["managed_by"] == MANAGED_BY
        assert m.state["demo"]["is_global"] is True


class TestDeclaredGlobal:
    GLOBAL_FILTER = FILTER.replace("author: me\n", "author: me\nglobal: true\n")

    @pytest.fixture
    def run(self, functions_dir):
        def go(m, **extra):
            return deploy(*m.options(functions_dir({"demo.py": self.GLOBAL_FILTER}), **extra))

        return go

    def test_makes_an_unchanged_function_global_when_active_but_not_global(
        self, real_open_webui, git_fn, run
    ):
        m = real_open_webui(
            live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=False)]
        )
        res = run(m)
        assert res[0].action == "unchanged, made global"
        assert m.state["demo"]["is_global"] is True
        assert [c for c in m.calls if c.startswith("POST")] == [
            "POST /api/v1/functions/id/demo/toggle/global"
        ]

    def test_activates_and_makes_global_a_function_that_is_neither(
        self, real_open_webui, git_fn, run
    ):
        m = real_open_webui(
            live=[git_fn("demo", self.GLOBAL_FILTER, is_active=False, is_global=False)]
        )
        res = run(m)
        assert res[0].action == "unchanged, activated, made global"
        assert m.state["demo"]["is_active"] is True and m.state["demo"]["is_global"] is True

    def test_makes_no_toggle_call_when_already_active_and_global(
        self, real_open_webui, git_fn, run
    ):
        m = real_open_webui(
            live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=True)]
        )
        res = run(m)
        assert res[0].action == "unchanged"
        assert [c for c in m.calls if c.startswith("POST")] == []

    def test_also_fixes_the_flags_when_the_code_is_updated(self, real_open_webui, run):
        m = real_open_webui(
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

    def test_makes_a_created_non_filter_global_when_declared(self, open_webui, run):
        m = open_webui(created_type="event", created_active=True)
        res = run(m)
        assert res[0].action == "created, made global"
        assert m.state["demo"]["is_global"] is True

    def test_dry_run_reports_the_toggle_and_changes_nothing(self, real_open_webui, git_fn, run):
        m = real_open_webui(
            live=[git_fn("demo", self.GLOBAL_FILTER, is_active=True, is_global=False)]
        )
        res = run(m, dry_run=True)
        assert res[0].action == "would make global"
        assert m.state["demo"]["is_global"] is False
        assert [c for c in m.calls if c.startswith("POST")] == []

    def test_leaves_a_function_not_declared_global_alone(
        self, real_open_webui, git_fn, functions_dir
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER, is_active=True, is_global=False)])
        res = deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert res[0].action == "unchanged"
        assert m.state["demo"]["is_global"] is False


class TestDeclaredNotGlobal:
    """`global: false`: a filter that each user switches on (a toggle) is never made global."""

    TOGGLE = FILTER.replace("author: me\n", "author: me\nglobal: false\n")

    @pytest.fixture
    def run(self, functions_dir):
        def go(m, **extra):
            return deploy(*m.options(functions_dir({"demo.py": self.TOGGLE}), **extra))

        return go

    def test_a_new_toggle_is_activated_but_not_made_global(self, real_open_webui, run):
        m = real_open_webui()
        res = run(m)
        assert m.calls == [LIST, CREATE, "POST /api/v1/functions/id/demo/toggle"]
        assert res[0].action == "created, activated"
        assert m.state["demo"]["is_global"] is False

    def test_a_toggle_someone_made_global_is_taken_out_again(self, real_open_webui, git_fn, run):
        m = real_open_webui(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=True)])
        res = run(m)
        assert res[0].action == "unchanged, made not global"
        assert m.state["demo"]["is_global"] is False

    def test_dry_run_says_so_and_changes_nothing(self, real_open_webui, git_fn, run):
        m = real_open_webui(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=True)])
        res = run(m, dry_run=True)
        assert res[0].action == "would make not global"
        assert m.state["demo"]["is_global"] is True

    def test_a_toggle_already_out_of_global_makes_no_call(self, real_open_webui, git_fn, run):
        m = real_open_webui(live=[git_fn("demo", self.TOGGLE, is_active=True, is_global=False)])
        res = run(m)
        assert res[0].action == "unchanged"
        assert not any("toggle" in c for c in m.calls)


class TestPruning:
    def test_deletes_a_git_controlled_function_whose_folder_is_gone_and_leaves_hand_made_ones(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(
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
            deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert m.calls == [LIST]
        # one orphan out of three is fine
        res = deploy(*m.options(functions_dir({"demo.py": FILTER, "retired2.py": FILTER})))
        assert any(r.id == "retired" and r.action == "deleted" for r in res)
        assert "retired" not in m.state
        assert "handmade" in m.state and "demo" in m.state

    def test_deletes_a_single_orphan_even_when_it_is_the_only_managed_function(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("retired", FILTER)])
        deploy(*m.options(functions_dir({"demo.py": FILTER})))
        assert "retired" not in m.state and "demo" in m.state

    def test_force_prune_overrides_the_mass_delete_guard(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER), git_fn("a", FILTER), git_fn("b", FILTER)])
        deploy(*m.options(functions_dir({"demo.py": FILTER}), force_prune=True))
        assert list(m.state) == ["demo"]

    def test_dry_run_reports_what_it_would_delete_and_deletes_nothing(
        self, real_open_webui, functions_dir, git_fn
    ):
        m = real_open_webui(live=[git_fn("demo", FILTER), git_fn("retired", FILTER)])
        res = deploy(*m.options(functions_dir({"demo.py": FILTER}), dry_run=True))
        assert any(r.id == "retired" and r.action == "would delete" for r in res)
        assert "retired" in m.state
        assert m.calls == [LIST, "GET /api/v1/functions/id/demo"]

    def test_fails_if_the_server_does_not_confirm_a_delete(self, open_webui, functions_dir, git_fn):
        m = open_webui(live=[git_fn("demo", FILTER), git_fn("retired", FILTER)], fail_delete=True)
        with pytest.raises(OwppError, match="not confirmed"):
            deploy(*m.options(functions_dir({"demo.py": FILTER})))

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

    def test_sets_only_the_declared_valves_and_keeps_the_rest(self, open_webui, functions_dir):
        m = open_webui(
            created_type="event",
            created_active=True,
            valves={"p": {"LEVEL": "loose", "OTHER": "keep"}},
        )
        res = deploy(*m.options(self.make(functions_dir)))
        assert m.valves["p"] == {"LEVEL": "strict", "OTHER": "keep", "N": 2}
        assert "POST /api/v1/functions/id/p/valves/update" in m.calls
        assert res[0].action == "created, set valves"

    def test_makes_no_call_when_the_valves_already_match(self, open_webui, functions_dir):
        m = open_webui(
            created_type="event", created_active=True, valves={"p": {"LEVEL": "strict", "N": 2}}
        )
        res = deploy(*m.options(self.make(functions_dir)))
        assert not any(c.endswith("/valves/update") for c in m.calls)
        assert res[0].action == "created"


class TestOnly:
    def test_deploys_only_the_named_plugins_and_never_prunes_then(self, tmp_path, real_open_webui):
        for n in ("mcpo_sync", "stale_data"):  # no git sources: nothing to fetch
            shutil.copytree(EXAMPLES / n, tmp_path / n)
        m = real_open_webui(live=[{"id": "gone", "meta": {"managed_by": MANAGED_BY}}])
        instance, choices = m.options(tmp_path, dry_run=True, only=["mcpo_sync"])
        assert [r.id for r in deploy(instance, choices)] == ["mcpo_sync"]
        assert not any(c.startswith("DELETE") for c in m.calls)
        choices.only = ["nope"]
        with pytest.raises(OwppError, match="no such plugin function nope"):
            deploy(instance, choices)


class TestStandaloneUse:
    ENV = {
        "OPEN_WEBUI_URL": "https://chat.example.com/",
        "OPEN_WEBUI_API_KEY": "k",
        "OWPP_PLUGINS_DIR": "/srv/p",
        "OWPP_MANAGED_BY": "git:me/repo",
    }

    def test_flags_win_over_the_environment(self):
        assert instance_from_env(self.ENV).base_url == "https://chat.example.com"
        a = choices_from_env(self.ENV, only="a,b", dry_run=True)
        assert str(a.dir) == "/srv/p"
        assert a.managed_by == "git:me/repo"
        assert a.only == ["a", "b"]
        assert a.dry_run is True
        b = choices_from_env(self.ENV, dir="/x", managed_by="m")
        assert str(b.dir) == "/x" and b.managed_by == "m"
        assert choices_from_env({}).managed_by == MANAGED_BY

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

    def deployed(self, open_webui, directory, **kw):
        m = open_webui()
        deploy(*m.options(directory, sources=Sources(repo_fetcher), **kw))
        return m

    def test_a_dry_run_lists_the_versions_that_change(self, real_open_webui, functions_dir):
        m = self.deployed(real_open_webui, functions_dir(versioned("1.0.0")))
        newer = functions_dir(versioned("1.1.0", tool_version="2.0", skill="Draw better."))
        res = deploy(*m.options(newer, dry_run=True))
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

    def test_code_that_changed_without_a_new_version_is_flagged(
        self, real_open_webui, functions_dir
    ):
        m = self.deployed(real_open_webui, functions_dir(versioned("1.0.0")))
        files = versioned("1.0.0")
        files["viz/function.py"] += "X = 1\n"
        (r,) = deploy(*m.options(functions_dir(files), dry_run=True))
        assert r.details == ["function: code changed, still 1.0.0"]

    def test_an_unchanged_function_shows_its_version(self, real_open_webui, functions_dir):
        d = functions_dir(versioned("1.0.0"))
        m = self.deployed(real_open_webui, d)
        res = deploy(*m.options(d, dry_run=True))
        assert res[0].details == []
        assert "`viz` (viz/): unchanged (1.0.0)" in render_report(res, True)

    def test_a_new_plugin_lists_everything_it_brings(self, real_open_webui, functions_dir):
        m = real_open_webui()
        (r,) = deploy(*m.options(functions_dir(versioned("1.0.0")), dry_run=True))
        assert r.details == ["function: new (1.0.0)", "tool `viz`: new (1.0)", "skill `draw`: new"]

    def test_the_source_commit_is_recorded_and_reported(self, real_open_webui, functions_dir):
        m = self.deployed(real_open_webui, functions_dir(sourced()))
        assert m.state["up"]["meta"]["sources"] == {REPO_GIT: PINNED}
        again = deploy(*m.options(functions_dir(sourced()), sources=Sources(repo_fetcher)))
        assert again[0].action == "unchanged" and again[0].details == []
        moved = deploy(
            *m.options(functions_dir(sourced(LATEST)), sources=Sources(repo_fetcher), dry_run=True)
        )
        assert moved[0].details == [
            "tool `up`: 1.0 -> 2.0",
            f"source {REPO_GIT}: {PINNED[:7]} -> {LATEST[:7]}",
        ]

    def test_latest_reports_against_the_latest_commits_and_changes_no_file(
        self, real_open_webui, functions_dir
    ):
        d = functions_dir(sourced())
        m = self.deployed(real_open_webui, d)
        before = (d / "up" / "plugin.yaml").read_text()
        looked_up = []
        res = deploy(
            *m.options(
                d,
                sources=Sources(
                    repo_fetcher, lookup=lambda git, ref: looked_up.append((git, ref)) or LATEST
                ),
                dry_run=True,
                latest=True,
            )
        )
        assert looked_up == [(REPO_GIT, "main")]
        assert res[0].action == "would update"
        assert res[0].details == [
            "tool `up`: 1.0 -> 2.0",
            f"source {REPO_GIT}: {PINNED[:7]} -> {LATEST[:7]} "
            f"(latest of main; plugin.yaml pins {PINNED[:7]})",
        ]
        assert render_report(res, True, latest=True).startswith("Dry run at the latest commits:")
        assert (d / "up" / "plugin.yaml").read_text() == before
        assert not any("/update" in c for c in m.calls[-3:])

    def test_latest_without_a_dry_run_is_refused(self, real_open_webui, functions_dir):
        m = real_open_webui()
        with pytest.raises(OwppError, match="only goes with --dry-run"):
            deploy(*m.options(functions_dir(sourced()), latest=True))
        assert m.calls == []


# ---- signing in -----------------------------------------------------------------------


class TestSignIn:
    """Without an API key, the deploy signs in: with a user name and password (Open-WebUI's own
    accounts, then LDAP), with an OIDC token, or with nothing."""

    def run(self, m, directory, **creds):
        target = m.options(directory, api_key="", **creds)
        how = sign_in(target.instance)
        return how, deploy(*target)

    def test_an_api_key_is_used_as_it_is(self, open_webui, functions_dir):
        m = open_webui()
        instance = m.instance()
        assert sign_in(instance) == "an API key" and instance.api_key == "sk-good"
        assert not any("/auths/" in c for c in m.calls)

    def test_user_name_and_password(self, open_webui, functions_dir):
        m = open_webui(accounts={"admin@example.com": "pw"})
        how, res = self.run(
            m, functions_dir({"demo.py": FILTER}), username="admin@example.com", password="pw"
        )
        assert how == "user admin@example.com" and res[0].action.startswith("created")
        assert m.calls[0] == "POST /api/v1/auths/signin"

    def test_ldap_when_the_password_sign_in_fails(self, open_webui, functions_dir):
        m = open_webui(ldap={"ada": "pw"})
        how, res = self.run(m, functions_dir({"demo.py": FILTER}), username="ada", password="pw")
        assert how == "LDAP user ada" and res[0].action.startswith("created")
        assert m.calls[:2] == ["POST /api/v1/auths/signin", "POST /api/v1/auths/ldap"]

    def test_wrong_credentials_say_what_was_tried(self, open_webui, functions_dir):
        m = open_webui(accounts={"admin@example.com": "pw"})
        with pytest.raises(OwppError, match="with a password .*400.*with LDAP .*not enabled"):
            self.run(
                m, functions_dir({"demo.py": FILTER}), username="admin@example.com", password="no"
            )

    def test_half_a_user_name_and_password_is_refused(self, real_open_webui, functions_dir):
        with pytest.raises(OwppError, match="go together"):
            self.run(real_open_webui(), functions_dir({"demo.py": FILTER}), username="ada")

    def test_an_oidc_token_is_exchanged(self, open_webui, functions_dir):
        m = open_webui(oidc={"keycloak": "id-token"})
        how, res = self.run(
            m, functions_dir({"demo.py": FILTER}), oidc_token="id-token", oauth_provider="Keycloak"
        )
        assert how == "an OIDC token (keycloak)" and res[0].action.startswith("created")
        assert m.calls[0] == "POST /api/v1/auths/oauth/keycloak/token/exchange"

    def test_an_oidc_exchange_the_instance_does_not_allow(self, real_open_webui, functions_dir):
        with pytest.raises(OwppError, match="ENABLE_OAUTH_TOKEN_EXCHANGE=true"):
            self.run(real_open_webui(), functions_dir({"demo.py": FILTER}), oidc_token="t")

    def test_nothing_signs_in_when_the_instance_allows_it(self, open_webui, functions_dir):
        m = open_webui(open_signin=True)
        how, res = self.run(m, functions_dir({"demo.py": FILTER}))
        assert how == "an open sign-in" and res[0].action.startswith("created")

    def test_nothing_says_what_to_set_when_it_does_not(self, real_open_webui, functions_dir):
        with pytest.raises(OwppError, match="OPEN_WEBUI_API_KEY.*OPEN_WEBUI_USERNAME.*OIDC"):
            self.run(real_open_webui(), functions_dir({"demo.py": FILTER}))

    def test_the_account_must_be_an_admin(self, open_webui, functions_dir):
        m = open_webui(open_signin=True, role="user")
        with pytest.raises(OwppError, match="not an admin"):
            self.run(m, functions_dir({"demo.py": FILTER}))
        assert not any("/functions" in c for c in m.calls)

    def test_the_environment_names(self):
        opts = instance_from_env(
            {
                "OPEN_WEBUI_URL": "http://x/",
                "OPEN_WEBUI_API_KEY": "sk-secret-key",
                "OPEN_WEBUI_USERNAME": "u",
                "OPEN_WEBUI_PASSWORD": "secret-password",
                "OPEN_WEBUI_OIDC_TOKEN": "secret-token",
                "OPEN_WEBUI_OAUTH_PROVIDER": "google",
            }
        )
        assert (opts.base_url, opts.api_key, opts.username) == ("http://x", "sk-secret-key", "u")
        assert (opts.password, opts.oidc_token, opts.oauth_provider) == (
            "secret-password",
            "secret-token",
            "google",
        )
        assert "secret" not in repr(opts)  # no credential in a log or a traceback


def warning_for(target):
    return iframe_sandbox_warning(target.instance, plugins_for(target.choices))


class TestIframeRequirementWarning:
    PLUGIN = "function:\n  title: Demo\nrequires:\n  iframe_sandbox_allow_same_origin: true\n"

    def make(self, functions_dir):
        return functions_dir(
            {"demo/plugin.yaml": self.PLUGIN, "demo/function.py": "class Event:\n    pass\n"}
        )

    def test_no_requirement_never_reads_the_admin_config(self, real_open_webui, functions_dir):
        m = real_open_webui()
        assert warning_for(m.options(functions_dir({"demo.py": FILTER}))) is None
        assert m.calls == []

    def test_setting_on_means_no_warning(self, open_webui, functions_dir):
        m = open_webui(interface_settings={"iframeSandboxAllowSameOrigin": True})
        assert warning_for(m.options(self.make(functions_dir))) is None
        assert m.calls == ["GET /api/v1/auths/admin/config"]

    def test_only_that_excludes_the_plugin_does_not_warn(self, real_open_webui, functions_dir):
        m = real_open_webui()
        d = functions_dir(
            {
                "demo/plugin.yaml": self.PLUGIN,
                "demo/function.py": "class Event:\n    pass\n",
                "other.py": FILTER,
            }
        )
        assert warning_for(m.options(d, only=["other"])) is None
        assert m.calls == []

    def test_missing_setting_warns_but_the_deploy_still_writes(
        self, open_webui, functions_dir, capsys
    ):
        m = open_webui(created_type="event", created_active=True)
        opts = m.options(self.make(functions_dir))
        assert run_deploy(*opts, env={}) == 0
        out = capsys.readouterr().out
        assert "Warning:" in out and "iframe Sandbox Allow Same Origin" in out
        assert "DEFAULT_INTERFACE_SETTINGS" in out and "Deploying anyway." in out
        assert m.calls[0] == "GET /api/v1/auths/admin/config"
        assert "POST /api/v1/functions/create" in m.calls

    def test_unreadable_admin_config_warns_without_stopping_the_deploy(
        self, open_webui, functions_dir
    ):
        m = open_webui(admin_config_status=403, created_type="event", created_active=True)
        opts = m.options(self.make(functions_dir))
        warning = warning_for(opts)
        assert warning and "could not be read" in warning
        assert any(r.action.startswith("created") for r in deploy(*opts))


def test_deploy_and_versioning_share_one_text_normaliser():
    # Both compare stored code with a local file, so both must treat CRLF and trailing space alike.
    import owpp.deploy as deploy
    import owpp.versioning as versioning

    assert deploy.norm is versioning.norm
    files = [FunctionFile(id="a", content="x = 1\r\n", description="d")]
    live = [
        {"id": "a", "content": "x = 1   \n", "meta": {"managed_by": "mine", "description": "d"}}
    ]
    assert plan_deploy(files, live, "mine")[0].action == "unchanged"
