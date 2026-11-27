"""Plugin files taken from a git repo, pinned to a commit, read through Sources."""

from __future__ import annotations

import base64
import subprocess

import pytest
from conftest import embedded, fake_sources, write_tree

from owpp.bundle import bundle_function, load_function_files
from owpp.deploy import deploy
from owpp.errors import OwppError
from owpp.sources import Sources
from owpp.sources._git import git_fetcher, kind_in, pick_sha

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


def repo(files: dict, calls: list | None = None):
    """A fetcher over {path in the repo: content}, recording each call."""

    def fetcher(git, ref, paths):
        if calls is not None:
            calls.append((git, ref, list(paths)))
        out = {}
        for p in paths:
            if p.endswith("/"):
                out |= {k: v for k, v in files.items() if k.startswith(p)}
            elif p in files:
                out[p] = files[p]
        return out

    return fetcher


@pytest.fixture
def plugin(tmp_path):
    def make(manifest: str, name: str = "remote"):
        write_tree(tmp_path / name, {"plugin.yaml": manifest})
        return tmp_path / name

    return make


def git(repo_dir, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo_dir, message="c", flags=("-a",)):
    git(
        repo_dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", *flags, "-m", message
    )


class TestResolve:
    def test_fetches_what_the_manifest_names_in_one_call_at_the_pinned_commit(self, plugin):
        calls = []
        files = {"sub/dir/tool.py": "class Tools: ...\n", "sub/dir/SKILL.md": "# s\n"}
        resolved = Sources(repo(files, calls)).resolve(plugin(MANIFEST))
        assert calls == [(REPO, SHA, ["sub/dir/tool.py", "sub/dir/SKILL.md"])]
        assert resolved.read("tool.py") == "class Tools: ...\n"
        assert resolved.taken == files  # by path in the repo
        assert resolved.pins == {f"{REPO} sub/dir": SHA}
        assert resolved.root == resolved.folder

    def test_each_file_is_fetched_once_per_sources(self, plugin):
        calls = []
        sources = Sources(repo({"sub/dir/tool.py": "t\n", "sub/dir/SKILL.md": "s\n"}, calls))
        sources.resolve(plugin(MANIFEST))
        sources.resolve(plugin(MANIFEST, "again"))
        assert len(calls) == 1

    def test_a_local_plugin_reads_its_folder_and_fetches_nothing(self, plugin):
        folder = plugin("function: {title: T}\n")
        write_tree(folder, {"x.txt": "here\n", "d/a.md": "a\n"})
        resolved = Sources(repo({}, calls := [])).resolve(folder)
        assert resolved.read("x.txt") == "here\n"
        assert [f["path"] for f in resolved.read_dir("d")] == ["a.md"]
        assert resolved.pins == {} and resolved.taken == {} and calls == []

    def test_a_ref_resolves_at_another_commit(self, plugin):
        calls = []
        other = "f" * 40
        resolved = Sources(repo({}, calls)).resolve(
            plugin(f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{title: T}}\n"),
            ref=other,
        )
        assert resolved.pins == {f"{REPO} x": other} and calls == []  # nothing it takes

    def test_reads_a_whole_skill_folder_with_binary_files(self, plugin):
        d = plugin(
            f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{title: T}}\n"
            "skills:\n  s: {dir: skills/s, access: public}\n"
        )
        files = {
            "x/skills/s/SKILL.md": "---\nname: S\n---\nbody\n",
            "x/skills/s/references/r.md": "r\n",
            "x/skills/s/img.png": {"base64": "AAEC"},
        }
        (fn,) = load_function_files(d.parent, Sources(repo(files)))
        (skill,) = embedded(fn.content)["skills"]
        assert skill["access"] == "public"
        assert [f["path"] for f in skill["files"]] == ["SKILL.md", "img.png", "references/r.md"]
        assert skill["files"][1]["encoding"] == "base64"

    @pytest.mark.parametrize(
        ("files", "message"),
        [
            ({"sub/dir/SKILL.md": "s\n"}, "sub/dir/tool.py not found"),
            ({"sub/dir/tool.py": "x" * 2_000_001, "sub/dir/SKILL.md": "s\n"}, "larger than"),
        ],
    )
    def test_a_missing_or_oversized_file_is_refused(self, plugin, files, message):
        with pytest.raises(OwppError, match=message):
            Sources(repo(files)).resolve(plugin(MANIFEST))

    def test_an_empty_or_huge_skill_folder_is_refused(self, plugin):
        d = plugin(
            f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{title: T}}\n"
            "skills:\n  s: {dir: s}\n"
        )
        with pytest.raises(OwppError, match="no files under x/s/"):
            Sources(repo({})).resolve(d)
        many = {f"x/s/{i}.md": "" for i in range(1001)}
        with pytest.raises(OwppError, match="more than 1000 files"):
            Sources(repo(many)).resolve(d)

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            ({"ref": "main"}, "40-character commit SHA"),
            ({"ref": ""}, r"has no `ref:`; run `owpp pull remote`"),
            ({"path": "../../etc"}, r"\.\."),
            ({"track": "--upload-pack=x"}, "track must be a branch or tag"),
            *[
                ({"git": bad}, "git URL")
                for bad in (
                    "no-slash",
                    "/etc/repo",
                    "ext::sh -c id",
                    "file:///tmp/r",
                    "--upload-pack=x",
                    "https://h/r #x",
                )
            ],
        ],
    )
    def test_refuses_an_unpinned_ref_a_bad_url_and_paths_that_climb_out(
        self, plugin, source, message
    ):
        src = {"git": REPO, "ref": SHA, "path": "x", **source}
        flow = ", ".join(f'{k}: "{v}"' for k, v in src.items() if v)
        d = plugin(f"source: {{{flow}}}\ntool: {{id: t, file: tool.py}}\nfunction: {{title: T}}\n")
        with pytest.raises(OwppError, match=message):
            Sources(repo({})).resolve(d)

    @pytest.mark.parametrize(
        "ok", ["https://h/o/r.git", "ssh://git@h/o/r.git", "git@h.example:o/r.git"]
    )
    def test_accepts_https_ssh_and_scp_style_urls(self, plugin, ok):
        d = plugin(f"source: {{git: '{ok}', ref: {SHA}, path: x}}\ntool: {{id: t, file: t.py}}\n")
        assert Sources(repo({"x/t.py": "t\n"})).resolve(d).read("t.py") == "t\n"

    def test_reading_a_file_the_source_does_not_take_is_refused(self, plugin):
        resolved = Sources(repo({"sub/dir/tool.py": "t\n", "sub/dir/SKILL.md": "s\n"})).resolve(
            plugin(MANIFEST)
        )
        with pytest.raises(OwppError, match="not one of the files its source takes"):
            resolved.read("other.py")

    def test_a_closed_sources_resolves_nothing(self, plugin):
        with Sources(repo({})) as sources:
            pass
        with pytest.raises(OwppError, match="closed"):
            sources.resolve(plugin("function: {title: T}\n"))


