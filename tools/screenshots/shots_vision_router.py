"""Dynamic Vision Router on a real Open-WebUI: a picture goes to the vision model."""

from __future__ import annotations

import struct
import zlib

import pytest
from conftest import URL, send


def png(path, size: int = 96) -> None:
    """A small square picture, blue on white, to attach."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(
        b"\0"
        + b"".join(
            b"\x3b\x82\xf6"
            if size // 4 < x < 3 * size // 4 and size // 4 < y < 3 * size // 4
            else b"\xff\xff\xff"
            for x in range(size)
        )
        for y in range(size)
    )
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def routed(api):
    """vision_model_id set and the status line on; put back afterwards."""
    before = api.valves("vision_router", vision_model_id="screenshot-vision", status=True)
    yield
    api("POST", "/api/v1/functions/id/vision_router/valves/update", before)


def test_a_picture_goes_to_the_vision_model(user, shot, routed, tmp_path):
    """By hand: set vision_model_id, and as a user who is not an admin send a picture to another
    model. The status line says where it went, and the vision model answers."""
    picture = tmp_path / "square.png"
    png(picture)
    user.goto(f"{URL}/?models=screenshot-model")
    user.locator("input[type=file]").first.set_input_files(str(picture))
    send(user, "What is in this picture?")
    user.get_by_text("I am the vision model").last.wait_for(timeout=60_000)
    user.wait_for_timeout(1000)
    shot(
        user,
        "vision_router",
        "routed",
        "A picture sent to the screenshot model: the filter sent it to the vision model instead, "
        "and the status line says so.",
        illustrates=[
            "test_a_message_with_an_image_goes_to_the_vision_model",
            "test_it_can_say_where_the_message_went",
        ],
    )
