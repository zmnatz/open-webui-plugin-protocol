"""`owpp live` (owpp.live) and its fixtures, without Docker. Docker and HTTP are
stand-ins here; the live suite (`tools/screenshots/run.py --live`, and CI's `live` job) runs the
real stack through the same command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from owpp.cli import build_parser, main
from owpp.errors import OwppError
from owpp.live import command as live_command
from owpp.live.stack import COMPOSE, DEFAULT_FIXTURES, Stack


class Docker:
    """A stand-in for subprocess.run: records each command, and answers pytest's run."""

    def __init__(self, pytest_code: int = 0, missing: bool = False):
        self.commands: list[list[str]] = []
        self.envs: list[dict] = []
        self.pytest_code = pytest_code
        self.missing = missing

    def __call__(self, command, check=False, env=None, **_):
        if self.missing:
            raise FileNotFoundError("docker")
        self.commands.append(list(command))
        self.envs.append(dict(env or {}))
        code = self.pytest_code if "pytest" in command else 0
        return subprocess.CompletedProcess(command, code)

    def docker(self) -> list[list[str]]:
        return [c for c in self.commands if c[0] == "docker"]

    def actions(self) -> list[str]:
        return ["up" if "up" in c else "down" for c in self.docker()]

    def pytest(self) -> list[str] | None:
        return next((c for c in self.commands if "pytest" in c), None)


