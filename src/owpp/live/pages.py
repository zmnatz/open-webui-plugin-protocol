"""Playwright pages on the live Open-WebUI: signing in on its own login page, and chatting."""

from __future__ import annotations

import contextlib

from .client import url

VIEWPORT = {"width": 1280, "height": 800}
PAGES = ("admin", "user", "signed_out")

# Hide the toasts ("You're now logged in.") that would otherwise sit on top of every page.
HIDE_TOASTS = """
document.addEventListener("DOMContentLoaded", () => {
  const style = document.createElement("style");
  style.textContent = "[data-sonner-toaster] { display: none !important; }";
  document.head.appendChild(style);
});
"""


def new_page(browser, storage_state: dict | None = None):
    """A page in a context of its own: with no session, or with a saved one."""
    context = browser.new_context(
        viewport=VIEWPORT, color_scheme="light", storage_state=storage_state
    )
    context.add_init_script(HIDE_TOASTS)
    return context.new_page()


def signed_in_state(browser, account: dict) -> dict:
    """Sign in once on Open-WebUI's own login page, and keep the session (its cookie and
    the token in localStorage). Open-WebUI limits sign-ins (429 after a few a minute), so
    each page starts from this instead of signing in again."""
    page = sign_in(browser, account)
    try:
        return page.context.storage_state()
    finally:
        page.context.close()


def sign_in(browser, account: dict, storage_state: dict | None = None):
    """A page signed in as `account`, at Open-WebUI's home, with the What's New dialog
    closed: through the login page, or from a session `signed_in_state` saved."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = new_page(browser, storage_state)
    if storage_state is None:
        page.goto(url() + "/auth")
        page.fill("input[name=email]", account["email"])
        page.fill("input[name=password]", account["password"])
        page.keyboard.press("Enter")
        page.wait_for_url(url() + "/")
    else:
        page.goto(url() + "/")
    with contextlib.suppress(PlaywrightTimeout):
        page.get_by_text("Okay, Let's Go!").click(timeout=5000)
    return page


def send(page, text: str) -> None:
    """Type a message into the chat input and send it. Since v0.13.5 the input takes typing
    while the models and tools are still loading, and can be redrawn once they arrive, losing
    what was typed so far: so check the input holds the whole message before pressing Enter,
    and type it again when it does not. The input turns ' into a curly ’, so leave apostrophes
    out of `text`."""
    chat_input = page.locator("#chat-input")
    for _ in range(5):
        chat_input.click()
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(text)
        page.wait_for_timeout(300)
        if chat_input.inner_text().strip() == text:
            page.keyboard.press("Enter")
            return
    raise AssertionError(f"the chat input never held {text!r}: {chat_input.inner_text()!r}")
