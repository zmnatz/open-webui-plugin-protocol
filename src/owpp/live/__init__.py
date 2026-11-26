"""`owpp live`, and the fixtures for tests on a real Open-WebUI with aimock as its models
(docs/commands/live.md). The browser fixtures need Playwright: install `owpp[live]`.

    from owpp.live import send, url

`send(page, text)` chats on a Playwright page; `url()` is Open-WebUI's address. The fixtures
(`api`, `user_api`, `aimock`, `admin`, `user`, `signed_out`, in owpp.live.fixtures) need no
import: `owpp live` loads them into its pytest run through PYTEST_PLUGINS.
"""

from .client import Aimock, Api, aimock_url, url
from .pages import send, sign_in

__all__ = ["Aimock", "Api", "aimock_url", "send", "sign_in", "url"]
