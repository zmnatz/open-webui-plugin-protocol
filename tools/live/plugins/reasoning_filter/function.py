"""A filter for the live suite (tools/live), never deployed from examples/plugins.

The inlet adds a system message the scripted model can be seen to receive. The outlet is
modelled on "Clear thinking tags" by Haervwe (MIT,
https://github.com/Haervwe/open-webui-tools/blob/main/filters/clean_thinking_tags_filter.py):
when a reply ends in reasoning with no answer after it, the reasoning becomes the answer. The
code is written here, not copied. See NOTICE.md.
"""

import re

MARKER = "LIVE-TEST-INLET-MARKER"


def _text(item: dict) -> str:
    parts = item.get("content") or []
    return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))


class Filter:
    def inlet(self, body: dict) -> dict:
        body.setdefault("messages", []).insert(0, {"role": "system", "content": MARKER})
        return body

    def outlet(self, body: dict) -> dict:
        messages = body.get("messages") or []
        last = messages[-1] if messages else None
        if not isinstance(last, dict) or last.get("role") != "assistant":
            return body
        output = last.get("output")
        if isinstance(output, list) and output:
            # Open-WebUI 0.12+ renders from `output`, so that is what must change.
            end = output[-1]
            if isinstance(end, dict) and end.get("type") == "reasoning":
                text = re.sub(r"</think>", "", _text(end), flags=re.IGNORECASE).strip()
                if text:
                    output[-1] = {
                        "type": "message",
                        "id": end.get("id") or "msg-live-test",
                        "status": "completed",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                    last["content"] = text
        return body
