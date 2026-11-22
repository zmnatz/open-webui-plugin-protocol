# Lets the model show, read and change the chat's drawing.

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from shared import (
    _ID,
    MARKER,
    PREFIX,
    _as_list,
    _empty,
    _load,
    _merge,
    _mutate,
    _simplify,
    _with_ids,
)

ELEMENT_DOC = """\
Elements use Excalidraw's skeleton format. Every element, arrows included, needs
a finite numeric "x" and "y"; without them the editor canvas goes blank:
  {"type":"rectangle","id":"a","x":0,"y":0,"width":160,"height":80,"label":{"text":"API"}}
  {"type":"ellipse"|"diamond", ... same fields}
  {"type":"text","x":0,"y":0,"text":"Hello","fontSize":20}
  {"type":"arrow"|"line","x":0,"y":0,"points":[[0,0],[200,0]]}
  Give shapes an "id" so arrows can connect to them; arrow points are relative
  to the arrow's x/y, so put that x/y where the arrow starts:
  {"type":"arrow","x":160,"y":40,"points":[[0,0],[120,0]],"start":{"id":"a"},"end":{"id":"b"},"label":{"text":"calls"}}
Optional: strokeColor, backgroundColor, fillStyle ("solid"|"hachure"|"cross-hatch"),
strokeStyle ("solid"|"dashed"|"dotted"), roughness (0 clean, 1 sketchy).
Layout: ~200px between box columns, ~120px between rows; y grows downward."""


class Tools:
    # -------------------------------------------------------------- tools

    async def show_excalidraw(
        self,
        elements: Optional[List[Dict[str, Any]]] = None,
        __metadata__: Optional[dict] = None,
    ) -> dict:
        """
        Show this chat's Excalidraw drawing to the user as a live editor they can
        draw in. Creates it on first use. Call this whenever the user asks for a
        diagram, sketch, whiteboard or drawing, passing the initial elements in
        the same call. The editor opens in the side panel on its own; do not
        paste a link, iframe or code. Call it once per chat: the panel keeps the
        editor open across later replies, so later changes go through
        upsert_excalidraw_elements and appear in the same editor within about
        two seconds. Call it again only if the user asks to see the drawing.

        :param elements: Optional elements to add before showing. See the element format below.
        """
        chat_id = _tool_chat_id(__metadata__)
        incoming = _as_list(elements)
        scene = await _mutate(
            chat_id,
            lambda current, new: (
                _merge(current, incoming) if incoming else (None if not new else [])
            ),
            "tool",
            pass_new=True,
        )
        src = f"{PREFIX}/view/{quote(chat_id, safe='')}"
        # The function's outlet adds this to the reply as an ```html block for the Artifacts panel.
        artifact = (
            f'<iframe src="{src}" title="Excalidraw" '
            'style="position:fixed;inset:0;width:100%;height:100%;border:0" '
            'allow="clipboard-read; clipboard-write"></iframe>'
        )
        return {
            "status": (
                "The editor opens in the Artifacts side panel when your reply "
                "finishes. Do not paste a link, iframe or code for it."
            ),
            "version": scene["version"],
            "note": "Use upsert_excalidraw_elements to change it and read_excalidraw to see the user's edits.",
            MARKER: artifact,
        }

    async def read_excalidraw(self, __metadata__: Optional[dict] = None) -> str:
        """
        Read the drawing as the user currently sees it, including their edits.
        Bound text is folded into each shape's `label`; arrows list `start` and
        `end` shape ids. Call this before changing a drawing the user has been
        editing.
        """
        scene = await _load(_tool_chat_id(__metadata__)) or _empty()
        return json.dumps(
            {"version": scene["version"], "elements": _simplify(scene["elements"])}
        )

    async def upsert_excalidraw_elements(
        self, elements: List[Dict[str, Any]], __metadata__: Optional[dict] = None
    ) -> str:
        """
        Add elements to the drawing, or update existing ones by id. Elements not
        mentioned are untouched, so the user's work is preserved. Prefer this
        over replace_excalidraw_elements. The open editor updates by itself.

        :param elements: Elements to add or update. See the element format below.
        """
        incoming = _as_list(elements)
        scene = await _mutate(
            _tool_chat_id(__metadata__),
            lambda current: _merge(current, incoming),
            "tool",
        )
        return f"Updated. The open editor will show it shortly (version {scene['version']})."

    async def replace_excalidraw_elements(
        self, elements: List[Dict[str, Any]], __metadata__: Optional[dict] = None
    ) -> str:
        """
        Replace everything in the drawing. This discards the user's edits, so use
        it only to start over.

        :param elements: The complete new set of elements. See the element format below.
        """
        incoming = _with_ids(_as_list(elements))
        scene = await _mutate(_tool_chat_id(__metadata__), lambda _: incoming, "tool")
        return f"Replaced (version {scene['version']})."

    async def delete_excalidraw_elements(
        self, ids: List[str], __metadata__: Optional[dict] = None
    ) -> str:
        """
        Remove elements from the drawing by id (get ids from read_excalidraw).

        :param ids: Ids of the elements to remove.
        """
        drop = set(ids)
        scene = await _mutate(
            _tool_chat_id(__metadata__),
            lambda current: [
                e
                for e in current
                if e.get("id") not in drop and e.get("containerId") not in drop
            ],
            "tool",
        )
        return f"Deleted (version {scene['version']})."


# Inserted before the :param lines so it stays in the tool description.
for _fn in (
    Tools.show_excalidraw,
    Tools.upsert_excalidraw_elements,
    Tools.replace_excalidraw_elements,
):
    _head, _sep, _params = (_fn.__doc__ or "").partition(":param")
    _fn.__doc__ = (
        _head.rstrip() + "\n\n" + ELEMENT_DOC + "\n\n        " + _sep + _params
    )


def _tool_chat_id(__metadata__: Optional[dict]) -> str:
    chat_id = (__metadata__ or {}).get("chat_id")
    if not chat_id or not _ID.fullmatch(chat_id):
        raise RuntimeError("No chat id: send a message first, then retry.")
    return chat_id
