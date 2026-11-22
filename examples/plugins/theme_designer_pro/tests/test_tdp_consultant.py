"""Theme Designer Pro's AI Consultant: a description in words, a model on the instance, a palette
back. Run with `owpp test theme_designer_pro`.

The mock's model answers `owui.model_reply` and keeps what it was asked in `owui.completions`."""

import pytest

URL = "/api/v1/theme-designer/consult"


@pytest.fixture
def model(owui):
    """A model "theme-model" on the instance, answering with a palette."""
    owui.model_reply = '{"hue": 210, "chroma": 18, "lightness": 14, "gradient": true, "name": "Deep  Harbour"}'
    owui.app.state.MODELS = {"theme-model": {"id": "theme-model"}}
    return owui


def test_the_consultant_turns_a_description_into_a_palette(td, model):
    """The consultant asks the model named by `ai_consultant_model` for a palette and answers
    it range-checked, with the model's name.

    By hand: set AI Consultant Model to a model's id. In the designer, open the AI Consultant,
    describe "a calm harbour at night" and press Generate: the palette changes to it.
    """
    td.valves(ai_consultant_model="theme-model")
    response = td.admin.post(URL, json={"description": "a calm harbour   at night"})
    assert response.json() == {
        "hue": 210, "chroma": 18, "lightness": 14, "gradient": True, "name": "Deep Harbour", "model": "theme-model",
    }
    (asked,) = model.completions
    assert asked["model"] == "theme-model" and asked["metadata"] == {"task": "theme_designer_pro_consultant"}
    assert asked["messages"][1] == {"role": "user", "content": "a calm harbour at night"}
    assert asked["messages"][0]["content"].startswith("You design color themes for Open WebUI.")


def test_without_a_model_to_ask_the_consultant_says_where_to_set_one(td, model):
    """With no AI Consultant Model and no task model, or one the instance does not have, the
    consultant says where to set one.

    By hand: leave AI Consultant Model empty with no task model under Admin Settings >
    Interface, and press Generate: the designer shows where to set one.
    """
    assert td.admin.post(URL, json={"description": "x"}).status_code == 409
    td.valves(ai_consultant_model="not-here", allow_personal_themes=True)
    assert td.user.post(URL, json={"description": "y"}).status_code == 409  # a second person: no wait


def test_with_no_model_set_the_task_model_is_asked(owui, td, model, monkeypatch):
    """Empty AI Consultant Model asks Open-WebUI's task model, with its task parameters, as
    Open-WebUI's own background tasks do.

    By hand: set a task model under Admin Settings > Interface and leave AI Consultant Model
    empty: Generate works.
    """
    import open_webui.routers.tasks as tasks

    async def config(base, models):
        return base, {"temperature": 0}

    monkeypatch.setattr(tasks, "get_task_model_generation_config", config, raising=False)
    monkeypatch.setattr(tasks, "apply_task_model_params", lambda p, m, i, params: {**p, **params}, raising=False)
    owui.config["task.model.default"] = "theme-model"
    assert td.admin.post(URL, json={"description": "warm"}).json()["model"] == "theme-model"
    assert model.completions[-1]["temperature"] == 0


def test_one_person_asks_at_most_every_few_seconds(td, model):
    """One person's requests are `consult_interval_seconds` apart (config.yaml, 3 by default),
    counted on every worker: a second one sooner is refused.

    By hand: press Generate twice quickly: the second says "Wait a few seconds between
    requests".
    """
    td.valves(ai_consultant_model="theme-model")
    assert td.admin.post(URL, json={"description": "a"}).status_code == 200
    again = td.admin.post(URL, json={"description": "b"})
    assert (again.status_code, again.json()) == (429, {"error": "Wait a few seconds between requests"})


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ('<think>{"hue": 1}</think>{"hue": 999, "chroma": -4, "lightness": 70, "gradient": "true"}', 200),
        ("I would pick a blue.", 502),
        ('{"hue": "blue", "chroma": 3, "lightness": 9}', 502),
    ],
)
def test_the_models_answer_is_checked(td, model, text, status):
    """The model's answer is read past any thinking, clamped to the designer's ranges, and an
    answer with no palette in it is a 502 the designer shows.

    By hand: not repeatable on purpose; with a weak model, an odd answer shows "The model's
    answer had no theme in it".
    """
    td.valves(ai_consultant_model="theme-model")
    model.model_reply = text
    response = td.admin.post(URL, json={"description": "x"})
    assert response.status_code == status
    if status == 200:
        assert {k: response.json()[k] for k in ("hue", "chroma", "lightness", "gradient")} == {
            "hue": 360, "chroma": 0, "lightness": 50, "gradient": True,
        }


def test_a_model_that_fails_is_a_502(td, model, monkeypatch):
    """A model that errors is a 502, and a pipeline filter that refuses is a 400.

    By hand: point AI Consultant Model at a model whose connection is down: Generate says "The
    model could not answer".
    """
    import open_webui.routers.pipelines as pipelines
    import open_webui.utils.chat as chat

    td.valves(ai_consultant_model="theme-model")

    async def broken(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(chat, "generate_chat_completion", broken, raising=False)
    assert td.admin.post(URL, json={"description": "a"}).status_code == 502
    monkeypatch.setattr(pipelines, "process_pipeline_inlet_filter", broken, raising=False)
    td.valves(allow_personal_themes=True)  # someone else asks, past the first one's wait
    assert td.user.post(URL, json={"description": "b"}).status_code == 400


def test_the_consultant_can_be_turned_off(td, model):
    """With `enable_ai_consultant` off nobody can ask, admins included.

    By hand: turn Enable Ai Consultant off: the designer has no AI Consultant.
    """
    td.valves(enable_ai_consultant=False)
    assert td.admin.post(URL, json={"description": "x"}).json() == {"error": "The AI Consultant is turned off"}


def test_users_ask_only_when_they_can_have_a_personal_theme(td, model):
    """Users design only their own themes, so they ask only while personal themes are on;
    signed out, nobody asks; an empty description asks nothing.

    By hand: with Allow Personal Themes on, a user's Themes tab has the AI Consultant.
    """
    td.valves(ai_consultant_model="theme-model")
    assert td.user.post(URL, json={"description": "x"}).json() == {"error": "Access denied"}
    assert td.anon.post(URL, json={"description": "x"}).status_code == 401
    td.valves(allow_personal_themes=True)
    assert td.user.post(URL, json={"description": "   "}).status_code == 400
    assert td.user.post(URL, json={"description": "x"}).status_code == 200
    assert td.user.post(URL, content=b"x" * 70000, headers={"content-type": "application/json"}).status_code == 413
