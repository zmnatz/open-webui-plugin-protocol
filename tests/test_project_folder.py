"""`.owpp/`: what owpp takes from git, kept beside the plugins folder (owpp.sources)."""

from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import FakeRepo, write_tree

from owpp.bundle import load_function_files
from owpp.cli import main
from owpp.deploy import build_plugins
from owpp.errors import OwppError
from owpp.pull import pull
from owpp.sources import Sources, _git, _project
from owpp.testing import pytest_plugin
from owpp.versioning import check_since

SHA = "a" * 40
NEW = "b" * 40
URL = "https://example.com/owner/repo.git"
UPSTREAM = {
    "up/plugin.yaml": "protocol: '0.7'\nfunction:\n  title: Whole\n  version: 1.0.0\n",
    "up/function.py": "class Filter:\n    pass\n",
    "up/tests/test_up.py": "def test_it():\n    assert True\n",
    "tool.py": "class Tools:\n    pass\n",
}
WHOLE = f"protocol: '0.7'\nsource: {{git: {URL}, ref: {SHA}, path: up, plugin: true}}\n"
TAKES = (
    f"protocol: '0.7'\nsource: {{git: {URL}, ref: {SHA}}}\n"
    "function: {title: T}\ntool: {id: t, file: tool.py}\n"
)


def repository(**commits):
    return FakeRepo(URL, commits={SHA: UPSTREAM, **commits}, head=SHA)


def unreachable(git, ref, paths):
    raise AssertionError(f"fetched {git} {paths}: .owpp/ holds that commit")


@pytest.fixture
def project(tmp_path):
    """A project with a plugin taken whole from git and one that takes its tool from git."""
    write_tree(
        tmp_path / "project" / "plugins",
        {
            "whole/plugin.yaml": WHOLE,
            "takes/plugin.yaml": TAKES,
            "takes/function.py": "class Filter:\n    pass\n",
        },
    )
    return tmp_path / "project"


def load(project, fetcher):
    plugins = project / "plugins"
    with Sources(fetcher, plugins=plugins) as sources:
        return {f.id: f for f in load_function_files(plugins, sources)}


def snapshot(folder):
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


