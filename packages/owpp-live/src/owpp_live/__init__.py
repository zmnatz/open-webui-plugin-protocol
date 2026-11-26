"""owpp-live: `owpp live`, and the fixtures for tests on a real Open-WebUI with aimock as its
models. Released together with owpp, at the same version.

    from owpp_live import send, url

`send(page, text)` chats on a Playwright page; `url()` is Open-WebUI's address. The fixtures
(`api`, `user_api`, `aimock`, `admin`, `user`, `signed_out`) need no import.
"""

from .client import Aimock, Api, aimock_url, url
from .pages import send, sign_in

__version__ = "0.6.3"

__all__ = ["Aimock", "Api", "aimock_url", "send", "sign_in", "url"]
