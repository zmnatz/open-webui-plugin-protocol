"""Clear thinking tags on the test harness: a reply that ends in reasoning with no answer
after it gets that reasoning as its answer. Run with `owpp test clear_thinking_tags`."""


def reasoning(text: str) -> dict:
    return {"type": "reasoning", "id": "r1", "content": [{"type": "output_text", "text": text}]}


def answer(text: str) -> dict:
    return {
        "type": "message",
        "id": "m1",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def reply(**assistant) -> dict:
    return {"messages": [{"role": "user", "content": "Hi"}, {"role": "assistant", **assistant}]}


def test_a_reply_that_ends_in_reasoning_gets_it_as_its_answer(plugin):
    """In Open-WebUI 0.12+ a reply is a list of `output` items, and the chat shows what that list
    holds. When it ends in reasoning with no answer after it, the reasoning becomes the answer,
    in `output` and in `content`.

    By hand: with a model that sometimes stops while thinking, ask it something until a reply
    has a closed Thinking block and nothing after it. With this filter on, the thinking text is
    shown as the reply instead.
    """
    body = plugin.outlet(reply(content="", output=[reasoning("The answer is 42.</think>")]))
    last = body["messages"][-1]
    assert last["output"] == [
        {
            "type": "message",
            "id": "r1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "The answer is 42."}],
        }
    ]
    assert last["content"] == "The answer is 42."


def test_a_reply_with_an_answer_after_its_reasoning_is_left_alone(plugin):
    """Reasoning followed by an answer is the normal case, and nothing changes.

    By hand: ask a thinking model something. The reply shows the Thinking block and the answer,
    as without the filter.
    """
    output = [reasoning("Let me see."), answer("42.")]
    body = plugin.outlet(reply(content="42.", output=output))
    assert body["messages"][-1]["output"] == output


def test_an_empty_answer_after_the_reasoning_does_not_count_as_one(plugin):
    """An empty message item after the reasoning is skipped over: the reasoning still becomes
    the answer.

    By hand: not repeatable on purpose; it depends on how the model streamed its reply.
    """
    body = plugin.outlet(reply(content="", output=[reasoning("42."), answer("")]))
    assert body["messages"][-1]["content"] == "42."
    assert [item["type"] for item in body["messages"][-1]["output"]] == ["message"]


def test_an_older_reply_with_an_unfinished_thinking_block_gets_its_text(plugin):
    """Before 0.12 the reasoning was a `<details type="reasoning" done="false">` block in the
    reply's text. When it was never closed, its text, unquoted, replaces it.

    By hand: not repeatable on Open-WebUI 0.13, which no longer writes replies this way.
    """
    content = (
        "Before.\n"
        '<details type="reasoning" done="false">\n'
        "<summary>Thinking…</summary>\n"
        "> The answer\n> is 42."
    )
    body = plugin.outlet(reply(content=content))
    assert body["messages"][-1]["content"] == "Before.\n\nThe answer\nis 42."


def test_a_reply_from_the_user_or_no_messages_changes_nothing(plugin):
    """Only the last message counts, and only when the assistant wrote it.

    By hand: not needed; a chat always ends with the assistant's reply when outlets run.
    """
    user_last = {"messages": [{"role": "user", "content": "Hi"}]}
    assert plugin.outlet(user_last) == user_last
    assert plugin.outlet({"messages": []}) == {"messages": []}
    assert plugin.outlet({}) == {}