class TestTheStore:
    def test_a_commit_is_fetched_once_and_then_read_from_the_project(self, project):
        repo = repository()
        first = load(project, repo.fetch)
        assert repo.fetched
        again = load(project, unreachable)
        assert {i: f.content for i, f in again.items()} == {i: f.content for i, f in first.items()}

    def test_it_holds_the_upstream_files_untouched(self, project):
        load(project, repository().fetch)
        (commit,) = (project / ".owpp" / "store").glob(f"*/{SHA}")
        assert (commit / "tree" / "up" / "plugin.yaml").read_text() == UPSTREAM["up/plugin.yaml"]
        assert (commit / "tree" / "tool.py").read_text() == UPSTREAM["tool.py"]

    def test_binary_files_come_back_as_they_were(self, project):
        files = {SHA: {**UPSTREAM, "up/static/x.bin": {"base64": "/wD+"}}}
        repo = FakeRepo(URL, commits=files)
        first = load(project, repo.fetch)["whole"].content
        assert load(project, unreachable)["whole"].content == first

    @pytest.mark.parametrize("change", ["edit", "delete"])
    def test_a_changed_file_is_refused(self, project, change):
        load(project, repository().fetch)
        (file,) = (project / ".owpp" / "store").glob(f"*/{SHA}/tree/tool.py")
        if change == "edit":
            file.write_text("import os  # added\n")
        else:
            file.unlink()
        with pytest.raises(OwppError, match=r"tool\.py is not as owpp wrote it.*Delete"):
            load(project, unreachable)

    def test_a_path_that_leaves_the_folder_is_refused(self, project):
        def escaping(git, ref, paths):
            return {f"{p}../../escaped" if p.endswith("/") else p: "x" for p in paths}

        with pytest.raises(OwppError, match="not a plain path"):
            load(project, escaping)
        assert not list(project.parent.rglob("escaped"))

    def read(self, project, fetcher, *entries):
        with Sources(fetcher, plugins=project / "plugins") as sources:
            return sources.fetcher(URL, SHA, list(entries))

    def test_a_changed_file_is_not_replaced_by_a_later_fetch_of_it(self, project):
        repo = repository()
        self.read(project, repo.fetch, "tool.py")
        (file,) = (project / ".owpp" / "store").glob(f"*/{SHA}/tree/tool.py")
        file.write_text("import os  # added\n")
        with pytest.raises(OwppError, match="is not as owpp wrote it"):
            self.read(project, repo.fetch, "./")
        assert file.read_text() == "import os  # added\n"

    def test_paths_that_differ_only_in_case_both_come_back(self, project):
        repo = FakeRepo(URL, {"d/Notes.md": "upper\n", "d/notes.md": "lower\n"})
        for _ in range(2):
            assert self.read(project, repo.fetch, "d/Notes.md") == {"d/Notes.md": "upper\n"}
            assert self.read(project, repo.fetch, "d/notes.md") == {"d/notes.md": "lower\n"}

    @pytest.mark.skipif(os.sep == "\\", reason="a backslash separates folders on Windows")
    def test_a_name_with_a_backslash_is_a_name(self, project):
        repo = FakeRepo(URL, {"d/a\\b.md": "x\n"})
        for _ in range(2):
            assert self.read(project, repo.fetch, "d/") == {"d/a\\b.md": "x\n"}

    def test_a_folder_import_looks_at_is_kept_too(self, project):
        with Sources(repository().fetch, plugins=project / "plugins") as sources:
            first = sources.files(URL, SHA, "up")
        with Sources(unreachable, plugins=project / "plugins") as sources:
            assert sources.files(URL, SHA, "up") == first

    def test_deleting_the_folder_is_safe(self, project):
        repo = repository()
        first = load(project, repo.fetch)["whole"].content
        shutil.rmtree(project / ".owpp")
        assert load(project, repo.fetch)["whole"].content == first

    def test_deleting_one_commit_fetches_it_again(self, project):
        repo = repository()
        load(project, repo.fetch)
        shutil.rmtree(next((project / ".owpp" / "store").iterdir()))
        before = len(repo.fetched)
        load(project, repo.fetch)
        assert len(repo.fetched) > before

    def test_a_sources_without_a_plugins_folder_writes_nothing(self, project):
        with Sources(repository().fetch) as sources:
            load_function_files(project / "plugins", sources)
        assert not (project / ".owpp").exists()

    def test_a_folder_with_nothing_from_git_gets_none(self, tmp_path):
        write_tree(tmp_path / "plugins", {"a/plugin.yaml": "function: {title: A}\n"})
        write_tree(tmp_path / "plugins", {"a/function.py": "class Filter:\n    pass\n"})
        load(tmp_path, unreachable)
        assert not (tmp_path / ".owpp").exists()

    def test_it_stays_inside_a_plugins_folder_that_is_a_repository(self, tmp_path):
        write_tree(tmp_path / "repo", {"whole/plugin.yaml": WHOLE, ".git/HEAD": "x\n"})
        with Sources(repository().fetch, plugins=tmp_path / "repo") as sources:
            load_function_files(tmp_path / "repo", sources)
        assert (tmp_path / "repo" / ".owpp" / "modules" / "whole").is_dir()
        assert not (tmp_path / ".owpp").exists()

    def test_a_project_that_cannot_be_written_still_loads(self, project, capsys):
        (project / ".owpp").write_text("a file where the folder would go\n")
        assert set(load(project, repository().fetch)) == {"takes", "whole"}
        assert capsys.readouterr().err.count("nothing from git is kept") == 1


