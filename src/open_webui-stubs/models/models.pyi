# Generated from the mock Open-WebUI (owpp.testing.stubs): do not edit.

from typing import Any


class ModelForm:
    id: Any
    base_model_id: Any
    name: Any
    meta: Any
    params: Any
    access_grants: Any
    is_active: Any
    model_config: Any
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


class ModelMeta:
    profile_image_url: Any
    background_image_url: Any
    description: Any
    i18n: Any
    capabilities: Any
    knowledge: Any
    subagents: Any
    voice: Any
    voice_avatar: Any
    model_config: Any
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


class ModelParams:
    model_controls: Any
    model_config: Any
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


class Models:
    @staticmethod
    async def get_all_models() -> Any: ...
    @staticmethod
    async def get_model_by_id(id: Any) -> Any: ...
    @staticmethod
    async def insert_new_model(form_data: Any, user_id: Any) -> Any: ...
    @staticmethod
    async def update_model_by_id(id: Any, model: Any, user_id: Any = ...) -> Any: ...
    @staticmethod
    async def delete_model_by_id(id: Any) -> Any: ...
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