class OpenWebUI:
    """A stand-in for Open-WebUI's sign-up API: healthy at once, accounts on demand."""

    def __init__(self, signed_up: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.signed_up = signed_up

    def __call__(self, url, method, body=None, token=None):
        path = url.split("127.0.0.1:", 1)[1].partition("/")[2]
        self.calls.append((method, "/" + path))
        if path == "health":
            return {"status": True}
        if path == "api/v1/auths/signup":
            if self.signed_up:
                raise urllib.error.HTTPError(url, 400, "taken", {}, None)
            return {"token": "admin-token"}
        if path == "api/v1/auths/add":
            return {}
        if path == "api/v1/auths/signin":
            return {"token": f"{body['email'].split('@')[0]}-token"}
        raise AssertionError(f"unexpected call {method} {url}")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A plugins repository: plugins/ and live/, as the working directory."""
    (tmp_path / "plugins" / "shout").mkdir(parents=True)
    (tmp_path / "live").mkdir()
    (tmp_path / "live" / "test_it.py").write_text("def test_it():\n    pass\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def deploys(monkeypatch):
    """`owpp deploy`, recorded instead of run: each call's argv and environment."""
    calls: list[tuple[list[str], dict]] = []

    def deploy(argv, env):
        calls.append((list(argv), dict(env)))
        return 0

    monkeypatch.setattr(live_command, "owpp_main", deploy)
    return calls


def live(argv: list[str], env=None, docker=None, owui=None):
    """Run `owpp live <argv>` with the stand-ins, as main() would."""
    parser = build_parser()
    passthrough = argv[argv.index("--") + 1 :] if "--" in argv else []
    argv = argv[: argv.index("--")] if "--" in argv else argv
    args = parser.parse_args(["live", *argv])
    args.pytest_args = passthrough
    directory = Path(args.dir or "plugins").resolve()
    return live_command.run_command(
        args,
        directory,
        env or {},
        run=docker or Docker(),
        http=owui or OpenWebUI(),
        sleep=lambda s: None,
    )


# ---- the stack ------------------------------------------------------------------------------


def test_the_repositorys_compose_file_and_fixtures_are_found_beside_its_tests(repo):
    (repo / "live" / "compose.yaml").write_text("services: {}\n")
    (repo / "live" / "aimock").mkdir()
    stack = Stack.find(Path("live"))
    assert stack.compose == repo / "live" / "compose.yaml"
    assert stack.fixtures == repo / "live" / "aimock"


def test_without_them_it_is_owpps_stack_and_owpps_fixtures(repo):
    stack = Stack.find(Path("live"))
    command = stack.compose_command("up")
    assert command[command.index("-f") :] == ["-f", str(COMPOSE), "up"]
    assert stack.compose_env()["OWPP_LIVE_FIXTURES"] == str(DEFAULT_FIXTURES)


def test_the_repositorys_compose_file_is_layered_on_owpps_with_its_paths_relative_to_it(repo):
    """docker compose resolves every file's relative paths against the project directory, so it
    is the folder of the repository's file: `./nginx.conf` there means the file beside it."""
    (repo / "stack").mkdir()
    (repo / "stack" / "extra.yaml").write_text("services: {}\n")
    command = Stack.find(Path("live"), compose=Path("stack/extra.yaml")).compose_command("up")
    files = [command[i + 1] for i, part in enumerate(command) if part == "-f"]
    assert files == [str(COMPOSE), str(repo / "stack" / "extra.yaml")]
    assert command[command.index("--project-directory") + 1] == str(repo / "stack")
    assert command[command.index("-p") + 1] == "owpp-live"


def test_a_compose_file_or_fixtures_folder_given_but_not_there_is_refused(repo):
    with pytest.raises(OwppError, match="no compose file"):
        Stack.find(Path("live"), compose=Path("nope.yaml"))
    with pytest.raises(OwppError, match="no aimock fixtures folder"):
        Stack.find(Path("live"), fixtures=Path("nope"))


def test_the_ports_reach_the_compose_file_and_the_addresses(repo):
    stack = Stack.find(Path("live"), port=3100, aimock_port=4110)
    assert stack.compose_env()["OWPP_LIVE_PORT"] == "3100"
    assert stack.compose_env()["OWPP_LIVE_AIMOCK_PORT"] == "4110"
    assert (stack.url, stack.aimock_url) == ("http://127.0.0.1:3100", "http://127.0.0.1:4110")


def test_owpps_compose_file_uses_the_variables_owpp_live_sets():
    text = COMPOSE.read_text()
    for name in ("OWPP_LIVE_PORT", "OWPP_LIVE_AIMOCK_PORT", "OWPP_LIVE_FIXTURES"):
        assert "${" + name in text, name


# ---- owpp live --------------------------------------------------------------------------------


def test_it_starts_the_stack_deploys_runs_the_tests_and_stops_it(repo, deploys):
    """Up, sign up the admin and the user, `owpp deploy` with the admin's token, pytest on the
    tests folder with the accounts in its environment, then down."""
    docker, owui = Docker(), OpenWebUI()
    assert live([], docker=docker, owui=owui) == 0
    assert docker.actions() == ["up", "down"]
    assert [c for c in owui.calls if c[1] != "/health"] == [
        ("POST", "/api/v1/auths/signup"),
        ("POST", "/api/v1/auths/add"),
        ("POST", "/api/v1/auths/signin"),
    ]
    (argv, env), *_ = deploys
    assert argv == ["deploy", "--dir", str(repo / "plugins")]
    assert env["OPEN_WEBUI_URL"] == "http://127.0.0.1:3000"
    assert env["OPEN_WEBUI_API_KEY"] == "admin-token"
    command = docker.pytest()
    assert command[:4] == [sys.executable, "-m", "pytest", str(repo / "live")]
    tests_env = docker.envs[docker.commands.index(command)]
    assert json.loads(tests_env["OWPP_LIVE_ADMIN"])["token"] == "admin-token"
    assert json.loads(tests_env["OWPP_LIVE_USER"])["token"] == "bob-token"
    assert tests_env["OWPP_LIVE_URL"] == "http://127.0.0.1:3000"
    assert tests_env["OWPP_LIVE_FAILURES"] == str(repo / "live" / "failures")
    assert tests_env["PYTEST_PLUGINS"] == "owpp.live.fixtures"


def test_the_callers_own_pytest_plugins_still_load(repo, deploys):
    docker = Docker()
    live([], env={"PYTEST_PLUGINS": "mine"}, docker=docker)
    tests_env = docker.envs[docker.commands.index(docker.pytest())]
    assert tests_env["PYTEST_PLUGINS"] == "mine,owpp.live.fixtures"


def test_its_exit_code_is_the_tests_and_the_stack_stops_either_way(repo, deploys):
    docker = Docker(pytest_code=1)
    assert live([], docker=docker) == 1
    assert docker.actions() == ["up", "down"]


def test_arguments_after_two_dashes_go_to_pytest(repo, deploys):
    docker = Docker()
    live(["--", "-k", "chat", "-x"], docker=docker)
    assert docker.pytest()[-3:] == ["-k", "chat", "-x"]


def test_the_deploy_never_signs_in_with_the_callers_own_instance(repo, deploys):
    """Only the throwaway instance's address and token: a password or OIDC token in the
    environment, meant for a real instance, is not passed on."""
    env = {
        "OPEN_WEBUI_URL": "https://chat.example.com",
        "OPEN_WEBUI_API_KEY": "sk-real",
        "OPEN_WEBUI_USERNAME": "me@example.com",
        "OPEN_WEBUI_PASSWORD": "secret",
        "OPEN_WEBUI_OIDC_TOKEN": "oidc",
    }
    live([], env=env)
    (_, deploy_env), *_ = deploys
    assert {k: v for k, v in deploy_env.items() if k.startswith("OPEN_WEBUI_")} == {
        "OPEN_WEBUI_URL": "http://127.0.0.1:3000",
        "OPEN_WEBUI_API_KEY": "admin-token",
    }


def test_a_failed_deploy_stops_the_stack_and_runs_no_tests(repo, monkeypatch):
    monkeypatch.setattr(live_command, "owpp_main", lambda argv, env: 1)
    docker = Docker()
    with pytest.raises(OwppError, match="deploy"):
        live([], docker=docker)
    assert docker.actions() == ["up", "down"]
    assert docker.pytest() is None


def test_keep_leaves_it_running(repo, deploys, capsys):
    docker = Docker()
    live(["--keep"], docker=docker)
    assert docker.actions() == ["up"]
    assert "owpp live --down" in capsys.readouterr().out


def test_up_deploys_runs_no_tests_and_prints_how_to_reach_it(repo, deploys, capsys):
    docker = Docker()
    assert live(["--up"], docker=docker) == 0
    assert docker.actions() == ["up"]
    assert docker.pytest() is None
    out = capsys.readouterr().out
    assert "admin@example.com" in out
    assert "export OWPP_LIVE_ADMIN=" in out
    assert "export PYTEST_PLUGINS=owpp.live.fixtures" in out
    assert "OPEN_WEBUI_API_KEY=admin-token" in out


def test_up_again_signs_in_to_the_accounts_already_there(repo, deploys):
    owui = OpenWebUI(signed_up=True)
    live(["--up"], owui=owui)
    assert ("POST", "/api/v1/auths/signin") in owui.calls
    assert ("POST", "/api/v1/auths/add") not in owui.calls


def test_down_only_stops_it(repo, deploys):
    docker = Docker()
    assert live(["--down"], docker=docker) == 0
    assert docker.actions() == ["down"]
    assert not deploys


def test_no_tests_folder_is_refused_before_anything_starts(repo, deploys):
    docker = Docker()
    with pytest.raises(OwppError, match="no live tests"):
        live(["--tests", "elsewhere"], docker=docker)
    assert docker.commands == []


def test_no_docker_says_it_is_needed(repo, deploys):
    with pytest.raises(OwppError, match="needs Docker"):
        live([], docker=Docker(missing=True))


def test_up_down_and_keep_are_one_or_another():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["live", "--up", "--down"])


