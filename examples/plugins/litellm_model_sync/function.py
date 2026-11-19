
# Open-WebUI Event function. On startup / enable / valve change, and then every
# SYNC_INTERVAL_MINUTES (the `jobs` library, plugin.yaml: jobs), it walks the
# OpenAI connections configured in Open-WebUI, asks each LiteLLM gateway for
# GET /model/info (the base URL minus /v1, same bearer key as the
# connection), and writes the gateway's metadata into Open-WebUI's model
# configs: the friendly display name, hiding of non-chat (embedding /
# decision / transcription) models, the vision capability the model states,
# and tags for the vendor (model_info.litellm_provider) and the model family
# (model_info.model_family). Connections that are not LiteLLM are skipped.
# It only changes or deletes model configs it wrote (meta.managed_by: its own
# function id), and never on an empty or failed answer.

from __future__ import annotations

import logging
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

CAPABILITIES = ("vision", "tools", "reasoning")


def info_url(base_url: str, path: str) -> str:
    """LiteLLM serves /model/info beside /v1, so drop a trailing /v1."""
    base = base_url.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/{path.strip().lstrip('/')}"


def merge_models(data: list[dict]) -> dict[str, dict]:
    """One record per model_name out of /model/info's one-row-per-deployment.

    A name served by several providers has a row per deployment, tiered by
    litellm_params.order. The lowest order is the one that answers first, so it
    names the provider and family; a capability counts only when every tier
    states it (the gateway already requires the tiers to agree).
    """
    grouped: dict[str, list[dict]] = {}
    for row in data:
        name = row.get("model_name")
        if name:
            grouped.setdefault(name, []).append(row)

    merged = {}
    for name, rows in grouped.items():
        rows.sort(key=lambda r: (r.get("litellm_params") or {}).get("order") or 0)
        infos = [r.get("model_info") or {} for r in rows]
        first = infos[0]
        caps = {
            cap: all((i.get("capabilities") or {}).get(cap) is True for i in infos)
            for cap in CAPABILITIES
        }
        merged[name] = {
            "display_name": first.get("display_name") or name,
            "provider": first.get("litellm_provider"),
            "family": first.get("model_family"),
            "mode": first.get("mode"),
            "capabilities": caps,
        }
    return merged


def model_id(prefix: str, name: str) -> str:
    """The id Open-WebUI gives a connection's model (prefix_id joined by a dot)."""
    return f"{prefix}.{name}" if prefix else name


def grant_dict(grant) -> dict:
    """An access grant as the plain dict ModelForm takes (row objects or dicts)."""
    get = grant.get if isinstance(grant, dict) else lambda k: getattr(grant, k)
    return {k: get(k) for k in ("principal_type", "principal_id", "permission")}


def desired_tags(record: dict, vendor: bool, family: bool, capability_tags: bool) -> list[str]:
    tags = []
    if vendor and record.get("provider"):
        tags.append(str(record["provider"]))
    if family and record.get("family"):
        tags.append(str(record["family"]))
    if capability_tags:
        tags.extend(cap for cap in CAPABILITIES if record["capabilities"].get(cap))
    return list(dict.fromkeys(tags))


def merge_tags(existing: list, previous: list[str], desired: list[str]) -> list[dict]:
    """Keep tags a person added, replace the ones this function wrote last time."""
    names = [t.get("name") if isinstance(t, dict) else t for t in existing or []]
    kept = [n for n in names if n and n not in previous]
    return [{"name": n} for n in dict.fromkeys(kept + desired)]


