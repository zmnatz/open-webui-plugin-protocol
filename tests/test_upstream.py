"""A whole plugin folder taken from git (`source: {plugin: true}`), built by the owpp reading it."""

from __future__ import annotations

import pytest
from conftest import embedded, write_tree

from owpp.bundle import load_function_files
from owpp.deploy import _needing_iframe_sandbox
from owpp.errors import OwppError
from owpp.pull import pull, set_ref
from owpp.sources import Sources
from owpp.versioning import bump, versions_of

SHA = "0123456789abcdef0123456789abcdef01234567"
NEW = "89abcdef0123456789abcdef0123456789abcdef"
REPO = "https://example.com/owner/repo.git"
INNER = "https://example.com/other/tools.git"

UPSTREAM_MANIFEST = """protocol: "0.2"
function:
  title: Viz
  version: 1.2.0
  global: true
  valves:
    COLOR: blue
    SIZE: 3
tool:
  id: viz_tool
  access: public
requires:
  iframe_sandbox_allow_same_origin: true
"""
FUNCTION = """from pydantic import BaseModel


class Filter:
    class Valves(BaseModel):
        COLOR: str = "red"
        SIZE: int = 1

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict) -> dict:
        return body
"""
TOOL = '''class Tools:
    def draw(self, what: str) -> str:
        """
        Draw something.

        :param what: What to draw.
        """
        return what
'''
SKILL = """---
name: drawing
description: How to draw.
access: public
---
Draw things.
"""
UPSTREAM = {
    "plugins/viz/plugin.yaml": UPSTREAM_MANIFEST,
    "plugins/viz/function.py": FUNCTION,
    "plugins/viz/tool.py": TOOL,
    "plugins/viz/skills/drawing/SKILL.md": SKILL,
    "plugins/viz/config.yaml": "greeting: upstream\n",
    "plugins/viz/tests/test_viz.py": "def test_it():\n    assert True\n",
}


def local(extra: str = "", ref: str = SHA) -> str:
    ref_line = f"  ref: {ref}\n" if ref else ""
    return (
        f'protocol: "0.2"\nsource:\n  git: {REPO}\n{ref_line}  path: plugins/viz\n'
        f"  plugin: true\n{extra}"
    )


def make_fetcher(repos: dict[tuple[str, str], dict[str, str]]):
    calls: list[tuple[str, str, list[str]]] = []

    def fetcher(git: str, ref: str, paths: list[str]) -> dict[str, str]:
        calls.append((git, ref, paths))
        files = repos[(git, ref)]
        out = {}
        for p in paths:
            if p.endswith("/"):
                out.update({k: v for k, v in files.items() if k.startswith(p)})
            elif p in files:
                out[p] = files[p]
        return out

    fetcher.calls = calls  # type: ignore[attr-defined]
    return fetcher


@pytest.fixture
def fetcher():
    return make_fetcher({(REPO, SHA): UPSTREAM})


def load(directory, fetcher_or_sources):
    sources = (
        fetcher_or_sources
        if isinstance(fetcher_or_sources, Sources)
        else Sources(fetcher_or_sources)
    )
    return {f.id: f for f in load_function_files(directory, sources)}


def test_the_whole_folder_is_one_directory_and_is_fetched_once(tmp_path, fetcher):
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    sources = Sources(fetcher)
    load(tmp_path, sources)
    load(tmp_path, sources)
    assert fetcher.calls == [(REPO, SHA, ["plugins/viz/"])]


def test_its_upstream_copy_is_gone_once_the_sources_is_closed(tmp_path, fetcher):
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    with Sources(fetcher) as sources:
        resolved = sources.resolve(tmp_path / "viz")
        root = resolved.root
        assert (root / "tests" / "test_viz.py").is_file()
        assert resolved.taken["plugins/viz/tool.py"] == TOOL
    assert not root.exists()
    with pytest.raises(OwppError, match="deleted when its Sources was closed"):
        _ = resolved.root


