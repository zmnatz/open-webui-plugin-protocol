"""Plugin files taken from a git repo, pinned to a commit."""

from __future__ import annotations

import base64
import subprocess

import pytest
from conftest import embedded, write_tree

from owpp.bundle import load_function_files
from owpp.deploy import deploy
from owpp.errors import OwppError
from owpp.sources import fetch_sources, git_fetcher, source_key, source_keys

SHA = "0123456789abcdef0123456789abcdef01234567"
REPO = "https://example.com/owner/repo.git"
MANIFEST = f"""source:
  git: {REPO}
  ref: {SHA}
  path: sub/dir
function:
  title: Remote
  global: true
tool:
  id: remote_tool
  file: tool.py
  access: public
skills:
  visualize:
    file: SKILL.md
"""


def url(f: str) -> str:
    return f"{REPO}#{SHA}:sub/dir/{f}"


@pytest.fixture
def plugin(tmp_path):
    def make(manifest: str):
        write_tree(tmp_path / "remote", {"plugin.yaml": manifest})
        return tmp_path

    return make


def git(repo, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo, message="c", flags=("-a",)):
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", *flags, "-m", message)


def test_lists_the_urls_a_plugin_needs_pinned_to_the_commit(plugin):
    assert source_keys(plugin(MANIFEST)) == [url("tool.py"), url("SKILL.md")]


def test_embeds_the_fetched_tool_and_skill(plugin):
    remote = {
        url("tool.py"): '"""\ntitle: Up\n"""\nclass Tools:\n    pass\n',
        url("SKILL.md"): "---\nname: visualize\ndescription: d\n---\nbody\n",
    }
    (fn,) = load_function_files(plugin(MANIFEST), remote)
    data = embedded(fn.content)
    assert "title: Up" in data["tools"][0]["content"]
    assert data["tools"][0]["id"] == "remote_tool"
    assert [(s["id"], s["name"], [f["path"] for f in s["files"]]) for s in data["skills"]] == [
        ("visualize", "visualize", ["SKILL.md"])
    ]


def test_takes_the_function_from_the_source_verbatim_with_global_from_the_manifest(plugin):
    d = plugin(
        f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{file: event.py, global: true}}\n"
    )
    code = '"""\ntitle: Up\n"""\nclass Filter:\n    pass\n'
    remote = {source_key("p", {"git": REPO, "ref": SHA, "path": "x"}, "event.py"): code}
    assert len(source_keys(d)) == 1
    (fn,) = load_function_files(d, remote)
    assert fn.content == code
    assert fn.want_global is True
    assert fn.name == "Up"


def test_refuses_function_file_without_a_source_or_with_extra_header_keys(plugin, tmp_path):
    with pytest.raises(OwppError, match="needs a `source:`"):
        load_function_files(plugin("function: {file: event.py}\n"), {})
    from conftest import fake_remote

    d = tmp_path / "other"
    write_tree(
        d / "remote",
        {
            "plugin.yaml": f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{file: event.py, title: T}}\n"
        },
    )
    with pytest.raises(OwppError, match="remove title"):
        load_function_files(d, fake_remote(d))


def test_takes_a_whole_skill_folder_from_the_source(plugin):
    d = plugin(
        f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{title: T}}\n"
        "skills:\n  s: {dir: skills/s, access: public}\n"
    )
    base = f"{REPO}#{SHA}:x/skills/s/"
    assert source_keys(d) == [base]
    remote = {
        f"{base}SKILL.md": "---\nname: S\n---\nbody\n",
        f"{base}references/r.md": "r\n",
        f"{base}img.png": {"base64": "AAEC"},
    }
    (fn,) = load_function_files(d, remote)
    (skill,) = embedded(fn.content)["skills"]
    assert skill["access"] == "public"
    assert [f["path"] for f in skill["files"]] == ["SKILL.md", "img.png", "references/r.md"]
    assert skill["files"][1]["encoding"] == "base64"


