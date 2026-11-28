"""aimock, the model of the test harness: the same OpenAI-compatible server, at the same version,
as the model of `owpp live` (its compose file pins it).

It runs with Bun (`bunx`) if Bun is installed, else with Node (`npx`), else with Docker. It
starts only when a test first uses the model, so a run that never asks a model needs none of
them.

The harness gives it its fixtures for each test through aimock's control API
(`POST /__aimock/fixtures`), and reads what Open-WebUI sent it from its journal.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE = "@copilotkit/aimock"
# The package's server command, the one its Docker image runs (`node dist/cli.js`): its `aimock`
# command takes a config file instead.
BIN = "llmock"
RUNNERS = ("bun", "node", "docker")  # in this order: the first on PATH runs aimock
TOOLS = {"bun": "bunx", "node": "npx", "docker": "docker"}


def version() -> str:
    """The aimock version `owpp live` runs: the tag of its image in owpp's compose file."""
    from ..live.stack import COMPOSE

    found = re.search(r"ghcr\.io/copilotkit/aimock:([0-9][^\s\"']*)", COMPOSE.read_text())
    if not found:
        raise RuntimeError(f"{COMPOSE} pins no aimock image")
    return found.group(1)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _command(runner: str, port: int, fixtures: Path, name: str) -> list[str]:
    # The tool as PATH has it (bunx.exe, npx.cmd on Windows), so it starts on every system.
    tool = shutil.which(TOOLS[runner]) or TOOLS[runner]
    args = ["--fixtures", "{fixtures}", "--port", "{port}", "--log-level", "warn"]
    at = f"{PACKAGE}@{version()}"
    if runner == "bun":
        rest = [a.format(fixtures=fixtures, port=port) for a in args]
        return [tool, "--package", at, BIN, "--host", "127.0.0.1", *rest]
    if runner == "node":
        rest = [a.format(fixtures=fixtures, port=port) for a in args]
        return [tool, "--yes", "--package", at, BIN, "--host", "127.0.0.1", *rest]
    rest = [a.format(fixtures="/fixtures", port=4010) for a in args]
    return [
        tool, "run", "--rm", "--name", name,
        "-p", f"127.0.0.1:{port}:4010",
        "-v", f"{fixtures}:/fixtures:ro",
        f"ghcr.io/copilotkit/aimock:{version()}",
        "--host", "0.0.0.0", *rest,
    ]  # fmt: skip


def pick_runner() -> str:
    """Bun if it is installed, else Node, else Docker."""
    for runner in RUNNERS:
        if shutil.which(TOOLS[runner]):
            return runner
    raise RuntimeError(
        "a test asked the harness's model, which is aimock: install Bun, Node (20 or newer) or "
        "Docker to run it"
    )


class Aimock:
    """One aimock on 127.0.0.1:`port`, started by `start()`, stopped when the process ends."""

    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self._process: subprocess.Popen | None = None
        self._name = f"owpp-harness-aimock-{os.getpid()}-{port}"

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, timeout: float = 120) -> None:
        if self.running:
            return
        runner = pick_runner()
        folder = Path(tempfile.mkdtemp(prefix="owpp-aimock-"))
        (folder / "none.json").write_text('{"fixtures": []}\n')
        log = open(folder / "aimock.log", "w")  # noqa: SIM115 (lives as long as aimock)
        self._process = subprocess.Popen(
            _command(runner, self.port, folder, self._name),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        self._runner = runner
        atexit.register(self.stop)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"aimock ({runner}) stopped as it started: {(folder / 'aimock.log').read_text()}"
                )
            try:
                self._call("GET", "/__aimock/health")
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"aimock ({runner}) did not answer on {self.url} in {timeout:.0f}s")

    def stop(self) -> None:
        if self._process is None:
            return
        if getattr(self, "_runner", None) == "docker":
            docker = shutil.which("docker") or "docker"
            subprocess.run([docker, "rm", "-f", self._name], capture_output=True, check=False)
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (127.0.0.1)
            text = response.read()
        return json.loads(text) if text.strip() else None

    def set_fixtures(self, fixtures: list[dict]) -> None:
        """Replace aimock's fixtures (first match wins), and empty its journal."""
        self._call("POST", "/__aimock/reset")
        if fixtures:
            self._call("POST", "/__aimock/fixtures", {"fixtures": fixtures})

    def requests(self, path: str = "/v1/chat/completions") -> list[dict]:
        """Each request body aimock got at `path`, oldest first: what Open-WebUI sent it."""
        entries = self._call("GET", f"/__aimock/journal?path={path}") or []
        return [entry["body"] for entry in entries if entry.get("body")]
