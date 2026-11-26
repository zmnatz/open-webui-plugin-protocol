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


def new_page(browser):
    """A page in a context of its own, with no session."""
    context = browser.new_context(viewport=VIEWPORT, color_scheme="light")
    context.add_init_script(HIDE_TOASTS)
    return context.new_page()


def sign_in(browser, account: dict):
    """A page signed in on Open-WebUI's own login page, with the What's New dialog closed."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = new_page(browser)
    page.goto(url() + "/auth")
    page.fill("input[name=email]", account["email"])
    page.fill("input[name=password]", account["password"])
    page.keyboard.press("Enter")
    page.wait_for_url(url() + "/")
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
