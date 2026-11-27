"""The Open-WebUI pin (tools/sync_open_webui.py, ADR 0004): read offline. CI's `--check` compares
it with upstream."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import tomllib

from owpp.testing import pin

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("sync", ROOT / "tools" / "sync_open_webui.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

LOCK = """\
aiocache==0.12.3 \\
    --hash=sha256:aaa \\
    --hash=sha256:bbb
    # via -r requirements-slim.txt
colorama==0.4.6 ; sys_platform == 'win32' \\
    --hash=sha256:ccc
"""


def test_lock_pins_keep_each_requirement_and_its_marker_without_hashes():
    assert sync.lock_pins(LOCK) == [
        ("aiocache==0.12.3", ""),
        ("colorama==0.4.6", "sys_platform == 'win32'"),
    ]


def test_the_extra_adds_the_image_python_to_every_pin():
    block = sync.extra(sync.lock_pins(LOCK), "python_version == '3.12'")
    assert "\"aiocache==0.12.3 ; python_version == '3.12'\"," in block
    assert "\"colorama==0.4.6 ; (sys_platform == 'win32') and python_version == '3.12'\"," in block
    assert block.startswith(sync.BEGIN) and block.endswith(sync.END)


def test_image_python_is_the_dockerfile_python_base():
    dockerfile = (
        "FROM --platform=$BUILDPLATFORM node:22 AS build\nFROM python:3.12-slim-trixie AS base\n"
    )
    assert sync.image_python(dockerfile) == "3.12"


def test_the_live_stack_runs_the_pinned_version():
    compose = (ROOT / "src" / "owpp" / "live" / "compose.yaml").read_text()
    assert f"ghcr.io/open-webui/open-webui:v{pin.VERSION}-slim" in compose


def test_every_pin_of_the_test_extra_is_for_the_image_python():
    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    pins = [r for r in extra["test"] if "==" in r]
    assert pins and all(r.endswith(f"python_version == '{pin.PYTHON}'") for r in pins)
    assert any(re.match(r"fastapi==", r) for r in pins)