def test_it_is_bundled_as_the_upstream_plugin_with_the_local_id(tmp_path, fetcher):
    write_tree(tmp_path, {"mine/plugin.yaml": local()})
    item = load(tmp_path, fetcher)["mine"]
    assert item.type == "filter" and item.want_global
    assert "title: Viz" in item.content and "version: 1.2.0" in item.content
    data = embedded(item.content)
    assert [(t["id"], t["access"]) for t in data["tools"]] == [("viz_tool", "public")]
    assert [(s["id"], s["access"]) for s in data["skills"]] == [("drawing", "public")]
    assert item.valves == {"COLOR": "blue", "SIZE": 3}
    assert item.sources == {f"{REPO} plugins/viz": SHA}


def test_the_local_manifest_overrides_valves_global_and_the_tool(tmp_path, fetcher):
    extra = (
        "function:\n  global: false\n  valves:\n    COLOR: green\n"
        "tool:\n  id: my_tool\n  access: private\n"
    )
    write_tree(tmp_path, {"viz/plugin.yaml": local(extra)})
    item = load(tmp_path, fetcher)["viz"]
    assert not item.want_global and item.not_global
    assert item.valves == {"COLOR": "green", "SIZE": 3}  # merged, key by key
    data = embedded(item.content)
    assert [(t["id"], t["access"]) for t in data["tools"]] == [("my_tool", "private")]
    assert [(s["id"], s["access"]) for s in data["skills"]] == [("drawing", "public")]


def test_a_local_config_yaml_replaces_the_upstream_one(tmp_path, fetcher):
    write_tree(tmp_path, {"viz/plugin.yaml": local(), "viz/config.yaml": "greeting: mine\n"})
    assert "mine" in load(tmp_path, fetcher)["viz"].content
    write_tree(tmp_path / "other", {"viz/plugin.yaml": local()})
    assert "upstream" in load(tmp_path / "other", fetcher)["viz"].content


@pytest.mark.parametrize(
    ("extra", "named"),
    [
        ("include: [core]\n", "include"),
        ("function:\n  title: Mine\n", "function.title"),
        ("tool:\n  file: tool.py\n", "tool.file"),
        ("skills:\n  drawing:\n    access: private\n", "skills"),
    ],
)
def test_anything_but_the_overrides_is_refused(tmp_path, fetcher, extra, named):
    write_tree(tmp_path, {"viz/plugin.yaml": local(extra)})
    with pytest.raises(OwppError, match=rf"only function\.valves.*remove {named}"):
        load(tmp_path, fetcher)


def test_a_folder_with_no_plugin_yaml_is_refused(tmp_path):
    files = {k: v for k, v in UPSTREAM.items() if not k.endswith("plugin.yaml")}
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    with pytest.raises(OwppError, match="no plugin.yaml, so it is not an owpp plugin"):
        load(tmp_path, make_fetcher({(REPO, SHA): files}))


def test_an_upstream_on_a_newer_protocol_is_refused(tmp_path):
    files = {**UPSTREAM, "plugins/viz/plugin.yaml": 'protocol: "9.0"\nfunction: {title: Viz}\n'}
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    with pytest.raises(OwppError, match="upstream .* protocol 9.0 is newer than owpp supports"):
        load(tmp_path, make_fetcher({(REPO, SHA): files}))


def test_an_upstream_that_takes_a_whole_plugin_itself_is_refused(tmp_path):
    inner = f"source: {{git: {INNER}, ref: {NEW}, path: x, plugin: true}}\n"
    files = {**UPSTREAM, "plugins/viz/plugin.yaml": inner}
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    with pytest.raises(OwppError, match="takes a whole plugin from git itself"):
        load(tmp_path, make_fetcher({(REPO, SHA): files}))


