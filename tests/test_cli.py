"""The CLI: check, init, and the commands end to end."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import EXAMPLES, FILTER, fake_sources, write_tree

from owpp import __version__
from owpp.bundle import load_function_files
from owpp.cli import bundle_parts, check_bundle, main, scaffold
from owpp.errors import OwppError


class TestCheckBundle:
    def test_accepts_good_code(self):
        assert check_bundle("import os\nx = os.getcwd()\n") is None

    def test_reports_a_syntax_error(self):
        assert "does not compile" in check_bundle("def f(:\n")

    def test_reports_undefined_names(self):
        assert check_bundle("x = typo_name + 1\n") == "undefined names: typo_name"

    def test_names_defined_by_imports_arguments_and_handlers_are_fine(self):
        code = "import a.b as c\ndef f(arg):\n    try:\n        return arg + c\n    except E as err:\n        return err\nclass E(Exception): pass\n"
        assert check_bundle(code) is None

    def test_a_name_used_only_when_globals_has_it_is_fine(self):
        """The assets library calls live_reload's functions only when that library is there."""
        code = 'def f():\n    if "reload_active" in globals():\n        return reload_active()\n'
        assert check_bundle(code) is None
        assert check_bundle("def f():\n    return reload_active()\n") is not None


class TestScaffold:
    @pytest.mark.parametrize("kind", ["event", "filter", "action", "pipe"])
    def test_init_scaffolds_a_plugin_that_bundles_compiles_and_is_documented(self, tmp_path, kind):
        scaffold(tmp_path, "my_plugin", kind)
        (fn,) = load_function_files(tmp_path)
        assert fn.type == kind
        assert check_bundle(fn.content, "my_plugin.py") is None
        readme = (tmp_path / "my_plugin" / "README.md").read_text()
        assert "\n## Test" in readme and "\n## Deploy" in readme
        assert "owpp test my_plugin" in readme
        assert (tmp_path / "my_plugin" / "tests" / "test_my_plugin.py").is_file()
        with pytest.raises(OwppError, match="already exists"):
            scaffold(tmp_path, "my_plugin", kind)

    def test_init_refuses_ids_open_webui_would_reject(self, tmp_path):
        with pytest.raises(OwppError, match="not a valid id"):
            scaffold(tmp_path, "my-plugin")


class TestCommands:
    def test_deploy_refuses_without_a_url(self, capsys):
        assert main(["deploy", "--dir", "/nonexistent"], env={}) == 1
        assert "OPEN_WEBUI_URL is not set" in capsys.readouterr().err

    def test_list_prints_id_type_and_global(self, functions_dir, capsys):
        d = functions_dir(
            {"a.py": FILTER.replace("author: me\n", "author: me\nglobal: true\n"), "b.py": FILTER}
        )
        assert main(["list", "--dir", str(d)], env={}) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines == [f"{'a':<24}filter (global)", f"{'b':<24}filter"]

    def test_list_without_a_plugins_folder_is_an_error(self, tmp_path):
        with pytest.raises(OwppError, match="no plugins folder"):
            main(["list", "--dir", str(tmp_path / "nope")], env={})

    def test_check_reports_ok_and_fail(self, functions_dir, capsys):
        d = functions_dir({"good.py": FILTER, "bad.py": FILTER + "x = typo\n"})
        assert main(["check", "--dir", str(d)], env={}) == 1
        out = capsys.readouterr().out
        assert "ok    good" in out and "FAIL  bad: undefined names: typo" in out
        assert main(["check", "good", "--dir", str(d)], env={}) == 0
        assert main(["check", "nope", "--dir", str(d)], env={}) == 1

    def test_check_covers_the_embedded_tool(self, tmp_path, capsys):
        scaffold(tmp_path, "viz", "filter")
        (tmp_path / "viz" / "plugin.yaml").write_text(
            "function:\n  title: Viz\ntool:\n  title: Viz Tool\n"
        )
        (tmp_path / "viz" / "tool.py").write_text("class Tools:\n    x = missing\n")
        assert main(["check", "--dir", str(tmp_path)], env={}) == 1
        assert "FAIL  tool viz: undefined names: missing" in capsys.readouterr().out

    def test_bundle_writes_the_exact_deployed_code(self, tmp_path):
        out = tmp_path / "out.py"
        assert main(["bundle", "mcpo_sync", str(out), "--dir", str(EXAMPLES)], env={}) == 0
        (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "mcpo_sync"]
        assert out.read_bytes() == fn.content.encode("utf-8")

    def test_init_creates_the_folder(self, tmp_path, capsys):
        assert main(["init", "hello", "--type", "pipe", "--dir", str(tmp_path)], env={}) == 0
        assert (tmp_path / "hello" / "plugin.yaml").exists()
        assert "created" in capsys.readouterr().out

    def test_bundle_parts_lists_the_function_then_its_tools(self):
        (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "excalidraw"]
        assert [name for name, _ in bundle_parts(fn)] == ["excalidraw", "tool excalidraw"]


