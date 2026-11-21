"""A filter for the live suite (tools/live), never deployed from examples/plugins.

The idea is from "Dynamic Vision Router" by open-webui and atgehrhardt
(https://github.com/open-webui/functions/tree/main/functions/filters/dynamic_vision_router):
an inlet that sends a message with an image to another model. That repository declares no
licence, so none of its code is used here; this is written from the idea alone. See NOTICE.md.

It shows what an inlet can do that the mock cannot check: change `body["model"]` from a valve,
and see which model and which user the real Open-WebUI passes in.
"""

from pydantic import BaseModel, Field


def has_image(messages: list) -> bool:
    last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    content = (last or {}).get("content")
    return isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in content
    )


class Filter:
    class Valves(BaseModel):
        vision_model_id: str = Field(default="", description="Where messages with images go.")

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __model__: dict | None = None) -> dict:
        target = self.valves.vision_model_id
        if target and (__model__ or {}).get("id") != target and has_image(body.get("messages", [])):
            body["model"] = target
        return body
