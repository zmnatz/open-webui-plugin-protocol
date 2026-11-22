# Generated from the mock Open-WebUI (owpp.testing.stubs): do not edit.

from typing import Any


class AccessGrants:
    @staticmethod
    async def set_access_grants(resource_type: Any, resource_id: Any, access_grants: Any, db: Any = ...) -> Any: ...
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


PRINCIPAL_TYPE_ANYONE: str


PRINCIPAL_TYPE_GROUP: str


PRINCIPAL_TYPE_USER: str


WILDCARD_PRINCIPAL_ID: str
