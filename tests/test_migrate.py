"""`owpp migrate`: bringing a plugin.yaml written for an older protocol up to the current one."""

from __future__ import annotations

import pytest
from conftest import write_tree

from owpp.cli import main
from owpp.errors import OwppError
from owpp.manifest import read_manifest
from owpp.migrate import migrate, migrate_text

OLD = """# Written before plugin.yaml had a protocol key.
function:
  title: T
  version: 0.1.0
include: [events]
"""
GIT = "https://example.com/owner/repo.git"
SHA = "a" * 40


def tracked(name: str, protocol: str = '"0.2"', flow: bool = False) -> str:
    source = (
        f"source: {{git: {GIT}, ref: {SHA}, track: {name}, path: p}}  # pinned\n"
        if flow
        else f"source:\n  git: {GIT}\n  ref: {SHA}\n  track: {name}  # followed\n  path: p\n"
    )
    return f"protocol: {protocol}\n{source}function:\n  title: T\n"


@pytest.fixture
def plugins(tmp_path):
    def make(old=OLD, **extra):
        return write_tree(
            tmp_path,
            {
                "old/plugin.yaml": old,
                "old/function.py": "class Event:\n    pass\n",
                **extra,
            },
        )

    return make


def run(directory, ids=None, dry_run=False, kinds=None):
    lines: list[str] = []
    asked: list[tuple[str, str]] = []

    def kind_of(git, name):
        asked.append((git, name))
        return (kinds or {}).get(name)

    code = migrate(directory, ids, dry_run=dry_run, out=lines.append, kind_of=kind_of)
    run.asked = asked  # type: ignore[attr-defined]
    return code, "\n".join(lines)


class TestMigrate:
    def test_it_adds_the_key_and_leaves_everything_else_alone(self, plugins):
        d = plugins()
        assert run(d) == (0, "new   old: migrated 0.1 -> 0.2 -> 0.3\n        wrote plugin.yaml")
        text = (d / "old" / "plugin.yaml").read_text()
        assert text.startswith(
            '# Written before plugin.yaml had a protocol key.\nprotocol: "0.3"\n'
        )
        assert "  version: 0.1.0\ninclude: [events]\n" in text
        assert read_manifest(d / "old")["protocol"] == "0.3"

    def test_a_dry_run_writes_nothing(self, plugins):
        d = plugins()
        code, out = run(d, dry_run=True)
        assert code == 0 and "would migrate 0.1 -> 0.2 -> 0.3" in out
        assert (d / "old" / "plugin.yaml").read_text() == OLD

    def test_an_explicit_old_version_is_replaced_keeping_its_comment(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.1" # when we started\nfunction:')
        d = plugins(old=old)
        assert run(d)[0] == 0
        assert 'protocol: "0.3" # when we started\n' in (d / "old" / "plugin.yaml").read_text()

    def test_a_plugin_already_at_the_current_version_is_left_alone(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.3"\nfunction:')
        d = plugins(old=old)
        assert run(d) == (0, "ok    old: protocol 0.3")
        assert (d / "old" / "plugin.yaml").read_text() == old

    def test_only_the_named_plugins_are_migrated(self, plugins):
        d = plugins()
        write_tree(
            d,
            {
                "new/plugin.yaml": OLD.replace("function:", 'protocol: "0.2"\nfunction:'),
                "new/function.py": "class Event:\n    pass\n",
            },
        )
        assert run(d, ["old"])[0] == 0
        assert read_manifest(d / "old")["protocol"] == "0.3"
        assert 'protocol: "0.2"' in (d / "new" / "plugin.yaml").read_text()

    def test_an_unknown_id_is_an_error(self, plugins):
        with pytest.raises(OwppError, match="no plugin nope"):
            run(plugins(), ["nope"])

    def test_the_command_migrates(self, plugins, capsys):
        d = plugins()
        assert main(["migrate", "--dir", str(d)], env={}) == 0
        assert "migrated 0.1 -> 0.2 -> 0.3" in capsys.readouterr().out
        assert read_manifest(d / "old")["protocol"] == "0.3"


class TestTrackToBranchOrTag:
    """0.2 -> 0.3: `source: track:` becomes `branch:` or `tag:`, as the repository says."""

    @pytest.mark.parametrize("kind", ["branch", "tag"])
    @pytest.mark.parametrize("flow", [False, True])
    def test_track_becomes_what_the_repository_says_it_is(self, plugins, kind, flow):
        d = plugins(old=tracked("v2", flow=flow))
        code, out = run(d, kinds={"v2": kind})
        assert code == 0 and "migrated 0.2 -> 0.3" in out
        assert run.asked == [(GIT, "v2")]
        text = (d / "old" / "plugin.yaml").read_text()
        assert text == tracked("v2", '"0.3"', flow).replace("track:", f"{kind}:")
        assert read_manifest(d / "old")["source"][kind] == "v2"

    def test_a_name_it_cannot_decide_is_left_for_the_user(self, plugins):
        d = plugins(old=tracked("main"))
        write_tree(d, {"plain/plugin.yaml": 'protocol: "0.2"\nfunction: {title: T}\n'})
        code, out = run(d)
        assert code == 1
        assert "FAIL  old: could not tell whether `track: main` is a branch or a tag" in out
        assert "migrated 0.2 -> 0.3" in out  # the others are migrated
        assert (d / "old" / "plugin.yaml").read_text() == tracked("main")

    def test_a_0_3_manifest_with_track_is_refused(self, plugins):
        d = plugins(old=tracked("main", '"0.3"'))
        with pytest.raises(OwppError, match="track is gone in protocol 0.3.*owpp migrate"):
            read_manifest(d / "old")


class TestSteps:
    """One step per version, so a future version only has to add its own step."""

    def test_a_manifest_can_move_through_more_than_one_step(self, monkeypatch):
        from owpp import migrate as mod

        monkeypatch.setattr(
            mod,
            "STEPS",
            (
                mod.Step(
                    "0.0", "0.1", lambda text, manifest, kind_of: text.replace('"0.0"', '"0.1"')
                ),
                *mod.STEPS,
            ),
        )
        text, old, steps = migrate_text(
            'protocol: "0.0"\nfunction: {title: T}\n', "0.0", "p/plugin.yaml"
        )
        assert old == "0.0" and steps == ["0.0", "0.1", "0.2"]
        assert 'protocol: "0.3"' in text

    def test_a_version_with_no_step_is_refused(self):
        with pytest.raises(OwppError, match="cannot migrate protocol 0.0"):
            migrate_text('protocol: "0.0"\n', "0.0", "p/plugin.yaml")
