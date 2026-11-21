"""Clear thinking tags on a real Open-WebUI: the scripted model stops while thinking."""

from __future__ import annotations

from conftest import URL

ASK = "[reasoning only] What is six times seven?"
THOUGHT = "Thinking it through, the answer is forty-two."


def ask(page) -> None:
    page.goto(f"{URL}/?models=screenshot-model")
    page.locator("#chat-input").click()
    page.keyboard.type(ASK)
    page.keyboard.press("Enter")


def toggle(api, active: bool) -> None:
    if api("GET", "/api/v1/functions/id/clear_thinking_tags")["is_active"] != active:
        api("POST", "/api/v1/functions/id/clear_thinking_tags/toggle")


def test_without_the_filter_the_reply_is_only_a_thought(user, api, shot):
    """By hand: with the filter off, have a model stop while thinking. The reply is a Thinking
    block and nothing else."""
    toggle(api, False)
    try:
        ask(user)
        user.get_by_text("Thought", exact=False).first.wait_for(timeout=60_000)
        user.wait_for_timeout(1000)
        shot(
            user,
            "clear_thinking_tags",
            "without",
            "Without the filter: the model stopped while thinking, and the reply is only its "
            "Thinking block.",
        )
    finally:
        toggle(api, True)


def test_with_the_filter_the_thought_is_the_answer(user, shot):
    """By hand: with the filter on, have a model stop while thinking. The thinking text is
    shown as the reply."""
    ask(user)
    user.get_by_text(THOUGHT).last.wait_for(timeout=60_000)
    user.wait_for_timeout(1000)
    shot(
        user,
        "clear_thinking_tags",
        "with",
        "With the filter: the same reply, and its thinking text is shown as the answer.",
        illustrates=["test_a_reply_that_ends_in_reasoning_gets_it_as_its_answer"],
    )