class TestModules:
    def test_a_whole_plugin_is_written_there_and_stays(self, project):
        root = load(project, repository().fetch)["whole"].root
        assert root == project / ".owpp" / "modules" / "whole"
        assert (root / "function.py").read_text() == UPSTREAM["up/function.py"]

    def test_it_is_written_again_when_the_local_files_change(self, project):
        load(project, repository().fetch)
        module = project / ".owpp" / "modules" / "whole"
        local = project / "plugins" / "whole"
        (local / "plugin.yaml").write_text(WHOLE + "function: {global: false}\n")
        load(project, unreachable)
        assert "global: false" in (module / "plugin.yaml").read_text()
        (local / "config.yaml").write_text("greeting: mine\n")
        load(project, unreachable)
        assert (module / "config.yaml").read_text() == "greeting: mine\n"
        (local / "config.yaml").unlink()
        load(project, unreachable)
        assert not (module / "config.yaml").exists()

    def test_it_is_written_again_when_the_pin_moves(self, project):
        newer = {**UPSTREAM, "up/function.py": "class Filter:\n    x = 2\n"}
        repo = repository(**{NEW: newer})
        load(project, repo.fetch)
        (project / "plugins" / "whole" / "plugin.yaml").write_text(WHOLE.replace(SHA, NEW))
        load(project, repo.fetch)
        module = project / ".owpp" / "modules" / "whole"
        assert (module / "function.py").read_text() == newer["up/function.py"]

    @pytest.mark.parametrize(
        ("path", "content"),
        [
            ("function.py", "import os\n"),  # edited
            ("static/added.js", "alert(1)\n"),  # added
            ("templates/", ""),  # an added folder would turn a library on
        ],
    )
    def test_a_changed_module_is_refused(self, project, path, content):
        load(project, repository().fetch)
        target = project / ".owpp" / "modules" / "whole" / path
        if path.endswith("/"):
            target.mkdir()
        else:
            target.parent.mkdir(exist_ok=True)
            target.write_text(content)
        with pytest.raises(OwppError, match="is not as owpp wrote it.*Delete .*modules/whole"):
            load(project, unreachable)

    def test_a_changed_module_is_refused_even_when_the_pin_moves(self, project):
        repo = repository(**{NEW: UPSTREAM})
        load(project, repo.fetch)
        (project / ".owpp" / "modules" / "whole" / "function.py").write_text("import os\n")
        (project / "plugins" / "whole" / "plugin.yaml").write_text(WHOLE.replace(SHA, NEW))
        with pytest.raises(OwppError, match="is not as owpp wrote it"):
            load(project, repo.fetch)

    def test_what_python_and_a_file_browser_leave_is_not_a_change(self, project):
        load(project, repository().fetch)
        module = project / ".owpp" / "modules" / "whole"
        write_tree(module, {"__pycache__/f.pyc": b"x", ".DS_Store": b"x"})
        load(project, unreachable)
        assert not (module / "__pycache__").exists()

    def test_a_cache_folder_of_the_upstream_stays(self, project):
        files = {**UPSTREAM, "up/notes/__pycache__/kept.txt": "upstream\n"}
        repo = FakeRepo(URL, files)
        load(project, repo.fetch)
        kept = project / ".owpp" / "modules" / "whole" / "notes" / "__pycache__"
        assert (kept / "kept.txt").read_text() == "upstream\n"
        write_tree(kept, {"added.pyc": b"x"})
        load(project, unreachable)
        assert sorted(p.name for p in kept.iterdir()) == ["kept.txt"]

    def test_many_at_once_all_get_it(self, project):
        repo = repository()
        with ThreadPoolExecutor(8) as pool:
            done = list(pool.map(lambda _: load(project, repo.fetch)["whole"].content, range(24)))
        assert len(set(done)) == 1

    def test_a_build_at_the_latest_commits_leaves_it_alone(self, project):
        newer = {**UPSTREAM, "up/function.py": "class Filter:\n    x = 2\n"}
        repo = FakeRepo(URL, commits={SHA: UPSTREAM, NEW: newer}, head=NEW)
        load(project, repo.fetch)
        before = snapshot(project / ".owpp" / "modules")
        plugins = project / "plugins"
        with Sources(repo.fetch, repo.lookup, plugins=plugins) as sources:
            made = build_plugins(plugins, sources, latest=True)
        assert "x = 2" in {f.id: f.content for f in made.files}["whole"]
        assert {f.root for f in made.files} == {None}
        assert snapshot(project / ".owpp" / "modules") == before

    def test_a_pull_dry_run_keeps_the_pinned_one(self, project, capsys):
        newer = {**UPSTREAM, "up/function.py": "class Filter:\n    x = 2\n"}
        repo = FakeRepo(URL, commits={SHA: UPSTREAM, NEW: newer}, head=NEW)
        plugins = project / "plugins"
        with Sources(repo.fetch, repo.lookup, repo.kind, plugins=plugins) as sources:
            assert pull(plugins, dry_run=True, sources=sources) == 0
        module = project / ".owpp" / "modules" / "whole"
        assert (module / "function.py").read_text() == UPSTREAM["up/function.py"]

    def test_check_since_leaves_it_alone(self, project):
        newer = {**UPSTREAM, "up/function.py": "class Filter:\n    x = 2\n"}
        repo = repository(**{NEW: newer})
        git(project, "init", "-q", "-b", "main")
        (project / ".gitignore").write_text(".owpp/\n")
        git(project, "add", "-A")
        git(project, "commit", "-qm", "first")
        plugins = project / "plugins"
        (plugins / "whole" / "plugin.yaml").write_text(WHOLE.replace(SHA, NEW))
        with Sources(repo.fetch, plugins=plugins) as sources:
            check_since(plugins, "main", sources=sources)
        module = project / ".owpp" / "modules" / "whole"
        assert (module / "function.py").read_text() == newer["up/function.py"]


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


