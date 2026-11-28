"""`owpp check` as a module (owpp.check): the findings, and what makes a check fail."""

from __future__ import annotations

import sys

import pytest
from conftest import EXAMPLES, FILTER, FakeRepo, fake_sources, write_tree

from owpp.bundle import load_function_files
from owpp.check import (
    Finding,
    UnknownPlugin,
    bundle_parts,
    check_bundle,
    check_plugins,
    failed,
    warning_count,
)
from owpp.cli import scaffold
from owpp.errors import OwppError

CLEAN = {
    "plugin.yaml": 'protocol: "0.7"\nfunction:\n  title: T\n',
    "function.py": "class Event:\n    pass\n",
}


class TestCheckBundle:
    def test_accepts_good_code(self):
        assert check_bundle("import os\nx = os.getcwd()\n") is None

    def test_reports_a_syntax_error(self):
        assert "does not compile" in check_bundle("def f(:\n")

    def test_reports_undefined_names_in_order(self):
        assert check_bundle("x = typo_name + 1\n") == "undefined names: typo_name"
        assert check_bundle("b()\na()\n") == "undefined names: a, b"

    def test_names_defined_by_imports_arguments_and_handlers_are_fine(self):
        code = "import a.b as c\ndef f(arg):\n    try:\n        return arg + c\n    except E as err:\n        return err\nclass E(Exception): pass\n"
        assert check_bundle(code) is None

    def test_a_name_used_only_when_globals_has_it_is_fine(self):
        """The assets library calls live_reload's functions only when that library is there."""
        code = 'def f():\n    if "reload_active" in globals():\n        return reload_active()\n'
        assert check_bundle(code) is None
        assert check_bundle("def f():\n    return reload_active()\n") is not None

    @pytest.mark.parametrize(
        "code",
        [
            "def f():\n    global x\n    x = 1\ndef g():\n    return x\n",
            "def f():\n    global os\n    import os\ndef g():\n    return os\n",
            "z = [(y := i) for i in range(3)]\nprint(y)\n",
            "class F:\n    class Valves: pass\n    valves: Valves\n"
            "    def f(self, v: Valves) -> Valves:\n        return v\n",
            "from __future__ import annotations\nclass F:\n    class Valves: pass\n"
            "    def f(self, v: Valves) -> Valves:\n        return v\n",
            "def f():\n    class L: pass\n    def g(a: L) -> L:\n        b: L = a\n"
            "        return b\n    return g\n",
            "from typing import Annotated\nx: Annotated[str, lambda v: v] = ''\n"
            "y: Annotated[str, [i for i in ()]] = ''\n",
            "def f():\n    return __name__, __doc__\nclass A:\n    def g(self): return __class__\n",
            "def top(a):\n    b = a\n    return b\n",
            "def f(cls):\n    return super(cls, cls)\n",
        ],
        ids=[
            "global assigned in a function",
            "global imported in a function",
            "walrus in a module comprehension",
            "class names in a class's annotations",
            "the same, postponed",
            "local names in a nested function's annotations",
            "names bound inside an annotation",
            "module and class dunders",
            "a function called top, as symtable calls the module",
            "super outside a class",
        ],
    )
    def test_names_python_would_find_are_fine(self, code):
        assert check_bundle(code) is None

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="type parameters are Python 3.12")
    def test_type_parameters_are_fine(self):
        code = "def f[T](a: T) -> T:\n    b: T = a\n    return b\nclass C[U]:\n    x: U\n"
        assert check_bundle(code) is None

    @pytest.mark.parametrize(
        "code, name",
        [
            ("def f():\n    q = 1\ndef g():\n    return q\n", "q"),
            ("class A:\n    x = 1\n    def f(self):\n        return x\n", "x"),
            ("def f(a: Nope):\n    pass\n", "Nope"),
            ("class A:\n    class V: pass\ndef f(a: V):\n    pass\n", "V"),
            ("class A:\n    class V: pass\n    class B:\n        v: V\n", "V"),
            ("class A:\n    class V: pass\n    def f(self):\n        v: V = 1\n", "V"),
        ],
        ids=[
            "another function's local",
            "a class attribute from a method",
            "an annotation",
            "another class's name in an annotation",
            "an outer class's name in an annotation",
            "a class's name in a method body",
        ],
    )
    def test_a_name_defined_only_out_of_scope_is_undefined(self, code, name):
        assert check_bundle(code) == f"undefined names: {name}"


def test_bundle_parts_lists_the_function_then_its_tools():
    (fn,) = [f for f in load_function_files(EXAMPLES, fake_sources()) if f.id == "excalidraw"]
    assert [name for name, _ in bundle_parts(fn)] == ["excalidraw", "tool excalidraw"]


@pytest.mark.parametrize("kind", ["event", "filter", "action", "pipe"])
def test_every_scaffold_is_clean(tmp_path, kind):
    scaffold(tmp_path, "my_plugin", kind)
    (found,) = check_plugins(tmp_path)
    assert found.kind == "ok" and found.message.startswith("my_plugin (")