class TestBundling:
    def test_embeds_the_fetched_tool_and_skill(self, plugin):
        files = {
            "sub/dir/tool.py": '"""\ntitle: Up\n"""\nclass Tools:\n    pass\n',
            "sub/dir/SKILL.md": "---\nname: visualize\ndescription: d\n---\nbody\n",
        }
        (fn,) = load_function_files(plugin(MANIFEST).parent, Sources(repo(files)))
        data = embedded(fn.content)
        assert "title: Up" in data["tools"][0]["content"]
        assert data["tools"][0]["id"] == "remote_tool"
        assert [(s["id"], s["name"], [f["path"] for f in s["files"]]) for s in data["skills"]] == [
            ("visualize", "visualize", ["SKILL.md"])
        ]
        assert fn.sources == {f"{REPO} sub/dir": SHA}

    def test_takes_the_function_from_the_source_verbatim_with_global_from_the_manifest(
        self, plugin
    ):
        d = plugin(
            f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{file: event.py, global: true}}\n"
        )
        code = '"""\ntitle: Up\n"""\nclass Filter:\n    pass\n'
        (fn,) = load_function_files(d.parent, Sources(repo({"x/event.py": code})))
        assert fn.content == code
        assert fn.want_global is True
        assert fn.name == "Up"

    def test_refuses_function_file_without_a_source_or_with_extra_header_keys(self, plugin):
        with pytest.raises(OwppError, match="needs a `source:`"):
            load_function_files(plugin("function: {file: event.py}\n").parent)
        d = plugin(
            f"source: {{git: {REPO}, ref: {SHA}, path: x}}\nfunction: {{file: event.py, title: T}}\n",
            "other",
        )
        with pytest.raises(OwppError, match="remove title"):
            bundle_function(fake_sources().resolve(d))

    def test_a_path_with_a_source_needs_a_sources(self, plugin):
        with pytest.raises(OwppError, match="needs a Sources"):
            bundle_function(plugin(MANIFEST))
        with pytest.raises(OwppError, match="needs a Sources"):
            load_function_files(plugin(MANIFEST).parent)

    def test_deploy_fetches_the_sources_and_creates_the_function_with_them_embedded(
        self, plugin, open_webui
    ):
        m = open_webui()
        fetched = []

        def fetcher(git_url, ref, paths):
            fetched.append((git_url, ref, *paths))
            return {
                p: "---\nname: visualize\n---\nx\n"
                if p.endswith("SKILL.md")
                else "class Tools:\n    pass\n"
                for p in paths
            }

        res = deploy(*m.options(plugin(MANIFEST).parent, sources=Sources(fetcher)))
        assert fetched == [(REPO, SHA, "sub/dir/tool.py", "sub/dir/SKILL.md")]
        assert "created" in res[0].action
        assert "_plugin_start()" in m.state["remote"]["content"]