class TestGit:
    NOTE = "add `.owpp/` to your .gitignore"

    def test_it_suggests_ignoring_the_folder_once_and_edits_nothing(self, project, capsys):
        git(project, "init", "-q")
        load(project, repository().fetch)
        assert capsys.readouterr().err.count(self.NOTE) == 1
        load(project, unreachable)
        assert self.NOTE not in capsys.readouterr().err
        assert not (project / ".gitignore").exists()

    def test_an_ignored_folder_needs_no_note(self, project, capsys):
        git(project, "init", "-q")
        (project / ".gitignore").write_text(".owpp/\n")
        load(project, repository().fetch)
        assert self.NOTE not in capsys.readouterr().err

    def test_outside_a_git_repository_there_is_no_note(self, project, capsys):
        load(project, repository().fetch)
        assert self.NOTE not in capsys.readouterr().err

    def test_a_folder_that_git_tracks_is_refused(self, project):
        """A committed .owpp/ could change what is bundled with no change to a pin."""
        git(project, "init", "-q")
        load(project, repository().fetch)
        git(project, "add", "-f", ".owpp")
        with pytest.raises(OwppError, match="git tracks files in .*\\.owpp"):
            load(project, unreachable)

    def test_a_folder_that_git_tracks_in_another_case_is_refused(self, project):
        """A file system that ignores case opens a committed .OWPP/ as .owpp/."""
        git(project, "init", "-q")
        load(project, repository().fetch)
        (project / "x").write_text("x\n")
        blob = subprocess.run(
            ["git", "hash-object", "-w", "x"], cwd=project, check=True, capture_output=True
        ).stdout.decode()
        git(project, "update-index", "--add", "--cacheinfo", f"100644,{blob.strip()},.OWPP/x")
        with pytest.raises(OwppError, match="git tracks files in"):
            load(project, unreachable)

    def test_a_folder_git_cannot_vouch_for_is_not_used(self, project, monkeypatch, capsys):
        """As in a container where git refuses a repository of another owner."""
        git(project, "init", "-q")
        load(project, repository().fetch)
        capsys.readouterr()
        before = snapshot(project / ".owpp")
        monkeypatch.setattr(
            _project, "_git", lambda *a: subprocess.CompletedProcess(a, 128, b"", b"dubious")
        )
        repo = repository()
        assert load(project, repo.fetch)["whole"].root is None
        assert repo.fetched
        assert snapshot(project / ".owpp") == before
        assert capsys.readouterr().err.count("is not used") == 1


class TestCommands:
    def test_a_command_keeps_what_it_fetches_and_the_next_needs_no_git(
        self, project, monkeypatch, capsys
    ):
        argv = ["check", "--dir", str(project / "plugins")]
        monkeypatch.setattr(_git, "git_fetcher", repository().fetch)
        assert main(argv, env={}) == 0
        monkeypatch.setattr(_git, "git_fetcher", unreachable)
        assert main(argv, env={}) == 0

    def test_upstream_tests_run_in_a_scratch_copy_that_reads_the_store(
        self, project, monkeypatch, capsys
    ):
        """Third-party tests do not write into the folder that is bundled."""
        ran = {}

        def run(args, **kwargs):
            ran["args"] = args
            ran["variable"] = os.environ.get("OWPP_PLUGINS_DIR")
            return 0

        monkeypatch.setattr(pytest, "main", run)
        monkeypatch.delenv("OWPP_PLUGINS_DIR", raising=False)
        monkeypatch.setattr(_git, "git_fetcher", repository().fetch)
        argv = ["test", "--upstream", "--dir", str(project / "plugins")]
        assert main(argv, env={}) == 0
        (tests,) = [p for p in ran["args"] if p.endswith("tests")]
        assert ".owpp" not in tests
        assert f"owpp_plugins_dir={(project / 'plugins').resolve()}" in ran["args"]
        assert ran["variable"] is None  # what a test itself runs is left as it was


class TestWhereTheTestFixturesKeepIt:
    @pytest.fixture(autouse=True)
    def unset(self, monkeypatch):
        monkeypatch.delenv("OWPP_PLUGINS_DIR", raising=False)

    def test_beside_the_plugins_folder_of_the_test(self, project):
        test = project / "plugins" / "takes" / "tests" / "test_takes.py"
        assert pytest_plugin.plugins_folder(test) == (project / "plugins").resolve()

    def test_or_the_one_owpp_test_passes(self, project, monkeypatch):
        monkeypatch.setenv("OWPP_PLUGINS_DIR", str(project))
        test = project / "elsewhere" / "test_x.py"
        passed = str(project / "plugins")
        assert pytest_plugin.plugins_folder(test, passed) == (project / "plugins").resolve()

    def test_or_the_folder_the_variable_names(self, project, monkeypatch):
        monkeypatch.setenv("OWPP_PLUGINS_DIR", str(project / "plugins"))
        test = project / "elsewhere" / "test_x.py"
        assert pytest_plugin.plugins_folder(test) == (project / "plugins").resolve()

    def test_nowhere_for_a_test_outside_a_plugin(self, tmp_path):
        assert pytest_plugin.plugins_folder(tmp_path / "test_x.py") is None

    def test_nowhere_for_a_plugin_that_is_the_whole_repository(self, tmp_path):
        write_tree(tmp_path / "repo", {"plugin.yaml": WHOLE, ".git/HEAD": "x\n"})
        assert pytest_plugin.plugins_folder(tmp_path / "repo" / "tests" / "t.py") is None
