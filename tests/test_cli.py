"""The CLI: check, init, and the commands end to end."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import EXAMPLES, FILTER, fake_remote

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


class TestScaffold:
    @pytest.mark.parametrize("kind", ["event", "filter", "action", "pipe"])
    def test_init_scaffolds_a_plugin_that_bundles_compiles_and_is_documented(self, tmp_path, kind):
        scaffold(tmp_path, "my_plugin", kind)
        (fn,) = load_function_files(tmp_path)
        assert fn.type == kind
        assert check_bundle(fn.content, "my_plugin.py") is None
        readme = (tmp_path / "my_plugin" / "README.md").read_text()
        assert "\n## Test" in readme and "\n## Deploy" in readme
        with pytest.raises(OwppError, match="already exists"):
            scaffold(tmp_path, "my_plugin", kind)

    def test_init_refuses_ids_open_webui_would_reject(self, tmp_path):
        with pytest.raises(OwppError, match="not a valid id"):
            scaffold(tmp_path, "my-plugin")


class TestCommands:
    def test_deploy_refuses_without_a_url_or_a_key(self, capsys):
        assert main(["deploy", "--dir", "/nonexistent"], env={}) == 1
        assert "OPEN_WEBUI_URL is not set" in capsys.readouterr().err
        assert main(["deploy", "--dir", "/nonexistent"], env={"OPEN_WEBUI_URL": "http://x"}) == 1
        assert "OPEN_WEBUI_API_KEY is not set" in capsys.readouterr().err

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
        (fn,) = [
            f for f in load_function_files(EXAMPLES, fake_remote(EXAMPLES)) if f.id == "mcpo_sync"
        ]
        assert out.read_bytes() == fn.content.encode("utf-8")

    def test_init_creates_the_folder(self, tmp_path, capsys):
        assert main(["init", "hello", "--type", "pipe", "--dir", str(tmp_path)], env={}) == 0
        assert (tmp_path / "hello" / "plugin.yaml").exists()
        assert "created" in capsys.readouterr().out

    def test_bundle_parts_lists_the_function_then_its_tools(self):
        (fn,) = [
            f for f in load_function_files(EXAMPLES, fake_remote(EXAMPLES)) if f.id == "excalidraw"
        ]
        assert [name for name, _ in bundle_parts(fn)] == ["excalidraw", "tool excalidraw"]


def test_runs_as_a_module_and_reports_its_version():
    done = subprocess.run(
        [sys.executable, "-m", "owpp", "--version"], capture_output=True, text=True
    )
    assert done.returncode == 0
    assert done.stdout.strip() == f"owpp {__version__}"
