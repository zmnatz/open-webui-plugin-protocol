"""The CLI: check, init, and the commands end to end."""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import EXAMPLES, FILTER, fake_sources, write_tree

from owpp import __version__, cli
from owpp.bundle import load_function_files
from owpp.check import check_bundle
from owpp.cli import main, scaffold
from owpp.errors import OwppError


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

    def test_check_prints_the_findings_and_exits_1_on_a_failure(self, functions_dir, capsys):
        d = functions_dir({"good.py": FILTER, "bad.py": FILTER + "x = typo\n"})
        assert main(["check", "--dir", str(d)], env={}) == 1
        assert capsys.readouterr().out.splitlines() == [
            "FAIL  bad: undefined names: typo",
            f"ok    good ({len(FILTER)} chars)",
        ]
        assert main(["check", "good", "--dir", str(d)], env={}) == 0
        capsys.readouterr()
        assert main(["check", "nope", "--dir", str(d)], env={}) == 1
        assert capsys.readouterr() == ("", f"no plugin nope in {d.resolve()}\n")

    def test_check_counts_the_warnings_and_strict_fails_on_them(self, tmp_path, capsys):
        write_tree(
            tmp_path / "p",
            {"plugin.yaml": "function: {title: T}\n", "function.py": "class Event:\n    pass\n"},
        )
        assert main(["check", "--dir", str(tmp_path)], env={}) == 0
        lines = capsys.readouterr().out.splitlines()
        assert [line[:6] for line in lines[:2]] == ["ok    ", "warn  "]
        assert lines[2:] == ["1 warning(s)"]
        assert main(["check", "--strict", "--dir", str(tmp_path)], env={}) == 1
        out = capsys.readouterr().out
        assert out.splitlines()[-1] == "1 warning(s); failing because of --strict"

    def test_bundle_writes_the_exact_deployed_code(self, tmp_path):
        out = tmp_path / "out.py"
        assert main(["bundle", "mcpo_sync", str(out), "--dir", str(EXAMPLES)], env={}) == 0
        (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "mcpo_sync"]
        assert out.read_bytes() == fn.content.encode("utf-8")

    def test_init_creates_the_folder(self, tmp_path, capsys):
        assert main(["init", "hello", "--type", "pipe", "--dir", str(tmp_path)], env={}) == 0
        assert (tmp_path / "hello" / "plugin.yaml").exists()
        assert "created" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["create", "import"])
def test_create_and_import_check_without_running_the_command_line_again(
    command, tmp_path, monkeypatch, capsys
):
    parsed = []
    parser = cli.build_parser
    monkeypatch.setattr(cli, "build_parser", lambda: parsed.append(1) or parser())
    if command == "create":
        (tmp_path / "spec.yaml").write_text("id: demo\n")
        argv = ["create", "--spec", str(tmp_path / "spec.yaml")]
    else:
        (tmp_path / "demo.py").write_text(FILTER)
        argv = ["import", str(tmp_path / "demo.py")]
    assert main([*argv, "--dir", str(tmp_path / "plugins")], env={}) == 0
    assert "ok    demo (" in capsys.readouterr().out
    assert len(parsed) == 1


class TestTestCommand:
    """`owpp test` runs in a child process: it starts a pytest run of its own."""

    @staticmethod
    def owpp_test(directory, *args):
        return subprocess.run(
            [sys.executable, "-m", "owpp", "test", "--dir", str(directory), *args],
            capture_output=True,
            text=True,
        )

    def test_editor_prints_the_open_webui_code_the_tests_run(self, tmp_path, monkeypatch, capsys):
        """An editor resolves `open_webui` from that folder; it needs no plugins folder."""
        from owpp.testing import pin

        cached = tmp_path / "cache" / f"open-webui-{pin.VERSION}"
        (cached / "open_webui").mkdir(parents=True)
        (cached / ".sha256").write_text(pin.WHEEL_SHA256)
        monkeypatch.setenv("OWPP_CACHE_DIR", str(tmp_path / "cache"))
        assert main(["test", "--editor", "--dir", str(tmp_path / "none")], env={}) == 0
        assert capsys.readouterr().out.strip() == str(cached)

    # That every scaffold passes its own tests is test_create's: `owpp init` writes what
    # `owpp create` writes with every answer the default.

    def test_it_runs_the_plugins_named_fails_on_a_failing_test_and_notes_those_without(
        self, tmp_path
    ):
        """One pytest run (each starts Open-WebUI): a failing test fails the command, a plugin
        not named is not run, and a plugin with no tests/ folder is noted."""
        scaffold(tmp_path, "demo", "event")
        (tmp_path / "demo" / "tests" / "test_more.py").write_text(
            "def test_valves(plugin):\n    assert plugin.valves.ENABLE is False\n"
        )
        scaffold(tmp_path, "skipped", "event")
        scaffold(tmp_path, "b", "event")
        (tmp_path / "b" / "tests" / "test_b.py").unlink()
        (tmp_path / "b" / "tests").rmdir()
        done = self.owpp_test(tmp_path, "demo", "b", "--", "-p", "no:cacheprovider")
        assert done.returncode == 1, done.stdout + done.stderr
        assert "1 failed, 2 passed" in done.stdout and "note  no tests/ folder: b" in done.stdout
        assert "skipped" not in done.stdout
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
