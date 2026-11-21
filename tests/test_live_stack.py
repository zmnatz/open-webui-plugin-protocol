"""The Docker stack the screenshots and the live suite run (tools/screenshots/compose.yaml)."""

from __future__ import annotations

import json
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


STACK = ROOT / "tools" / "screenshots"


def test_aimock_is_pinned_and_every_fixture_names_its_model():
    """aimock's list of models is the models its fixtures match on, so each fixture names one;
    and the image is pinned, so a new aimock never changes a run by itself."""
    services = yaml.safe_load((STACK / "compose.yaml").read_text())["services"]
    tag = services["aimock"]["image"].rpartition(":")[2]
    assert tag[:1].isdigit(), services["aimock"]["image"]
    fixtures = json.loads((STACK / "aimock" / "models.json").read_text())["fixtures"]
    assert fixtures and all(f["match"].get("model") for f in fixtures)


def test_the_gateway_describes_every_model_aimock_answers_as():
    """litellm_model_sync gives a model its read grant from the gateway's /model/info; a model
    missing there cannot be used by a user who is not an admin ("Model not found")."""
    fixtures = json.loads((STACK / "aimock" / "models.json").read_text())["fixtures"]
    answered = {f["match"]["model"] for f in fixtures}
    listed = {
        m["id"] for m in json.loads((STACK / "gateway" / "v1" / "models").read_text())["data"]
    }
    info = json.loads((STACK / "gateway" / "model" / "info").read_text())["data"]
    described = {m["model_name"] for m in info}
    assert answered <= listed == described
