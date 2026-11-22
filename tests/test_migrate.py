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
        assert run(d) == (
            0,
            "new   old: migrated 0.1 -> 0.2 -> 0.3 -> 0.5\n        wrote plugin.yaml",
        )
        text = (d / "old" / "plugin.yaml").read_text()
        assert text.startswith(
            '# Written before plugin.yaml had a protocol key.\nprotocol: "0.5"\n'
        )
        assert "  version: 0.1.0\ninclude: [events]\n" in text
        assert read_manifest(d / "old")["protocol"] == "0.5"

    def test_a_dry_run_writes_nothing(self, plugins):
        d = plugins()
        code, out = run(d, dry_run=True)
        assert code == 0 and "would migrate 0.1 -> 0.2 -> 0.3 -> 0.5" in out
        assert (d / "old" / "plugin.yaml").read_text() == OLD

    def test_an_explicit_old_version_is_replaced_keeping_its_comment(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.1" # when we started\nfunction:')
        d = plugins(old=old)
        assert run(d)[0] == 0
        assert 'protocol: "0.5" # when we started\n' in (d / "old" / "plugin.yaml").read_text()

    def test_a_plugin_already_at_the_current_version_is_left_alone(self, plugins):
        old = OLD.replace("function:", 'protocol: "0.5"\nfunction:')
        d = plugins(old=old)
        assert run(d) == (0, "ok    old: protocol 0.5")
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
        assert read_manifest(d / "old")["protocol"] == "0.5"
        assert 'protocol: "0.2"' in (d / "new" / "plugin.yaml").read_text()

    def test_an_unknown_id_is_an_error(self, plugins):
        with pytest.raises(OwppError, match="no plugin nope"):
            run(plugins(), ["nope"])

    def test_the_command_migrates(self, plugins, capsys):
        d = plugins()
        assert main(["migrate", "--dir", str(d)], env={}) == 0
        assert "migrated 0.1 -> 0.2 -> 0.3 -> 0.5" in capsys.readouterr().out
        assert read_manifest(d / "old")["protocol"] == "0.5"


class TestTrackToBranchOrTag:
    """0.2 -> 0.3: `source: track:` becomes `branch:` or `tag:`, as the repository says."""

    @pytest.mark.parametrize("kind", ["branch", "tag"])
    @pytest.mark.parametrize("flow", [False, True])
    def test_track_becomes_what_the_repository_says_it_is(self, plugins, kind, flow):
        d = plugins(old=tracked("v2", flow=flow))
        code, out = run(d, kinds={"v2": kind})
        assert code == 0 and "migrated 0.2 -> 0.3 -> 0.5" in out
        assert run.asked == [(GIT, "v2")]
        text = (d / "old" / "plugin.yaml").read_text()
        assert text == tracked("v2", '"0.5"', flow).replace("track:", f"{kind}:")
        assert read_manifest(d / "old")["source"][kind] == "v2"

    def test_a_name_it_cannot_decide_is_left_for_the_user(self, plugins):
        d = plugins(old=tracked("main"))
        write_tree(d, {"plain/plugin.yaml": 'protocol: "0.2"\nfunction: {title: T}\n'})
        code, out = run(d)
        assert code == 1
        assert "FAIL  old: could not tell whether `track: main` is a branch or a tag" in out
        assert "migrated 0.2 -> 0.3 -> 0.5" in out  # the others are migrated
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
        assert old == "0.0" and steps == ["0.0", "0.1", "0.2", "0.3"]
        assert 'protocol: "0.5"' in text

    def test_a_version_with_no_step_is_refused(self):
        with pytest.raises(OwppError, match="cannot migrate protocol 0.0"):
            migrate_text('protocol: "0.0"\n', "0.0", "p/plugin.yaml")


V03 = 'protocol: "0.3"\nfunction:\n  title: T\ninclude: [routes, events]\ntool:\n  id: t\n'
SHARED = """# Shared: imports, constants and helpers.

import json
import re
from typing import Any, Optional

PREFIX = "/demo"
_ID = re.compile(r"[a-z]+")


def _load(raw: str) -> Optional[dict]:
    return json.loads(raw) if _ID.fullmatch(raw) else None
"""
FUNCTION = """# The function. Imports come from shared.py.

class Event(PluginEvents):
    @on("system.startup.completed")
    async def started(self, app):
        on = [PREFIX]  # a local that has the decorator's name
        plugin_mount(app, None, on[0])
        await _plugin_ensure()
        return json.dumps(_load("x"))
"""
TOOL = """class Tools:
    def go(self, data: Any) -> str:
        return PREFIX
"""


class TestTheImportsArriveIn0_5:
    """0.3 -> 0.5: a plugin's files import what they used to find in scope (owpp.imports)."""

    def migrated(self, tmp_path, **files):
        write_tree(
            tmp_path,
            {
                "p/plugin.yaml": V03,
                "p/shared.py": SHARED,
                "p/function.py": FUNCTION,
                "p/tool.py": TOOL,
                **files,
            },
        )
        code, out = run(tmp_path)
        return (
            code,
            out,
            {n: (tmp_path / "p" / n).read_text() for n in ("shared.py", "function.py", "tool.py")},
        )

    def test_each_file_imports_what_it_takes_from_shared_py_the_libraries_and_elsewhere(
        self, tmp_path
    ):
        code, out, files = self.migrated(tmp_path)
        assert code == 0, out
        assert "wrote function.py" in out and "wrote tool.py" in out and "wrote shared.py" in out
        function = files["function.py"]
        assert "import json\n" in function  # shared.py imported it for this file
        assert "from owpp.lib import PluginEvents, on, plugin_ensure, plugin_mount\n" in function
        assert "from shared import PREFIX, _load\n" in function
        assert "await plugin_ensure()" in function and "_plugin_ensure" not in function
        assert "from typing import Any\n" in files["tool.py"]
        assert "from shared import PREFIX\n" in files["tool.py"]
        # shared.py keeps what it uses itself and loses what only the tool used
        assert "import json\nimport re\nfrom typing import Optional\n" in files["shared.py"]

    def test_the_result_bundles_and_reads_as_python_on_its_own(self, tmp_path):
        """What the bundler refuses from a 0.3 plugin, it accepts once migrated."""
        from owpp.bundle import load_function_files
        from owpp.flatten import unbound
        from owpp.imports import BUILTINS

        self.migrated(tmp_path)
        (fn,) = load_function_files(tmp_path)
        compile(fn.content, "p.py", "exec")
        for name in ("shared.py", "function.py", "tool.py"):
            text = (tmp_path / "p" / name).read_text()
            assert set(unbound(text)) <= BUILTINS, name

    def test_a_name_it_cannot_place_is_reported_and_the_rest_is_done(self, tmp_path):
        code, out, files = self.migrated(
            tmp_path, **{"p/tool.py": "class Tools:\n    x = MYSTERY\n"}
        )
        assert code == 1
        assert "tool.py:2: MYSTERY is not defined anywhere owpp knows of: import it" in out
        assert "from shared import PREFIX, _load\n" in files["function.py"]

    def test_a_dry_run_says_which_files_it_would_write(self, tmp_path):
        write_tree(
            tmp_path, {"p/plugin.yaml": V03, "p/shared.py": SHARED, "p/function.py": FUNCTION}
        )
        code, out = run(tmp_path, dry_run=True)
        assert "would write function.py" in out
        assert "          +from shared import PREFIX, _load" in out  # what it would add
        assert "would write shared.py" not in out  # it still uses every import it has
        assert (tmp_path / "p" / "function.py").read_text() == FUNCTION

    def test_future_imports_become_the_same_in_every_file(self, tmp_path):
        _, _, files = self.migrated(
            tmp_path, **{"p/shared.py": "from __future__ import annotations\n\n" + SHARED}
        )
        for name in ("function.py", "tool.py"):
            assert "from __future__ import annotations\n" in files[name], name

    def test_a_postponed_annotation_still_gets_its_import(self, tmp_path):
        """FastAPI resolves `user: PluginAdmin` by name at run time, from the module."""
        function = (
            "from __future__ import annotations\n\n"
            "async def page(user: PluginAdmin):\n    pass\n\nclass Event:\n    pass\n"
        )
        write_tree(tmp_path, {"p/plugin.yaml": V03, "p/function.py": function})
        assert run(tmp_path)[0] == 0
        assert "from owpp.lib import PluginAdmin\n" in (tmp_path / "p" / "function.py").read_text()

    def test_a_local_file_beside_code_taken_from_git_is_migrated(self, tmp_path):
        """With only the tool taken from git, the function is the folder's, and the bundler
        refuses it without imports."""
        manifest = (
            f'protocol: "0.3"\nsource: {{git: {GIT}, ref: {SHA}, path: p}}\n'
            "function:\n  title: T\ninclude: [events]\ntool:\n  id: t\n  file: tool.py\n"
        )
        write_tree(
            tmp_path, {"p/plugin.yaml": manifest, "p/function.py": FUNCTION, "p/tool.py": TOOL}
        )
        run(tmp_path)
        assert "from owpp.lib import" in (tmp_path / "p" / "function.py").read_text()
        assert (tmp_path / "p" / "tool.py").read_text() == TOOL  # the bundler takes git's

    def test_code_taken_from_git_is_left_alone(self, tmp_path):
        manifest = f'protocol: "0.3"\nsource: {{git: {GIT}, ref: {SHA}, path: p}}\nfunction:\n  file: f.py\n'
        write_tree(tmp_path, {"p/plugin.yaml": manifest, "p/function.py": FUNCTION})
        code, out = run(tmp_path)
        assert code == 0 and "wrote function.py" not in out
        assert (tmp_path / "p" / "function.py").read_text() == FUNCTION

    def test_a_current_plugin_needs_nothing(self, tmp_path):
        write_tree(
            tmp_path,
            {
                "p/plugin.yaml": V03,
                "p/function.py": "from owpp.lib import on\n\nclass Event:\n    pass\n",
            },
        )
        code, out = run(tmp_path)
        assert code == 0 and out.splitlines()[1:] == ["        wrote plugin.yaml"]