class Event(PluginScheduledSync):  # event / repeat: the jobs library
    class Valves(BaseModel):
        INFO_PATH: str = Field(
            default="/model/info",
            description="LiteLLM model-info path, relative to the connection URL minus /v1.",
        )
        INCLUDE_CONNECTIONS: str = Field(
            default="",
            description=(
                "Comma-separated substrings of connection URLs to sync. "
                "Empty means every OpenAI connection that answers /model/info."
            ),
        )
        SET_VISION: bool = Field(
            default=True,
            description="Set the model's vision capability from the gateway's capabilities map.",
        )
        TAG_VENDOR: bool = Field(
            default=True, description="Tag each model with its provider (litellm_provider)."
        )
        TAG_FAMILY: bool = Field(
            default=True, description="Tag each model with its family (model_family)."
        )
        TAG_CAPABILITIES: bool = Field(
            default=False,
            description="Also tag vision / tools / reasoning where the model states them.",
        )
        NATIVE_FUNCTION_CALLING: bool = Field(
            default=False,
            description=(
                "Set params.function_calling=native on models that state tools support. "
                "Off by default because it changes how tool calls are made."
            ),
        )
        PRUNE_MISSING: bool = Field(
            default=True,
            description=(
                "Delete model configs this function created whose model the gateway "
                "no longer returns. Only runs for a connection that returned models, "
                "never on an empty or failed response."
            ),
        )
        PUBLIC_READ: bool = Field(
            default=True,
            description=(
                "Give every managed model config a public read grant (existing grants "
                "are kept). Without one Open-WebUI treats the config as private and "
                "hides the model from non-admins."
            ),
        )
        ADOPT_EXISTING: bool = Field(
            default=False,
            description=(
                "Also overwrite model configs this function did not create and that "
                "already have a custom name. Off by default; configs with no custom "
                "name are adopted either way."
            ),
        )
        HIDE_MODES: str = Field(
            default="embedding,decisions,audio_transcription",
            description=(
                "Comma-separated LiteLLM model modes to hide from the model selector "
                "(meta.hidden; they stay enabled). Default covers embeddings, decision and Whisper."
            ),
        )
        REQUEST_TIMEOUT: int = Field(default=15, description="HTTP timeout in seconds.")
        ADOPT_MARKERS: str = Field(
            default="",
            description=(
                "Comma-separated managed_by markers of an earlier sync to treat as this "
                "function's own: their configs are updated and pruned like its own. For "
                "moving from another sync. Empty adopts nothing."
            ),
        )

    @property
    def owner(self) -> str:
        """The marker on every model config this function writes, and the only thing it
        changes or prunes: its own id. (Never None where it matters: sync() stops if it
        cannot tell.)"""
        return plugin_function_id()

    def mine(self, meta: dict) -> bool:
        adopted = {m.strip() for m in self.valves.ADOPT_MARKERS.split(",") if m.strip()}
        return meta.get("managed_by") in {self.owner} | adopted

    async def sync(self):
        if not self.owner:  # a missing marker would match, and prune, every hand-made config
            log.warning("LiteLLM Model Sync: cannot tell which function this is; skipping")
            return
        try:
            connections = await self.connections()
        except Exception as e:
            log.error("LiteLLM Model Sync: cannot read OpenAI connections: %s", e)
            return

        total = 0
        current: set[str] = set()  # every id any connection returned
        answered: set[str] = set()  # connections that returned models
        failed = False
        for conn in connections:
            try:
                data = await self.fetch_info(conn["base"], conn["key"])
            except Exception as e:
                # Most connections are not LiteLLM (or are down); not an error.
                log.info("LiteLLM Model Sync: %s has no /model/info (%s); skipping", conn["base"], e)
                failed = True
                continue
            records = merge_models(data)
            if not records:
                # An empty answer is not evidence the models are gone.
                log.warning("LiteLLM Model Sync: %s returned no models; keeping its configs", conn["base"])
                failed = True
                continue
            try:
                total += await self.apply(conn, records)
            except Exception as e:
                log.error("LiteLLM Model Sync: failed to update models for %s: %s", conn["base"], e)
                failed = True
                continue
            current.update(model_id(conn["prefix"], name) for name in records)
            answered.add(conn["base"])
        pruned = 0
        if self.valves.PRUNE_MISSING and answered:
            try:
                pruned = await self.prune(current, answered, failed)
            except Exception as e:
                log.error("LiteLLM Model Sync: prune failed: %s", e)
        log.info("LiteLLM Model Sync: %d model config(s) written, %d removed", total, pruned)

    async def prune(self, current: set[str], answered: set[str], failed: bool) -> int:
        """Delete managed configs the gateway stopped returning.

        A config is only ever deleted if this function created it
        (meta.managed_by) and its source connection answered with models this
        run. Configs from before sources were recorded have no source, so they
        are pruned only when every connection answered.
        """
        from open_webui.models.models import Models

        removed = 0
        for row in await Models.get_all_models():
            if row.base_model_id is not None or row.id in current:
                continue
            meta = row.meta.model_dump()
            if not self.mine(meta):
                continue
            source = meta.get("sync_source")
            if source is None:
                if failed:
                    continue
            elif source not in answered:
                continue
            if await Models.delete_model_by_id(row.id):
                removed += 1
                log.info("LiteLLM Model Sync: removed %s (no longer returned by %s)", row.id, source or "gateway")
        return removed

    async def connections(self) -> list[dict]:
        from open_webui.models.config import Config

        if not await Config.get("openai.enable", True):
            return []
        urls = await Config.get("openai.api_base_urls", []) or []
        keys = await Config.get("openai.api_keys", []) or []
        configs = await Config.get("openai.api_configs", {}) or {}

        allow = [s.strip() for s in self.valves.INCLUDE_CONNECTIONS.split(",") if s.strip()]
        out = []
        for idx, url in enumerate(urls):
            cfg = configs.get(str(idx), configs.get(url, {})) or {}
            if not cfg.get("enable", True):
                continue
            if allow and not any(s in url for s in allow):
                continue
            if not urlparse(url).scheme:
                continue
            out.append(
                {
                    "base": url,
                    "key": keys[idx] if idx < len(keys) else "",
                    "prefix": cfg.get("prefix_id") or "",
                }
            )
        return out

    async def fetch_info(self, base: str, key: str) -> list[dict]:
        url = info_url(base, self.valves.INFO_PATH)
        headers = {"Accept": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        timeout = aiohttp.ClientTimeout(total=self.valves.REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status}")
                body = await resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not any(
            isinstance(r, dict) and "model_name" in r for r in data
        ):
            raise RuntimeError("not a LiteLLM /model/info document")
        return data

    async def apply(self, conn: dict, records: dict[str, dict]) -> int:
        from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models
        from open_webui.models.users import Users

        admin = await Users.get_super_admin_user()
        v = self.valves
        hide_modes = {m.strip() for m in v.HIDE_MODES.split(",") if m.strip()}
        written = 0
        for name, record in records.items():
            # Same id Open-WebUI gives the connection's model, so the config
            # row overrides that base model.
            mid = model_id(conn["prefix"], name)
            existing = await Models.get_model_by_id(mid)
            if existing and not v.ADOPT_EXISTING:
                managed = self.mine(existing.meta.model_dump())
                # A config nobody named (blank, or still the raw id) is
                # Open-WebUI's own bookkeeping, e.g. from toggling the model
                # off, not a customisation, so it is safe to adopt.
                unnamed = existing.name in ("", mid, name)
                if not managed and not unnamed:
                    log.info(
                        "LiteLLM Model Sync: leaving hand-edited config %s (%r) alone; "
                        "enable ADOPT_EXISTING to overwrite",
                        mid,
                        existing.name,
                    )
                    continue

            meta = existing.meta.model_dump() if existing else {}
            params = existing.params.model_dump() if existing else {}

            if v.SET_VISION:
                caps = dict(meta.get("capabilities") or {})
                caps["vision"] = record["capabilities"]["vision"]
                meta["capabilities"] = caps
            tags = desired_tags(record, v.TAG_VENDOR, v.TAG_FAMILY, v.TAG_CAPABILITIES)
            meta["tags"] = merge_tags(meta.get("tags"), meta.get("synced_tags") or [], tags)
            meta["synced_tags"] = tags
            meta["managed_by"] = self.owner
            meta["sync_source"] = conn["base"]
            hidden = record.get("mode") in hide_modes
            if hidden:
                # The "hide" toggle in the admin Models list: out of the
                # selector but still enabled and callable.
                meta["hidden"] = True
            if v.NATIVE_FUNCTION_CALLING and record["capabilities"]["tools"]:
                params["function_calling"] = "native"

            display = record["display_name"]
            # Hiding is enforced every sync; a visible model is left however a
            # person set it, so un-hiding by hand on a chat model sticks. Hidden
            # models stay enabled, which also repairs configs an earlier version
            # of this function disabled instead.
            active = True if hidden else (existing.is_active if existing else True)
            # Other grants (groups, users, write access) are kept as they are;
            # only the public read grant is added when it is missing.
            grants = [grant_dict(g) for g in (existing.access_grants if existing else [])]
            public = {"principal_type": "user", "principal_id": "*", "permission": "read"}
            grants_changed = False
            if v.PUBLIC_READ and public not in grants:
                grants.append(public)
                grants_changed = True

            if existing and not grants_changed and (
                existing.name == display
                and existing.is_active == active
                and existing.meta.model_dump() == meta
                and existing.params.model_dump() == params
            ):
                continue

            form = ModelForm(
                id=mid,
                base_model_id=None,
                name=display,
                meta=ModelMeta(**meta),
                params=ModelParams(**params),
                access_grants=grants,
                is_active=active,
            )
            if existing:
                await Models.update_model_by_id(mid, form)
            elif admin:
                await Models.insert_new_model(form, admin.id)
            else:
                log.warning("LiteLLM Model Sync: no admin user yet; cannot create %s", mid)
                continue
            written += 1
        return written
