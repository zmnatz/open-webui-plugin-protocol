# Generated from the mock Open-WebUI (owpp.testing.stubs): do not edit.

from typing import Any


async def get_function_module_from_cache(request: Any, function_id: Any, load_from_db: Any = ...) -> Any: ...


def get_functions_cache(request: Any) -> Any: ...


async def load_function_module_by_id(function_id: Any, content: Any = ...) -> Any: ...


async def load_tool_module_by_id(tool_id: Any, content: Any = ...) -> Any: ...


def replace_imports(content: Any) -> Any: ...