class TestFindings:
    def test_a_finding_reads_as_the_line_check_prints(self):
        assert str(Finding("ok", "a (1 chars)")) == "ok    a (1 chars)"
        assert str(Finding("fail", "x")) == "FAIL  x"
        assert str(Finding("warn", "x")) == "warn  x"
        assert str(Finding("note", "x")) == "note  x"
        assert str(Finding("env", "x")) == "env   x"

    def test_ok_and_fail(self, functions_dir):
        d = functions_dir({"good.py": FILTER, "bad.py": FILTER + "x = typo\n"})
        bad, good = check_plugins(d)
        assert bad == Finding("fail", "bad: undefined names: typo")
        assert good == Finding("ok", f"good ({len(FILTER)} chars)")
        assert failed([bad, good]) and not failed([good], strict=True)

    def test_only_the_plugins_named(self, functions_dir):
        d = functions_dir({"good.py": FILTER, "bad.py": FILTER + "x = typo\n"})
        assert [f.kind for f in check_plugins(d, ids=["good"])] == ["ok"]

    def test_an_unknown_plugin_is_refused(self, functions_dir):
        d = functions_dir({"good.py": FILTER})
        with pytest.raises(UnknownPlugin, match=f"no plugin nope, nah in {d}"):
            list(check_plugins(d, ids=["nope", "good", "nah"]))

    def test_a_missing_plugins_folder_is_an_error(self, tmp_path):
        with pytest.raises(OwppError, match="no plugins folder"):
            list(check_plugins(tmp_path / "nope"))

    def test_the_embedded_tool_is_checked(self, tmp_path):
        scaffold(tmp_path, "viz", "filter")
        (tmp_path / "viz" / "plugin.yaml").write_text(
            "function:\n  title: Viz\ntool:\n  title: Viz Tool\n"
        )
        (tmp_path / "viz" / "tool.py").write_text("class Tools:\n    x = missing\n")
        assert Finding("fail", "tool viz: undefined names: missing") in check_plugins(tmp_path)


class TestStrict:
    def test_warnings_fail_only_a_strict_check(self):
        found = [Finding("ok", "a"), Finding("warn", "b"), Finding("warn", "c")]
        assert warning_count(found) == 2
        assert not failed(found) and failed(found, strict=True)

    def test_notes_and_env_never_fail(self):
        found = [Finding("note", "a"), Finding("env", "b")]
        assert warning_count(found) == 0 and not failed(found, strict=True)

    def test_a_clean_plugin_has_nothing_to_warn_about(self, tmp_path):
        write_tree(tmp_path / "p", CLEAN)
        assert [f.kind for f in check_plugins(tmp_path)] == ["ok"]


def test_a_plugin_taken_whole_from_git_is_checked_in_its_upstream_folder(tmp_path):
    """Its changelog and its variables are the upstream's: the local folder has neither."""
    url, sha = "https://example.com/owner/repo.git", "a" * 40
    write_tree(
        tmp_path / "p",
        {"plugin.yaml": f"source: {{git: {url}, ref: {sha}, path: up, plugin: true}}\n"},
    )
    upstream = {
        "up/plugin.yaml": 'protocol: "0.7"\nfunction:\n  title: T\n  version: 1.2.0\n',
        "up/function.py": CLEAN["function.py"],
        "up/config.yaml": "greeting: ${GREETING:-hello}\n",
        "up/CHANGELOG.md": "# Changelog\n\n## 1.1.0\n",
    }
    found = [str(f) for f in check_plugins(tmp_path, FakeRepo(url, upstream).sources())]
    assert "warn  p/CHANGELOG.md has no `## 1.2.0` entry for the current version" in found
    assert "env   GREETING (default hello)" in found


class TestCheckProtocol:
    """A missing protocol is a warning (0.1 plugins predate the key); an older one is a note."""

    def check(self, tmp_path, line):
        write_tree(tmp_path / "p", {**CLEAN, "plugin.yaml": f"{line}function: {{title: T}}\n"})
        return list(check_plugins(tmp_path))[1:]

    def test_a_missing_key_warns(self, tmp_path):
        (found,) = self.check(tmp_path, "")
        assert found.kind == "warn"
        assert found.message.startswith("p/plugin.yaml: no `protocol:` key")
        assert "owpp migrate" in found.message

    def test_an_older_protocol_is_a_note(self, tmp_path):
        (found,) = self.check(tmp_path, 'protocol: "0.1"\n')
        assert found.kind == "note"
        assert found.message.startswith("p/plugin.yaml: protocol 0.1")
        assert "owpp migrate" in found.message

    def test_the_current_protocol_is_quiet(self, tmp_path):
        assert self.check(tmp_path, 'protocol: "0.7"\n') == []