def test_what_the_upstream_takes_from_git_itself_is_fetched_too(tmp_path):
    manifest = (
        f'protocol: "0.2"\nsource:\n  git: {INNER}\n  ref: {NEW}\n  path: t\n'
        "function:\n  title: Viz\ntool:\n  id: inner\n  file: tool.py\n"
    )
    files = {"plugins/viz/plugin.yaml": manifest}
    fetcher = make_fetcher({(REPO, SHA): files, (INNER, NEW): {"t/tool.py": TOOL}})
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    item = load(tmp_path, fetcher)["viz"]
    assert [t["id"] for t in embedded(item.content)["tools"]] == ["inner"]
    assert item.sources == {f"{REPO} plugins/viz": SHA, f"{INNER} t": NEW}


def test_a_source_with_no_ref_says_to_run_pull(tmp_path):
    write_tree(tmp_path, {"viz/plugin.yaml": local(ref="")})
    with pytest.raises(OwppError, match=r"has no `ref:`; run `owpp pull viz`"):
        Sources(make_fetcher({})).resolve(tmp_path / "viz")


def test_its_requirements_are_the_upstream_ones(tmp_path, fetcher):
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    assert _needing_iframe_sandbox(tmp_path, sources=Sources(fetcher)) == ["viz"]


def test_its_versions_are_the_upstream_ones(tmp_path):
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    assert versions_of(tmp_path, "viz") == [("function", "(the upstream's)")]
    with pytest.raises(OwppError, match="taken whole from git"):
        bump(tmp_path, "viz", "patch")


class TestSync:
    def run(self, directory, fetcher, dry_run=False):
        lines: list[str] = []
        code = pull(
            directory,
            dry_run=dry_run,
            sources=Sources(fetcher, lookup=lambda git, ref: NEW),
            out=lines.append,
            today="2026-11-20",
        )
        return code, "\n".join(lines)

    def test_it_adds_a_missing_ref(self, tmp_path):
        fetcher = make_fetcher({(REPO, NEW): UPSTREAM})
        write_tree(tmp_path, {"viz/plugin.yaml": "# mine\n" + local(ref="")})
        code, out = self.run(tmp_path, fetcher)
        assert code == 0 and f"pinned to {NEW}" in out
        text = (tmp_path / "viz/plugin.yaml").read_text()
        assert text == "# mine\n" + local(ref=NEW)  # added right after git:, the rest kept
        assert not (tmp_path / "viz/CHANGELOG.md").exists()

    def test_it_moves_the_ref_without_bumping_a_version(self, tmp_path):
        moved = {**UPSTREAM, "plugins/viz/tool.py": TOOL + "\n# new\n"}
        fetcher = make_fetcher({(REPO, SHA): UPSTREAM, (REPO, NEW): moved})
        write_tree(tmp_path, {"viz/plugin.yaml": local()})
        code, out = self.run(tmp_path, fetcher)
        assert code == 0 and "changed plugins/viz/tool.py" in out.replace("  ", " ")
        assert (tmp_path / "viz/plugin.yaml").read_text() == local(ref=NEW)
        assert "bump" not in out


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            f"source:\n  git: {REPO}\n  path: p\n",
            f"source:\n  git: {REPO}\n  ref: {NEW}\n  path: p\n",
        ),
        (
            f"source: {{git: {REPO}, path: p}}\n",
            f"source: {{git: {REPO}, ref: {NEW}, path: p}}\n",
        ),
        (
            f"source:\r\n    git: {REPO}  # where\r\n",
            f"source:\r\n    git: {REPO}  # where\r\n    ref: {NEW}\r\n",
        ),
    ],
)
def test_set_ref_adds_the_line_after_git(before, after):
    assert set_ref(before, "", NEW) == after


def test_set_ref_needs_a_git_line():
    with pytest.raises(OwppError, match="add it by hand"):
        set_ref("source:\n  path: p\nfunction: {}\n", "", NEW)


