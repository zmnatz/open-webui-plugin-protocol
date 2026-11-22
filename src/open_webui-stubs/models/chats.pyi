# Generated from the mock Open-WebUI (owpp.testing.stubs): do not edit.

from typing import Any


class Chat:
    id: Any
    user_id: Any
    title: Any
    chat: Any
    created_at: Any
    updated_at: Any
    share_id: Any
    archived: Any
    pinned: Any
    meta: Any
    folder_id: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


class ChatFile:
    id: Any
    user_id: Any
    chat_id: Any
    message_id: Any
    file_id: Any
    created_at: Any
    updated_at: Any
    def __init__(self, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...


class Chats:
    @staticmethod
    async def get_chat_by_id(id: Any) -> Any: ...
    @staticmethod
    async def get_chats(skip: Any = ..., limit: Any = ...) -> Any: ...
    @staticmethod
    async def get_chats_by_user_id(user_id: Any, skip: Any = ..., limit: Any = ...) -> Any: ...
    @staticmethod
    async def has_chat_access(chat_id: Any, user: Any, permission: Any = ...) -> Any: ...
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getattr__(self, name: str) -> Any: ...