class TestRefs:
    """What a branch or tag names, read from `git ls-remote`."""

    def test_a_branch_or_a_tag_is_looked_up_exactly_and_told_apart(self):
        out = f"{'a' * 40}\trefs/heads/v1\n{'b' * 40}\trefs/tags/v1\n{'c' * 40}\trefs/tags/v1^{{}}"
        assert pick_sha(out, "refs/heads/v1") == "a" * 40
        assert pick_sha(out, "refs/tags/v1") == "c" * 40  # the commit an annotated tag points at
        assert pick_sha(out, "refs/heads/nope") is None
        assert kind_in(out, "v1") == "tag"  # both: the tag, as git reads the name
        assert kind_in(f"{'a' * 40}\trefs/heads/main\n", "main") == "branch"
        assert kind_in("", "main") is None

    def test_ls_remote_output_is_read_as_git_does(self):
        out = "\n".join(
            [
                f"{'a' * 40}\tHEAD",
                f"{'b' * 40}\trefs/heads/main",
                f"{'c' * 40}\trefs/tags/v1",
                f"{'d' * 40}\trefs/tags/v1^{{}}",  # the commit an annotated tag points at
                f"{'e' * 40}\trefs/heads/v1",
                f"{'f' * 40}\trefs/remotes/x/main",
            ]
        )
        assert pick_sha(out, "HEAD") == "a" * 40
        assert pick_sha(out, "main") == "b" * 40
        assert pick_sha(out, "v1") == "d" * 40  # the peeled tag, over the branch
        assert pick_sha(out, "other") is None

    @pytest.mark.parametrize(
        ("listed", "kind"),
        [
            (["refs/heads/v1"], "branch"),
            (["refs/tags/v1"], "tag"),
            (["refs/heads/v1", "refs/tags/v1"], "tag"),
            ([], None),
        ],
    )
    def test_sources_says_whether_a_name_is_a_branch_or_a_tag(self, monkeypatch, listed, kind):
        asked = []

        def ls_remote(args, **kwargs):
            asked.append(args)
            out = "".join(f"{SHA}\t{name}\n" for name in listed)
            return subprocess.CompletedProcess(args, 0, out, "")

        monkeypatch.setattr(subprocess, "run", ls_remote)
        with Sources() as sources:
            assert sources.kind(REPO, "v1") == kind
        assert asked[0][-2:] == ["refs/heads/v1", "refs/tags/v1"]

    def test_sources_reads_a_folder_at_a_commit_by_path_inside_it(self):
        files = {"viz/tool.py": "t\n", "viz/a/b.md": "b\n", "other.py": "o\n"}
        calls: list = []
        sources = Sources(repo(files, calls))
        assert sources.files(REPO, SHA, "viz") == {"tool.py": "t\n", "a/b.md": "b\n"}
        assert calls == [(REPO, SHA, ["viz/"])]


class TestGitFetcher:
    """The git transport, at its own seam: real git, on a local repository."""

    def test_reads_files_at_an_exact_commit_and_rejects_a_missing_one(self, tmp_path):
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

    def test_a_directory_lists_regular_files_only_and_keeps_binary_ones(self, tmp_path):
        git(tmp_path, "init", "-q")
        write_tree(
            tmp_path,
            {"s/SKILL.md": "# s\n", "s/refs/a.md": "a\n", "s/bin.dat": bytes([0xFF, 0x00, 0x80])},
        )
        (tmp_path / "s" / "link").symlink_to("/etc/passwd")
        git(tmp_path, "add", ".")
        commit(tmp_path, "one", flags=())
        sha = git(tmp_path, "rev-parse", "HEAD")
        out = git_fetcher(f"file://{tmp_path}", sha, ["s/"], "file")
        assert sorted(out) == ["s/SKILL.md", "s/bin.dat", "s/refs/a.md"]
        assert out["s/SKILL.md"] == "# s\n"
        assert out["s/bin.dat"] == {"base64": base64.b64encode(bytes([0xFF, 0x00, 0x80])).decode()}
