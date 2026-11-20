"""`owpp migrate`: bringing a plugin.yaml written for protocol 0.1 up to 0.2."""

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


def run(directory, ids=None, dry_run=False):
    lines: list[str] = []
    code = migrate(directory, ids, dry_run=dry_run, out=lines.append)
    return code, "\n".join(lines)


class TestMigrate:
    def test_it_adds_the_key_and_leaves_everything_else_alone(self, plugins):
        d = plugins()
        assert run(d) == (0, "new   old: migrated 0.1 -> 0.2\n        wrote plugin.yaml")
        text = (d / "old" / "plugin.yaml").read_text()
        assert text.startswith(
            '# Written before plugin.yaml had a protocol key.\nprotocol: "0.2"\n'
        )
        assert "  version: 0.1.0\ninclude: [events]\n" in text
        assert read_manifest(d / "old")["protocol"] == "0.2"

    def test_a_dry_run_writes_nothing(self, plugins):
        d = plugins()
        code, out = run(d, dry_run=True)
        assert code == 0 and "would migrate 0.1 -> 0.2" in out
        assert (d / "old" / "plugin.yaml").read_text() == OLD

    def test_an_explicit_old_version_is_replaced_keeping_its_comment(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.1" # when we started\nfunction:')
        d = plugins(old=old)
        assert run(d)[0] == 0
        assert 'protocol: "0.2" # when we started\n' in (d / "old" / "plugin.yaml").read_text()

    def test_a_plugin_already_at_the_current_version_is_left_alone(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.2"\nfunction:')
        d = plugins(old=old)
        assert run(d) == (0, "ok    old: protocol 0.2")
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
        assert read_manifest(d / "old")["protocol"] == "0.2"
        assert 'protocol: "0.2"' in (d / "new" / "plugin.yaml").read_text()

    def test_an_unknown_id_is_an_error(self, plugins):
        with pytest.raises(OwppError, match="no plugin nope"):
            run(plugins(), ["nope"])

    def test_the_command_migrates(self, plugins, capsys):
        d = plugins()
        assert main(["migrate", "--dir", str(d)], env={}) == 0
        assert "migrated 0.1 -> 0.2" in capsys.readouterr().out
        assert read_manifest(d / "old")["protocol"] == "0.2"


class TestSteps:
    """One step per version, so a future version only has to add its own step."""

    def test_a_manifest_can_move_through_more_than_one_step(self, monkeypatch):
        from owpp import migrate as mod

        monkeypatch.setattr(
            mod,
            "STEPS",
            (
                mod.Step("0.0", "0.1", lambda text: text.replace('"0.0"', '"0.1"')),
                *mod.STEPS,
            ),
        )
        text, old, steps = migrate_text(
            'protocol: "0.0"\nfunction: {title: T}\n', "0.0", "p/plugin.yaml"
        )
        assert old == "0.0" and steps == ["0.0", "0.1"]
        assert 'protocol: "0.2"' in text

    def test_a_version_with_no_step_is_refused(self):
        with pytest.raises(OwppError, match="cannot migrate protocol 0.0"):
            migrate_text('protocol: "0.0"\n', "0.0", "p/plugin.yaml")
