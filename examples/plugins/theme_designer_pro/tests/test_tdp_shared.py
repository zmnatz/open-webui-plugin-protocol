"""The code the function and the Launcher share (shared.py): the signed link a theme travels in,
and filling a template's placeholders. Tested directly, with no Open-WebUI. Run with `owpp test
theme_designer_pro`."""

import pytest

from owpp.testing import plugin_source


@pytest.fixture
def shared(owui, plugin_dir):  # owui: the function imports open_webui
    return plugin_source(plugin_dir).shared


def test_a_placeholder_is_filled_once(shared):
    """Each `__NAME__` is filled in one pass: a value that holds a placeholder's text is left as
    it is, and a name with no value stays.

    By hand: not repeatable by hand; the Launcher's frame shows a Designer Url as it was typed.
    """
    template = "<a href='__URL__'>__HEIGHT__px __OTHER__</a>"
    assert shared._fill(template, {"URL": "/x?__HEIGHT__", "HEIGHT": 600}) == "<a href='/x?__HEIGHT__'>600px __OTHER__</a>"


def test_a_link_opens_only_as_signed(shared):
    """A link opens with the key it was signed with and as it was signed: another key, a
    changed payload, another prefix, text that is not ASCII, or no key at all is no link.

    By hand: edit one character of a card's Apply link and open it: the designer opens without
    applying the theme.
    """
    key = b"secret"
    token = shared._sign_token(key, shared.THEME_TOKEN_PREFIX, {"u": "ada", "h": "0" * 64})
    assert shared._open_token(key, token) == (shared.THEME_TOKEN_PREFIX, {"u": "ada", "h": "0" * 64})
    body, sig = token[len(shared.THEME_TOKEN_PREFIX):].split(".")
    for bad in (
        token[:-1] + ("A" if token[-1] != "A" else "B"),
        shared.THEME_TOKEN_PREFIX + body[:-2] + "xx." + sig,
        "tdp-apply.v9." + body + "." + sig,
        token + "é",
        "",
        None,
    ):
        assert shared._open_token(key, bad) is None
    assert shared._open_token(b"other", token) is None and shared._open_token(None, token) is None
    not_an_object = shared._sign_token(key, shared.APPLY_TOKEN_PREFIX, {})
    assert shared._open_token(key, not_an_object.replace(not_an_object.split(".")[2], "W10")) is None


def test_the_launcher_and_the_function_speak_the_same_link(owui, plugin_dir):
    """The Launcher and the function take the format from the one shared.py, each in its own
    copy, so a link one signs is a link the other opens.

    By hand: a card's Apply works (it opens the designer with the theme applied).
    """
    src = plugin_source(plugin_dir)
    token = src.tool_shared._sign_token(b"k", src.tool_shared.THEME_TOKEN_PREFIX, {"u": "ada"})
    assert src.shared._open_token(b"k", token) == (src.shared.THEME_TOKEN_PREFIX, {"u": "ada"})
