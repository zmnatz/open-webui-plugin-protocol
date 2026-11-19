"""A stand-in for an OpenAI-compatible model server, for the screenshot run (compose.yaml).

It needs nothing but the standard library. The screenshots need a model that calls the plugins'
tools the same way every time, so this one follows a script instead of thinking:

- Asked with tools (native function calling), it calls the first tool whose name is in SCRIPT,
  with the arguments listed there. Once the tool has answered, it replies with SCRIPT's text.
- Asked in Open-WebUI's default mode (a prompt listing the tools, answered with JSON), it answers
  with the same call as {"tool_calls": [...]}.
- Anything else gets a short fixed reply, so the chat shows a normal answer.

It also answers /model/info as a LiteLLM gateway would, for the LiteLLM Model Sync example.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "screenshot-model"

BOX = {"type": "rectangle", "id": "api", "x": 80, "y": 80, "width": 200, "height": 90}
DB = {"type": "ellipse", "id": "db", "x": 420, "y": 80, "width": 200, "height": 90}
# The tool call each plugin's tool gets, and what the model says once it has answered.
SCRIPT = {
    "show_excalidraw": (
        {
            "elements": [
                {**BOX, "label": {"text": "API"}},
                {**DB, "label": {"text": "Database"}},
                {
                    "type": "arrow",
                    "id": "q",
                    "x": 280,
                    "y": 125,
                    "points": [[0, 0], [140, 0]],
                    "start": {"id": "api"},
                    "end": {"id": "db"},
                },
            ]
        },
        "Here is the diagram: the API reads from the database. Edit it in the panel.",
    ),
}
PLAIN = "Hello! I am the screenshot model: I answer the same way every time."
EMBEDDING = "screenshot-embedding"
# What a LiteLLM gateway's /model/info says about the models, for examples/plugins/litellm_model_sync.
MODEL_INFO = [
    {
        "model_name": MODEL,
        "model_info": {
            "display_name": "Screenshot Model",
            "litellm_provider": "anthropic",
            "model_family": "claude",
            "mode": "chat",
            "capabilities": {"vision": True, "tools": True},
        },
    },
    {
        "model_name": EMBEDDING,
        "model_info": {
            "display_name": "Screenshot Embeddings",
            "litellm_provider": "openai",
            "mode": "embedding",
            "capabilities": {},
        },
    },
]


def _tool_names(body: dict) -> list[str]:
    return [t.get("function", {}).get("name", "") for t in body.get("tools") or []]


def _reply(body: dict) -> dict:
    """{"content": str} or {"tool_call": (name, args)}."""
    messages = body.get("messages") or []
    last = messages[-1] if messages else {}
    called = [call["function"]["name"] for m in messages for call in m.get("tool_calls") or []]
    # Open-WebUI may put calls of its own in front (v0.13 lists the skills first), so the
    # script's tool is called whenever it is offered and has not been called yet.
    for name in _tool_names(body):
        if name in SCRIPT and name not in called:
            return {"tool_call": (name, SCRIPT[name][0])}
    if last.get("role") == "tool":
        done = [name for name in called if name in SCRIPT]
        return {"content": SCRIPT[done[-1]][1] if done else "Done."}
    # Default (prompt-based) function calling: the tools are listed in the system prompt.
    prompt = " ".join(str(m.get("content", "")) for m in messages)
    if "tool_calls" in prompt:
        for name, (args, _) in SCRIPT.items():
            if f'"{name}"' in prompt or f"'{name}'" in prompt:
                return {"content": json.dumps({"tool_calls": [{"name": name, "parameters": args}]})}
        return {"content": json.dumps({"tool_calls": []})}
    if "title" in prompt.lower() and "chat" in prompt.lower() and last.get("role") == "user":
        # Open-WebUI's title and tag tasks want JSON; keep them short and stable.
        if "tags" in prompt.lower():
            return {"content": json.dumps({"tags": ["Demo"]})}
        return {"content": json.dumps({"title": "Screenshot demo"})}
    return {"content": PLAIN}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path.endswith("/model/info"):  # LiteLLM's, beside /v1
            self._send(200, {"data": MODEL_INFO})
        elif path.endswith("/models"):
            models = [{"id": m, "object": "model"} for m in (MODEL, EMBEDDING)]
            self._send(200, {"object": "list", "data": models})
        else:
            self._send(200, {"status": "ok"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if os.environ.get("FAKE_LLM_LOG"):  # debugging: what Open-WebUI sends
            summary = {
                "tools": _tool_names(body),
                "messages": [
                    [m.get("role"), str(m.get("content"))[:80], m.get("tool_calls")]
                    for m in body.get("messages") or []
                ],
            }
            print(json.dumps(summary), flush=True)
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": "not found"})
            return
        reply = _reply(body)
        call_id = f"call_{uuid.uuid4().hex[:12]}"
        if "tool_call" in reply:
            name, args = reply["tool_call"]
            delta = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
            }
            message = {"role": "assistant", "content": None, "tool_calls": delta["tool_calls"]}
            finish = "tool_calls"
        else:
            delta = message = {"role": "assistant", "content": reply["content"]}
            finish = "stop"
        base = {"id": f"chatcmpl-{call_id}", "created": int(time.time()), "model": MODEL}
        if not body.get("stream"):
            self._send(
                200,
                {
                    **base,
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                },
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in (
            {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
        ):
            event = {**base, "object": "chat.completion.chunk", **chunk}
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