def test_refuses_a_branch_or_tag_as_the_ref_and_paths_that_climb_out():
    src = {"git": REPO, "ref": "main", "path": "x"}
    with pytest.raises(OwppError, match="40-character commit SHA"):
        source_key("p", src, "tool.py")
    with pytest.raises(OwppError, match=r"\.\."):
        source_key("p", {**src, "ref": SHA}, "../../etc/passwd")
    for bad in (
        "no-slash",
        "/etc/repo",
        "ext::sh -c id",
        "file:///tmp/r",
        "--upload-pack=x",
        "https://h/r #x",
    ):
        with pytest.raises(OwppError, match="git URL"):
            source_key("p", {**src, "ref": SHA, "git": bad}, "t.py")
    for ok in ("https://h/o/r.git", "ssh://git@h/o/r.git", "git@h.example:o/r.git"):
        assert source_key("p", {**src, "ref": SHA, "git": ok}, "t.py").startswith(ok)


def test_fails_clearly_when_a_file_was_not_fetched(plugin):
    with pytest.raises(OwppError, match="was not fetched"):
        load_function_files(plugin(MANIFEST), {})


def test_fetch_sources_fetches_each_repo_once_and_reports_a_missing_or_oversized_file():
    calls = []

    def fetcher(git_url, ref, paths):
        calls.append((git_url, ref, paths))
        return {p: "hi" for p in paths}

    keys = [url("a.py"), url("b.py")]
    out = fetch_sources(keys, fetcher)
    assert len(calls) == 1
    assert list(out) == keys
    with pytest.raises(OwppError, match="not found"):
        fetch_sources(keys, lambda g, r, ps: {})
    with pytest.raises(OwppError, match="larger than"):
        fetch_sources(keys, lambda g, r, ps: {p: "x" * 2_000_001 for p in ps})


def test_deploy_fetches_the_sources_and_creates_the_function_with_them_embedded(
    plugin, mock_server
):
    m = mock_server()
    fetched = []

    def fetcher(git_url, ref, paths):
        fetched.append((git_url, ref, *paths))
        return {
            p: "---\nname: visualize\n---\nx\n"
            if p.endswith("SKILL.md")
            else "class Tools:\n    pass\n"
            for p in paths
        }

    res = deploy(m.options(plugin(MANIFEST), git_fetcher=fetcher))
    assert fetched == [(REPO, SHA, "sub/dir/tool.py", "sub/dir/SKILL.md")]
    assert "created" in res[0].action
    assert "_plugin_start()" in m.state["remote"]["content"]


def test_git_fetcher_reads_files_at_an_exact_commit_and_rejects_a_missing_one(tmp_path):
    git(tmp_path, "init", "-q")
    (tmp_path / "t.py").write_text("v1\n")
    git(tmp_path, "add", ".")
    commit(tmp_path, "one")
    sha = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "t.py").write_text("v2\n")
    commit(tmp_path, "two")
    assert git_fetcher(f"file://{tmp_path}", sha, ["t.py"], "file")["t.py"] == "v1\n"
    with pytest.raises(OwppError, match="not found"):
        git_fetcher(f"file://{tmp_path}", sha, ["nope.py"], "file")
    # Not an allowed transport by default.
    with pytest.raises(OwppError, match="failed"):
        git_fetcher(f"file://{tmp_path}", sha, ["t.py"])


def test_fetch_sources_expands_a_directory_and_git_fetcher_lists_regular_files_only(tmp_path):
    git(tmp_path, "init", "-q")
    write_tree(
        tmp_path,
        {"s/SKILL.md": "# s\n", "s/refs/a.md": "a\n", "s/bin.dat": bytes([0xFF, 0x00, 0x80])},
    )
    (tmp_path / "s" / "link").symlink_to("/etc/passwd")
    git(tmp_path, "add", ".")
    commit(tmp_path, "one", flags=())
    sha = git(tmp_path, "rev-parse", "HEAD")

    def fetcher(g, r, ps):
        return git_fetcher(g, r, ps, "file")

    base = f"file://{tmp_path}#{sha}:"
    out = fetch_sources([f"{base}s/"], fetcher)
    assert sorted(k[len(base) + 2 :] for k in out) == ["SKILL.md", "bin.dat", "refs/a.md"]
    assert out[f"{base}s/SKILL.md"] == "# s\n"
    assert out[f"{base}s/bin.dat"] == {
        "base64": base64.b64encode(bytes([0xFF, 0x00, 0x80])).decode()
    }
    with pytest.raises(OwppError, match="no files under"):
        fetch_sources([f"{base}nope/"], fetcher)
