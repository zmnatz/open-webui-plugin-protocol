"""The Docker stack the screenshots and the live suite run (tools/screenshots/compose.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_every_open_webui_it_starts_is_the_slim_image_at_a_pinned_version():
    """The slim image leaves out the bundled ML models (about 4.5 GB in the full one), which
    nothing here uses; a pinned version keeps every run on the one the protocol targets."""
    images = [
        service["image"]
        for compose in ROOT.glob("tools/**/compose*.y*ml")
        for service in (yaml.safe_load(compose.read_text()).get("services") or {}).values()
        if "open-webui/open-webui" in service.get("image", "")
    ]
    assert images, "no Open-WebUI service found"
    for image in images:
        tag = image.rpartition(":")[2]
        assert tag.startswith("v") and tag.endswith("-slim"), image
