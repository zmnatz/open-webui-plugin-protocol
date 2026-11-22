"""The built-in libraries, for plugins to import: `from owpp.lib import PluginAssets, plugin_config`.

A plugin's files import from here so an editor and tests can resolve the names. The bundler
removes the import and inlines each library the plugin uses, so a deployed plugin does not need
owpp. Which library a name comes from decides what the plugin must `include:` (docs/libraries.md).
tests/test_libraries.py checks this list against the libraries.

live_reload imports open_webui at its top (it is Classic298's, kept unchanged), so its names are
loaded on first use rather than with this module.
"""

from typing import TYPE_CHECKING

from .libraries import LIB_DIR, public_names
from .runtime.lib.plugin_assets import (  # assets
    PluginAssets,
    plugin_assets_register,
    register,
)
from .runtime.lib.plugin_chat_data import (  # chat_data
    ChatNotSaved,
    plugin_chat_is_temp,
    plugin_chat_read,
    plugin_chat_update,
    plugin_chat_write,
)
from .runtime.lib.plugin_config import (  # config
    plugin_config,
)
from .runtime.lib.plugin_core import (  # core
    plugin_app,
    plugin_env,
    plugin_function_id,
    plugin_is_active,
    plugin_stored_valves,
)
from .runtime.lib.plugin_events import (  # events
    PluginEvents,
    on,
)
from .runtime.lib.plugin_jobs import (  # jobs
    PluginScheduledSync,
    plugin_claim,
    plugin_every,
    plugin_spawn,
    plugin_stop_jobs,
    plugin_sync_markers,
    plugin_unclaim,
)
from .runtime.lib.plugin_routes import (  # routes
    PluginAdmin,
    PluginUser,
    ReadableChat,
    WritableChat,
    plugin_chat_guard,
    plugin_check_token,
    plugin_guard,
    plugin_mount,
    plugin_require_active,
    plugin_token,
    plugin_user,
)
from .runtime.lib.plugin_static import (  # static
    plugin_static_ensure,
    plugin_static_files,
    plugin_static_serve,
)
from .runtime.lib.plugin_templates import (  # templates
    plugin_template_bytes,
    plugin_template_files,
    plugin_template_text,
)
from .runtime.lib.shared_assets import (  # shared_assets
    ASSET_IMPL_ATTR,
    ASSET_IMPL_VERSION,
    ASSET_KEY,
    ASSET_REGISTRY_ATTR,
    ASSET_ROUTE_ATTR,
    CUSTOM_CSS_PATH,
    LOADER_PATH,
    SHARED_ASSET_TYPES,
    asset_compose,
    asset_fragments,
    asset_register,
    asset_sort_key,
    asset_strip_block,
    asset_withdraw_deleted,
)
from .runtime.plugin_runtime import (  # runtime
    plugin_ensure,
)

if TYPE_CHECKING:
    from .runtime.lib.live_reload import (  # live_reload
        RELOAD_EXEC_ID,
        RELOAD_FUNCTION_ID,
        RELOAD_IMPL_VERSION,
        RELOAD_STATE_ATTR,
        reload_active,
        reload_bootstrap,
        reload_channel,
        reload_ensure_listener,
        reload_log,
        reload_mark_loaded,
        reload_on_event,
        reload_publish,
        reload_state,
        reload_tasks,
    )

# Read from the file, so a new upstream name needs no edit here (only the TYPE_CHECKING list, for
# editors, which tests/test_libraries.py checks).
_LIVE_RELOAD = frozenset(public_names(LIB_DIR / "live_reload.py"))


def __getattr__(name: str):
    if name in _LIVE_RELOAD:
        from .runtime.lib import live_reload

        return getattr(live_reload, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ASSET_IMPL_ATTR",
    "ASSET_IMPL_VERSION",
    "ASSET_KEY",
    "ASSET_REGISTRY_ATTR",
    "ASSET_ROUTE_ATTR",
    "CUSTOM_CSS_PATH",
    "LOADER_PATH",
    "RELOAD_EXEC_ID",
    "RELOAD_FUNCTION_ID",
    "RELOAD_IMPL_VERSION",
    "RELOAD_STATE_ATTR",
    "SHARED_ASSET_TYPES",
    "ChatNotSaved",
    "PluginAdmin",
    "PluginAssets",
    "PluginEvents",
    "PluginScheduledSync",
    "PluginUser",
    "ReadableChat",
    "WritableChat",
    "asset_compose",
    "asset_fragments",
    "asset_register",
    "asset_sort_key",
    "asset_strip_block",
    "asset_withdraw_deleted",
    "on",
    "plugin_app",
    "plugin_assets_register",
    "plugin_chat_guard",
    "plugin_chat_is_temp",
    "plugin_chat_read",
    "plugin_chat_update",
    "plugin_chat_write",
    "plugin_check_token",
    "plugin_claim",
    "plugin_config",
    "plugin_ensure",
    "plugin_env",
    "plugin_every",
    "plugin_function_id",
    "plugin_guard",
    "plugin_is_active",
    "plugin_mount",
    "plugin_require_active",
    "plugin_spawn",
    "plugin_static_ensure",
    "plugin_static_files",
    "plugin_static_serve",
    "plugin_stop_jobs",
    "plugin_stored_valves",
    "plugin_sync_markers",
    "plugin_template_bytes",
    "plugin_template_files",
    "plugin_template_text",
    "plugin_token",
    "plugin_unclaim",
    "plugin_user",
    "register",
    "reload_active",
    "reload_bootstrap",
    "reload_channel",
    "reload_ensure_listener",
    "reload_log",
    "reload_mark_loaded",
    "reload_on_event",
    "reload_publish",
    "reload_state",
    "reload_tasks",
]
