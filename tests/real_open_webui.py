"""The real Open-WebUI (the test harness), behind the same `Fetch` port and with the same
interface as FakeOpenWebUI (fake_open_webui.py): the deploy and `owpp import --instance` tests
run against it, so what they assert is what Open-WebUI does.

FakeOpenWebUI stays for what the real Open-WebUI cannot give on demand: other sign-in methods
(LDAP, OIDC, a trusted header), an instance that is still starting, a delete that fails.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fake_open_webui import INSTANCE_FIELDS, Target

from owpp.bundle import function_type
from owpp.deploy import Choices, Instance
from owpp.openwebui import HttpResponse


class RealOpenWebUI:
    """An open Harness, as deploy and import are given an Open-WebUI.

    `calls` lists each call ("METHOD /path") but /health, as FakeOpenWebUI does: a functions
    call only once it got past the credential check. `state` is the functions by id, read from
    Open-WebUI. `live` are functions that are there before the test (a hand-made one, an
    earlier deploy), stored with Open-WebUI's model as they would be in its database.
    """

    def __init__(self, owui, live=(), valves=None):
        self.owui = owui
        self.base_url = "http://testserver"
        self.calls: list[str] = []
        for f in live:
            self._store(f)
        for function_id, values in (valves or {}).items():
            from open_webui.models.functions import Functions

            owui.run(Functions.update_function_valves_by_id(function_id, values))

    def _store(self, f: dict) -> None:
        from open_webui.models.functions import FunctionForm, FunctionMeta, Functions

        content = f.get("content", "")
        kind = f.get("type") or (function_type(content) or ["filter"])[0]
        form = FunctionForm(
            id=f["id"],
            name=f.get("name", f["id"]),
            content=content,
            meta=FunctionMeta(**(f.get("meta") or {})),
        )
        self.owui.run(Functions.insert_new_function(self.owui.admin.id, kind, form))
        changes = {k: f[k] for k in ("is_active", "is_global") if k in f}
        if changes:
            self.owui.run(Functions.update_function_by_id(f["id"], changes))

    # ---- as deploy and import are given it

    def instance(self, **kwargs) -> Instance:
        """This Open-WebUI, signed in as its admin unless told otherwise."""
        kwargs.setdefault("api_key", self.owui.admin.token)
        return Instance(base_url=self.base_url, fetch=self, **kwargs)

    def options(self, directory: Path, **kwargs) -> Target:
        connection = {k: kwargs.pop(k) for k in list(kwargs) if k in INSTANCE_FIELDS}
        return Target(self.instance(**connection), Choices(dir=Path(directory), **kwargs))

    # ---- the Fetch port

    def __call__(self, method, url, headers=None, body=None) -> HttpResponse:
        path = urlsplit(url).path
        res = self.owui._fetch(method, url, headers, body)
        refused = res.status == 401 and not path.startswith("/api/v1/auths/")
        if path != "/health" and not refused:
            self.calls.append(f"{method} {path}")
        return res

    # ---- what it holds

    @property
    def state(self) -> dict[str, dict]:
        """Each function, as Open-WebUI returns it with its code (GET /functions/id/<id>)."""
        return {i: row.model_dump() for i, row in self.owui.functions.items()}

    @property
    def valves(self) -> dict[str, dict]:
        return self.owui.function_valves
