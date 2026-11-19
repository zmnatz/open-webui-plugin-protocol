# Page Banners: an Event function that shows the admin banners in every chat.
#
# The page-side code is not here: it is assets/loader.js and assets/custom.css, published
# into the Shared Assets Protocol by `class Event(PluginAssets)` (the assets library). This
# file is only what has to run on the server: the valves, the numbers the script is given
# (asset_vars) and the push to open tabs when an admin edits the banners.
#
# A variant of Better Banners by Classic298 (BSD-3-Clause; see NOTICE.md in the repository root).

import json
from typing import Literal

from pydantic import BaseModel, Field

SOCKET_EVENT = "owui:page-banners"  # distinct from Better Banners', so both can be installed
BANNERS_UPDATED_EVENT = "config.banners.updated"


class Event(PluginAssets):  # a PluginEvents class, so @on handlers work
    class Valves(BaseModel):
        position: Literal["top", "bottom"] = Field(
            default="top",
            description="Where banners appear: at the top of the chat, or right above the message input.",
        )
        max_height_px: int = Field(
            default=160,
            ge=60,
            le=600,
            description="Tallest a single expanded banner gets before its text scrolls.",
        )
        resync_interval_seconds: int = Field(
            default=300,
            ge=0,
            le=3600,
            description="How often each open tab re-reads the banners on its own, as a backstop for a live update it missed. 0 turns it off.",
        )

    def asset_vars(self) -> dict:
        """Fills the config placeholder in assets/loader.js. Runs on every page load, so the
        library rebuilds the script only when this returns something different."""
        return {
            "CONFIG": json.dumps(
                {
                    "event": SOCKET_EVENT,
                    "position": self.valves.position,
                    "maxHeight": self.valves.max_height_px,
                    "resync": self.valves.resync_interval_seconds,
                }
            )
        }

    @on(BANNERS_UPDATED_EVENT)
    async def push(self):
        """An admin edited the banners: tell the open tabs to re-read them."""
        from open_webui.socket.main import sio

        await sio.emit(SOCKET_EVENT, {})