class TestCheckProtocol:
    """A missing protocol is a warning (0.1 plugins predate the key); an older one is a note."""

    def make(self, tmp_path, line=""):
        write_tree(
            tmp_path / "p",
            {
                "plugin.yaml": f"{line}function: {{title: T}}\n",
                "function.py": "class Event:\n    pass\n",
            },
        )

    def test_a_missing_key_warns(self, tmp_path, capsys):
        self.make(tmp_path)
        assert main(["check", "--dir", str(tmp_path)], env={}) == 0
        out = capsys.readouterr().out
        assert "warn  p/plugin.yaml: no `protocol:` key" in out
        assert "owpp migrate" in out and "1 warning(s)" in out

    def test_strict_fails_on_a_missing_key(self, tmp_path):
        self.make(tmp_path)
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 1

    def test_an_older_protocol_is_a_note_and_still_passes_strict(self, tmp_path, capsys):
        self.make(tmp_path, 'protocol: "0.1"\n')
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 0
        out = capsys.readouterr().out
        assert "note  p/plugin.yaml: protocol 0.1" in out and "owpp migrate" in out
        assert "warning(s)" not in out

    def test_the_current_protocol_is_quiet(self, tmp_path, capsys):
        self.make(tmp_path, 'protocol: "0.3"\n')
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 0
        assert "protocol" not in capsys.readouterr().out


class TestTestCommand:
    """`owpp test` runs in a child process: it starts a pytest run of its own."""

    @staticmethod
    def owpp_test(directory, *args):
        return subprocess.run(
            [sys.executable, "-m", "owpp", "test", "--dir", str(directory), *args],
            capture_output=True,
            text=True,
        )

    def test_every_scaffold_passes_its_own_tests(self, tmp_path):
        for kind in ("event", "filter", "action", "pipe"):
            scaffold(tmp_path, f"demo_{kind}", kind)
        done = self.owpp_test(tmp_path, "--", "-p", "no:cacheprovider")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "8 passed" in done.stdout

    def test_a_failing_plugin_test_fails_the_command(self, tmp_path):
        scaffold(tmp_path, "demo", "event")
        (tmp_path / "demo" / "tests" / "test_more.py").write_text(
            "def test_valves(plugin):\n    assert plugin.valves.ENABLE is False\n"
        )
        done = self.owpp_test(tmp_path, "demo", "--", "-p", "no:cacheprovider")
        assert done.returncode == 1 and "1 failed, 2 passed" in done.stdout

    def test_it_runs_only_the_plugins_named_and_notes_those_without_tests(self, tmp_path):
        scaffold(tmp_path, "a", "event")
        scaffold(tmp_path, "b", "event")
        (tmp_path / "b" / "tests" / "test_b.py").unlink()
        (tmp_path / "b" / "tests").rmdir()
        done = self.owpp_test(tmp_path, "--", "-p", "no:cacheprovider")
        assert done.returncode == 0 and "note  no tests/ folder: b" in done.stdout
        assert self.owpp_test(tmp_path, "b").returncode == 1
        assert "no plugin nope" in self.owpp_test(tmp_path, "nope").stderr

    def test_arguments_after_the_separator_are_only_for_test(self, capsys):
        with pytest.raises(SystemExit):
            main(["list", "--", "-x"], env={})
        assert "only `owpp test`" in capsys.readouterr().err


def test_runs_as_a_module_and_reports_its_version():
    done = subprocess.run(
        [sys.executable, "-m", "owpp", "--version"], capture_output=True, text=True
    )
    assert done.returncode == 0
    assert done.stdout.strip() == f"owpp {__version__}"


@pytest.mark.parametrize("argv", [["sync"], ["deploy", "--dry-run", "--sync"]])
def test_the_names_from_before_pull_and_latest_are_gone(argv, capsys):
    """`owpp sync` became `owpp pull`, and deploy's `--sync` became `--latest`: no aliases."""
    with pytest.raises(SystemExit) as raised:
        main(argv, env={})
    assert raised.value.code == 2
    err = capsys.readouterr().err
    assert "invalid choice: 'sync'" in err or "unrecognized arguments: --sync" in err
