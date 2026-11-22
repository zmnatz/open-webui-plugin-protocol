# Syncs the servers listed in mcpo's /openapi.json into Open-WebUI as OpenAPI tool servers.

from __future__ import annotations

import logging
import os
import re
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, Field

from owpp.lib import PluginScheduledSync, plugin_config, plugin_function_id, plugin_sync_markers

log = logging.getLogger(__name__)

# mcpo's root description lists servers as "- [name](/name/docs)".
MCPO_SERVER_LINK = re.compile(r"\[([^\]]+)\]\(/([^)/]+)/docs\)")


class Event(PluginScheduledSync):  # event / repeat: the jobs library
    class Valves(BaseModel):
        MCPO_BASE_URL: str = Field(
            default="http://mcpo:8000",
            description="Base URL of the mcpo proxy.",
        )
        MCPO_API_KEY: str = Field(
            default="",
            description="mcpo --api-key value, sent as Authorization: Bearer. Empty uses the MCPO_API_KEY environment variable.",
        )
        INCLUDE_SERVERS: str = Field(
            default="",
            description="Comma-separated allowlist of mcpo server names. Empty means all.",
        )
        EXCLUDE_SERVERS: str = Field(
            default="",
            description="Comma-separated denylist of mcpo server names.",
        )
        PRUNE_MANAGED: bool = Field(
            default=True,
            description="Remove previously synced servers that no longer exist in mcpo.",
        )
        REQUEST_TIMEOUT: int = Field(
            default=15,
            description="HTTP timeout in seconds for the mcpo request.",
        )

    @property
    def owner(self) -> str:
        """The marker on every tool-server entry this function writes, and the only thing it
        prunes: its own id, plus the markers plugin.yaml's jobs: adopt_markers names
        (plugin_sync_markers). Never None where it matters: sync() stops if it cannot tell."""
        return plugin_function_id()

    async def sync(self):
        if not self.owner:  # a missing marker would match, and prune, every hand-made entry
            log.warning("mcpo Sync: cannot tell which function this is; skipping")
            return
        base = self.valves.MCPO_BASE_URL.strip().rstrip("/")
        # The valve wins; otherwise the container's MCPO_API_KEY.
        key = (self.valves.MCPO_API_KEY or os.environ.get("MCPO_API_KEY", "")).strip()
        if not base or not key:
            log.warning("mcpo Sync: MCPO_BASE_URL / MCPO_API_KEY not set; skipping")
            return

        try:
            routes = await self.fetch_servers(base, key)
        except Exception as e:
            log.error("mcpo Sync: failed to list servers from %s: %s", base, e)
            return

        connections = self.build_connections(base, key, routes)
        try:
            await self.persist(connections)
        except Exception as e:
            log.error("mcpo Sync: failed to persist tool servers: %s", e)

    async def fetch_servers(self, base: str, key: str) -> list[str]:
        # The server list is in the root OpenAPI document's description.
        url = f"{base}/openapi.json"
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=self.valves.REQUEST_TIMEOUT)
        async with (
            aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
            session.get(url, headers=headers) as resp,
        ):
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")
            data = await resp.json()

        description = (data.get("info") or {}).get("description") or ""
        return [route for _label, route in MCPO_SERVER_LINK.findall(description)]

    def build_connections(self, base: str, key: str, routes: list[str]) -> list[dict]:
        allow = self._names(self.valves.INCLUDE_SERVERS)
        deny = self._names(self.valves.EXCLUDE_SERVERS)

        config = plugin_config()
        servers = config.get("servers")
        servers = servers if isinstance(servers, dict) else {}

        connections = []
        for route in routes:
            if allow and route not in allow:
                continue
            if route in deny:
                continue
            override = servers.get(route)
            override = override if isinstance(override, dict) else {}
            connections.append(
                {
                    "url": f"{base}/{quote(route, safe='')}",
                    "path": "openapi.json",
                    "type": "openapi",
                    "auth_type": "bearer",
                    "key": key,
                    "config": {"enable": bool(override.get("enable", config.get("enable", True)))},
                    "info": {
                        "id": f"mcpo-{route}",
                        "name": str(override.get("name") or f"{route} (mcpo)"),
                        "description": str(
                            override.get("description") or f"{route} MCP server via mcpo (OpenAPI)"
                        ),
                        "managed_by": self.owner,
                    },
                }
            )
        return connections

    @staticmethod
    def _names(value: str) -> set[str]:
        return {name.strip() for name in value.split(",") if name.strip()}

    async def persist(self, connections: list[dict]):
        from open_webui.models.config import Config

        existing = await Config.get("tool_server.connections", []) or []
        synced_ids = {connection["info"]["id"] for connection in connections}

        mine = plugin_sync_markers()
        kept = []
        for connection in existing:
            info = connection.get("info") or {}
            if info.get("managed_by") in mine:
                # Drop entries being replaced, and stale ones when pruning.
                if info.get("id") in synced_ids or self.valves.PRUNE_MANAGED:
                    continue
            elif info.get("id") in synced_ids:
                # Replace manual entries that collide with a synced server id.
                continue
            kept.append(connection)

        await Config.upsert({"tool_server.connections": kept + connections})
        log.info("mcpo Sync: %d server(s) synced", len(connections))
