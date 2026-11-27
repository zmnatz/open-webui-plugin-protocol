"""Dynamic Vision Router on the test harness: a message with an image is sent to the model
in the `vision_model_id` valve. Run with `owpp test vision_router`."""

import pytest

IMAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def chat(*parts, images=None) -> dict:
    message = {"role": "user", "content": [{"type": "text", "text": "What is this?"}, *parts]}
    if images:
        message["images"] = images
    return {"model": "chat-model", "messages": [message]}


@pytest.fixture
def bob(owui):
    return owui.add_user("Bob")


@pytest.fixture
def routed(owui, plugin):
    owui.set_valves("vision_router", vision_model_id="vision-model")
    return plugin


def test_a_message_with_an_image_goes_to_the_vision_model(routed, bob):
    """With `vision_model_id` set, a user's message with an image is sent to that model instead.

    By hand: set vision_model_id to a model that can see images, and choose another model in a
    chat as a user who is not an admin. Send a picture: the reply comes from the vision model.
    """
    body = routed.inlet(chat(IMAGE), user=bob, model="chat-model")
    assert body["model"] == "vision-model"


def test_images_attached_the_older_way_count_too(routed, bob):
    """An `images` list on the message counts as well as an `image_url` part.

    By hand: not repeatable on Open-WebUI 0.13, which sends images as `image_url` parts.
    """
    body = routed.inlet(chat(images=["data:image/png;base64,AAAA"]), user=bob, model="chat-model")
    assert body["model"] == "vision-model"


def test_a_message_without_an_image_stays_with_its_model(routed, bob):
    """Text alone is not rerouted.

    By hand: in the same chat, send text only. The chosen model answers.
    """
    assert routed.inlet(chat(), user=bob, model="chat-model")["model"] == "chat-model"


def test_without_a_vision_model_nothing_is_rerouted(plugin, bob):
    """`vision_model_id` is empty by default, and then nothing changes.

    By hand: clear vision_model_id and send a picture. The chosen model answers.
    """
    assert plugin.inlet(chat(IMAGE), user=bob, model="chat-model")["model"] == "chat-model"


def test_admins_are_left_alone_unless_it_is_turned_on_for_them(owui, routed):
    """By default only users who are not admins are rerouted; `enabled_for_admins` turns it on
    for admins, and `enabled_for_users` off for everyone else.

    By hand: send a picture as an admin. The chosen model answers. Turn enabled_for_admins on
    and send it again: the vision model answers.
    """
    ada = owui.add_user("Ada", role="admin")
    assert routed.inlet(chat(IMAGE), user=ada, model="chat-model")["model"] == "chat-model"
    owui.set_valves("vision_router", enabled_for_admins=True, enabled_for_users=False)
    assert routed.inlet(chat(IMAGE), user=ada, model="chat-model")["model"] == "vision-model"
    bob = owui.add_user("Bob")
    assert routed.inlet(chat(IMAGE), user=bob, model="chat-model")["model"] == "chat-model"


def test_some_models_are_never_rerouted(owui, routed, bob):
    """Models in `skip_reroute_models`, and the vision model itself, keep their messages.

    By hand: add the chosen model to skip_reroute_models and send a picture. It answers.
    """
    assert routed.inlet(chat(IMAGE), user=bob, model="vision-model")["model"] == "chat-model"
    owui.set_valves("vision_router", skip_reroute_models=["chat-model"])
    assert routed.inlet(chat(IMAGE), user=bob, model="chat-model")["model"] == "chat-model"


def test_it_can_say_where_the_message_went(owui, routed, bob):
    """With `status` on, the chat shows a status line naming the vision model.

    By hand: turn status on and send a picture. "Request routed to <model>" shows above the
    reply.
    """
    owui.set_valves("vision_router", status=True)
    routed.inlet(chat(IMAGE), user=bob, model="chat-model")
    assert [event for _, event in owui.chat_events] == [
        {"type": "status", "data": {"description": "Request routed to vision-model", "done": True}}
    ]