# ---- one of owpp's commands -------------------------------------------------------------------


def test_live_is_one_of_owpps_commands():
    live_parser = build_parser()._subparsers._group_actions[0].choices["live"]
    assert "--up" in live_parser._option_string_actions


def test_owpp_and_owpp_live_need_no_playwright_to_load():
    """Playwright comes with `owpp[live]`, for the browser fixtures alone: owpp, its CLI and
    `owpp live` itself load without it."""
    code = (
        "import sys; sys.modules['playwright'] = None\n"
        "import owpp.live, owpp.live.fixtures\n"
        "from owpp.cli import main\n"
        "main(['live', '--help'])"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--up" in result.stdout


def test_only_test_and_live_take_arguments_after_two_dashes(capsys):
    with pytest.raises(SystemExit):
        main(["check", "--", "-k", "x"], {})
    assert "only `owpp test` and `owpp live`" in capsys.readouterr().err


# ---- the fixtures --------------------------------------------------------------------------------


def run_pytest(folder: Path, **env) -> subprocess.CompletedProcess:
    (folder / "test_x.py").write_text("def test_x(api):\n    pass\n")
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("OWPP_LIVE_") and k != "PYTEST_PLUGINS"
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(folder)],
        capture_output=True,
        text=True,
        env=base | env,
        cwd=folder,
    )


def test_the_live_fixtures_are_not_in_every_pytest_run(tmp_path):
    """Installing owpp does not give every pytest run an `api` or a `user` fixture."""
    result = run_pytest(tmp_path)
    assert "fixture 'api' not found" in result.stdout, result.stdout + result.stderr


def test_a_live_fixture_outside_owpp_live_says_to_start_it(tmp_path):
    result = run_pytest(tmp_path, PYTEST_PLUGINS="owpp.live.fixtures")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "run `owpp live`" in result.stdout + result.stderr