def test_the_mock_loads_it_from_stand_ins(tmp_path):
    from owpp.testing import MockOpenWebUI

    write_tree(tmp_path, {"viz/plugin.yaml": local("function:\n  valves:\n    SIZE: 9\n")})
    stand_ins = {k[len("plugins/viz/") :]: v for k, v in UPSTREAM.items()}
    with MockOpenWebUI(static_dir=tmp_path / "static") as owui:
        plugin = owui.load(tmp_path / "viz", sources=stand_ins)
        assert plugin.row.name == "Viz" and plugin.row.type == "filter"
        assert owui.function_valves["viz"] == {"COLOR": "blue", "SIZE": 9}


RUN_CLI = """
import json, sys
import owpp.cli as cli
from owpp.sources import Sources
files = json.load(open(sys.argv[1]))

def fetcher(git, ref, paths):
    return {k: v for k, v in files.items() if any(k.startswith(p) for p in paths)}

cli.Sources = lambda: Sources(fetcher)
sys.exit(cli.main(sys.argv[2:]))
"""


class TestOwppTestUpstream:
    UPSTREAM_TEST = (
        "import os\n\n\ndef test_sees_no_instance_settings(plugin_dir):\n"
        '    assert plugin_dir.name == "viz"\n'
        '    assert not [n for n in os.environ if n.startswith("OPEN_WEBUI_")]\n'
    )

    def run(self, tmp_path, *args):
        import json
        import os
        import subprocess
        import sys

        files = {**UPSTREAM, "plugins/viz/tests/test_viz.py": self.UPSTREAM_TEST}
        (tmp_path / "files.json").write_text(json.dumps(files))
        (tmp_path / "run.py").write_text(RUN_CLI)
        write_tree(tmp_path / "plugins", {"viz/plugin.yaml": local()})
        return subprocess.run(
            [sys.executable, str(tmp_path / "run.py"), str(tmp_path / "files.json")]
            + ["test", "--dir", str(tmp_path / "plugins"), *args, "--", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            env={**os.environ, "OPEN_WEBUI_API_KEY": "sk-secret", "OPEN_WEBUI_URL": "http://x"},
        )

    def test_upstream_tests_run_only_when_asked(self, tmp_path):
        done = self.run(tmp_path)
        assert done.returncode == 0, done.stdout + done.stderr
        assert "upstream tests not run (`owpp test --upstream` runs them): viz" in done.stdout

    def test_with_upstream_they_run_without_the_instance_settings(self, tmp_path):
        done = self.run(tmp_path, "--upstream")
        assert done.returncode == 0, done.stdout + done.stderr
        assert "viz: running the upstream plugin's tests" in done.stdout
        assert "1 passed" in done.stdout


def test_pull_lists_what_the_upstream_takes_from_git_itself(tmp_path):
    def upstream(ref: str) -> dict[str, str]:
        manifest = (
            f'protocol: "0.2"\nsource:\n  git: {INNER}\n  ref: {ref}\n  path: t\n'
            "function:\n  title: Viz\ntool:\n  id: inner\n  file: tool.py\n"
        )
        return {"plugins/viz/plugin.yaml": manifest}

    inner_new = "c" * 40
    fetcher = make_fetcher(
        {
            (REPO, SHA): upstream(NEW),
            (REPO, NEW): upstream(inner_new),
            (INNER, NEW): {"t/tool.py": TOOL},
            (INNER, inner_new): {"t/tool.py": TOOL + "\n# new\n"},
        }
    )
    write_tree(tmp_path, {"viz/plugin.yaml": local()})
    lines: list[str] = []
    code = pull(
        tmp_path,
        sources=Sources(fetcher, lookup=lambda git, ref: NEW),
        out=lines.append,
        today="2026-11-20",
    )
    out = "\n".join(lines)
    assert code == 0, out
    assert f"changed {INNER} t/tool.py" in out.replace("  ", " ")
    assert "changed plugins/viz/plugin.yaml" in out.replace("  ", " ")
