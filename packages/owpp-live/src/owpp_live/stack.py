"""The stack `owpp live` runs: owpp's compose file (Open-WebUI and aimock), with the repository's
own compose file layered on top, its aimock fixtures, and two throwaway accounts.

Docker and HTTP go through the `run` and `http` callables a `Stack` is given, so the command can
be tested without either.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from owpp.errors import OwppError

HERE = Path(__file__).resolve().parent
COMPOSE = HERE / "compose.yaml"
DEFAULT_FIXTURES = HERE / "aimock"
PROJECT = "owpp-live"

# Throwaway accounts on a throwaway instance; never reused anywhere.
ADMIN = {"name": "Ada Admin", "email": "admin@example.com", "password": "owpp-live-admin"}
USER = {
    "name": "Bob User",
    "email": "bob@example.com",
    "password": "owpp-live-user",
    "role": "user",
}

Run = Callable[..., subprocess.CompletedProcess]
Http = Callable[[str, str, "dict | None", "str | None"], object]


def http(url: str, method: str, body: dict | None = None, token: str | None = None):
    """One JSON request; raises urllib's errors."""
    request = urllib.request.Request(
        url,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


@dataclass
class Stack:
    """Where the stack's pieces come from, and how to reach it once it is up."""

    tests: Path
    compose: Path | None = None
    fixtures: Path | None = None
    port: int = 3000
    aimock_port: int = 4010
    run: Run = subprocess.run
    http: Http = http
    sleep: Callable[[float], None] = time.sleep
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def find(
        cls,
        tests: Path,
        compose: Path | None = None,
        fixtures: Path | None = None,
        **options,
    ) -> Stack:
        """The repository's compose file and fixtures: those given, else `compose.yaml` and
        `aimock/` in the tests folder when they are there."""
        tests = tests.resolve()
        if compose is None and (tests / "compose.yaml").is_file():
            compose = tests / "compose.yaml"
        if fixtures is None and (tests / "aimock").is_dir():
            fixtures = tests / "aimock"
        for what, path, check in (
            ("compose file", compose, Path.is_file),
            ("aimock fixtures folder", fixtures, Path.is_dir),
        ):
            if path is not None and not check(path):
                raise OwppError(f"no {what} at {path}")
        return cls(
            tests,
            compose.resolve() if compose else None,
            fixtures.resolve() if fixtures else None,
            **options,
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def aimock_url(self) -> str:
        return f"http://127.0.0.1:{self.aimock_port}"

    def compose_command(self, *args: str) -> list[str]:
        """`docker compose` with owpp's file, then the repository's. Paths in the repository's
        file are relative to its own folder (the project directory)."""
        files = ["-f", str(COMPOSE)] + (["-f", str(self.compose)] if self.compose else [])
        project_dir = self.compose.parent if self.compose else self.tests
        return [
            "docker",
            "compose",
            "-p",
            PROJECT,
            "--project-directory",
            str(project_dir),
            *files,
            *args,
        ]

    def compose_env(self) -> dict[str, str]:
        return dict(self.env) | {
            "OWPP_LIVE_PORT": str(self.port),
            "OWPP_LIVE_AIMOCK_PORT": str(self.aimock_port),
            "OWPP_LIVE_FIXTURES": str(self.fixtures or DEFAULT_FIXTURES),
        }

    def _docker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        try:
            return self.run(self.compose_command(*args), check=check, env=self.compose_env())
        except FileNotFoundError as error:
            raise OwppError("owpp live needs Docker, with its compose plugin, on PATH") from error
        except subprocess.CalledProcessError as error:
            raise OwppError(
                f"`docker compose {' '.join(args)}` failed (exit {error.returncode}): is Docker "
                "running, and can your user reach it?"
            ) from error

    def up(self) -> None:
        self._docker("up", "-d", "--wait")

    def down(self) -> None:
        self._docker("down", "--volumes", check=False)

    def api(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        return self.http(self.url + path, method, body, token)

    def wait_for_health(self, seconds: float = 600) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                answer = self.api("GET", "/health")
                if isinstance(answer, dict) and answer.get("status"):
                    return
            except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
                pass
            self.sleep(2)
        raise OwppError(f"Open-WebUI did not answer {self.url}/health within {seconds:.0f}s")

    def accounts(self) -> tuple[dict, dict]:
        """The admin and the user, each with its token. Signs them up on a fresh instance, and
        signs in when they are already there (a stack left running with --up)."""
        try:
            admin = self.api("POST", "/api/v1/auths/signup", ADMIN)["token"]
            self.api("POST", "/api/v1/auths/add", USER, admin)
        except urllib.error.HTTPError:
            admin = self.api("POST", "/api/v1/auths/signin", ADMIN)["token"]
        user = self.api("POST", "/api/v1/auths/signin", USER)["token"]
        return {**ADMIN, "token": admin}, {**USER, "token": user}

    def test_env(self, admin: dict, user: dict, failures: Path) -> dict[str, str]:
        """What the live tests read, through owpp-live's pytest plugin."""
        return {
            "OWPP_LIVE_URL": self.url,
            "OWPP_LIVE_AIMOCK_URL": self.aimock_url,
            "OWPP_LIVE_ADMIN": json.dumps(admin),
            "OWPP_LIVE_USER": json.dumps(user),
            "OWPP_LIVE_FAILURES": str(failures),
        }


def shell_exports(env: Mapping[str, str], names: Sequence[str]) -> str:
    """`export NAME='value'` lines, for a shell to run the tests against a stack left up."""
    return "\n".join(f"export {n}='{env[n]}'" for n in names)
