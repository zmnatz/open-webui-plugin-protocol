"""The Theme Designer Pro Launcher, the tool the function installs: it opens the designer in a chat,
and builds a theme someone describes as a card they can apply. Run with `owpp test
theme_designer_pro`."""

import json
import re
import time

import pytest

TOOL = "theme_designer_pro_launcher"
BASE = "/api/v1/theme-designer"


@pytest.fixture
def launcher(owui, td):
    return owui.tool(TOOL)


def body(response) -> str:
    return response.body.decode()


def card_data(card) -> dict:
    found = re.search(
        r'<script id="tdp-data" type="application/json">(.*?)</script>', body(card), re.S
    )
    return json.loads(found.group(1))


def tool_valves(owui, **valves):
    owui.tool_valves[TOOL] = {**owui.tool_valves.get(TOOL, {}), **valves}
    return owui.tool(TOOL)


def test_the_launcher_opens_the_designer_in_the_chat(owui, td, launcher):
    """Asked for the designer, the Launcher shows it in the chat: the instance theme for an
    admin (their own with my_theme), always their own for a user, with a Pop out link.

    By hand: ask "open theme designer" in a chat with the Launcher on: the designer opens under
    the reply.
    """
    frame, said = launcher.call("open_theme_designer", user=owui.admin)
    assert f'src="{BASE}"' in body(frame) and f'href="{BASE}"' in body(frame)
    assert frame.headers["content-disposition"] == "inline"
    assert said == "The designer is open in the chat, on the instance theme every user sees."
    frame, _ = launcher.call("open_theme_designer", user=owui.admin, my_theme=True)
    assert f'src="{BASE}?scope=me"' in body(frame)
    frame, said = launcher.call("open_theme_designer", user=td.ada)
    assert f'src="{BASE}?scope=me"' in body(frame) and "personal theme" in said


def test_the_frame_follows_its_height_and_scale_valves(owui, td):
    """`iframe_height` sets the frame's height and `iframe_scale` shrinks the designer inside
    it to fit more.

    By hand: set the Launcher's Iframe Scale to 0.5 and open the designer in a chat: it shows at
    half size, filling the frame.
    """
    frame, _ = tool_valves(owui, iframe_height=600, iframe_scale=0.5).call(
        "open_theme_designer", user=owui.admin
    )
    html = body(frame)
    assert "height: 600px;" in html and "width: 200.0%;" in html and "height: 1200px;" in html
    assert "transform: scale(0.5);" in html


def test_the_launcher_opens_the_designer_where_the_function_serves_it(owui, td):
    """The Launcher's `designer_url` must match the function's: it is where the frame points.

    By hand: after changing the function's Designer Url, set the Launcher's to the same; the
    designer opens in chats again.
    """
    frame, _ = tool_valves(owui, designer_url="/api/v1/my-themes/").call(
        "open_theme_designer", user=owui.admin
    )
    assert 'src="/api/v1/my-themes"' in body(frame)


def test_a_described_theme_comes_back_as_a_card_that_applies_it(owui, td, launcher):
    """A theme someone describes comes back as a card with its preview and an Apply link
    signed for them alone: the designer applies it for that person, and nobody else.

    By hand: as a user with Allow Personal Themes on, ask "make my chat a deep teal lagoon". A
    card shows the theme; Apply puts it on your theme only.
    """
    td.valves(allow_personal_themes=True)
    card, said = launcher.call(
        "create_theme",
        user=td.ada,
        name="Teal   Lagoon",
        hue=180,
        chroma=22,
        gradient_colors="#001122,#114455",
    )
    data = card_data(card)
    assert data["name"] == "Teal Lagoon" and data["subtitle"] == "Your theme · gradient · glass"
    assert said.startswith(
        'Built "Teal Lagoon" and frosted glass panels, for the user\'s own theme.'
    )
    theme = json.loads(data["theme"])
    assert theme["dark"]["gradientStops"][0]["color"] == "#001122"
    token = re.search(r"apply=([^&\"]+)", data["applyUrl"]).group(1)
    config = td.config(td.user, f"?scope=me&apply={token}")
    assert config["applyOnLoad"] == {"kind": "theme", "sha": data["sha"], "mode": "all"}
    td.valves(allow_personal_themes=True)
    assert td.config(td.admin, f"?scope=me&apply={token}")["applyOnLoad"] is None


def test_only_an_admin_builds_a_theme_for_everyone(owui, td, launcher):
    """`everyone` builds the instance theme, for an admin only; a user's is always their own.

    By hand: as an admin, ask "a copper theme for everyone": the card says Instance theme.
    """
    card, _ = launcher.call(
        "create_theme",
        user=owui.admin,
        name="Copper",
        hue=25,
        chroma=30,
        everyone=True,
        mode="dark",
    )
    assert (
        card_data(card)["subtitle"].startswith("Instance theme")
        and card_data(card)["mode"] == "dark"
    )
    assert "scope=me" not in card_data(card)["applyUrl"]
    card, _ = launcher.call(
        "create_theme", user=td.ada, name="Copper", hue=25, chroma=30, everyone=True
    )
    assert card_data(card)["subtitle"].startswith("Your theme")


def test_css_the_model_wrote_is_checked_first(owui, td, launcher):
    """CSS the model writes may not load anything; with `model_written_css` off it may not
    write any.

    By hand: not repeatable on purpose; the model reads the reason and calls again.
    """
    said = launcher.call(
        "create_theme", user=td.ada, name="X", hue=1, chroma=1, custom_css="@import url(x.css);"
    )
    assert said.startswith("Not built: the custom_css can't be used because")
    tool = tool_valves(owui, model_written_css=False)
    said = tool.call(
        "create_theme", user=td.ada, name="X", hue=1, chroma=1, custom_css="a{color:red}"
    )
    assert (
        said == "Not built: an admin turned off CSS the chat model writes. Leave custom_css empty."
    )


def test_an_animation_the_model_wrote_runs_isolated_and_is_checked_first(owui, td, launcher):
    """An animation the model writes may not reach the network or the page, and runs isolated;
    with `model_written_animations` off the model may not write one.

    By hand: ask "an animated background of drifting paper lanterns": the card's preview runs the
    new animation, marked (new).
    """
    said = launcher.call(
        "create_theme",
        user=td.ada,
        name="X",
        hue=1,
        chroma=1,
        animation_code="fetch('/api/v1/chats')",
    )
    assert said.startswith("Not built: the animation_code can't be used because")
    tool = tool_valves(owui, model_written_animations=False)
    said = tool.call(
        "create_theme", user=td.ada, name="X", hue=1, chroma=1, animation_code="draw()"
    )
    assert said.startswith("Not built: an admin turned off animations the chat model writes.")


def test_a_catalog_animation_is_picked_by_the_words_asked_for(owui, td, launcher):
    """A background described in words is the closest animation of the catalog at
    `canvas_catalog_url`; with `background_animations` off the theme has none.

    By hand: ask "make my chat a koi pond": the card's preview shows the Koi Pond animation.
    Turn Background Animations off and ask again: a gradient instead.
    """
    url = "https://catalog.example/canvas.json"
    launcher.module._catalog.update(
        at=time.time(),
        url=url,
        presets=[
            ("Koi Pond (fish)", "Koi swimming in a pond", "/* koi */"),
            ("Snow", "Falling snow", "/* snow */"),
        ],
    )
    tool = tool_valves(owui, canvas_catalog_url=url)
    card, said = tool.call(
        "create_theme", user=td.ada, name="Pond", hue=150, chroma=20, background="koi pond"
    )
    assert card_data(card)["subtitle"] == "Your theme · Koi Pond · glass"
    assert 'with the "Koi Pond (fish)" animated background' in said
    assert json.loads(card_data(card)["theme"])["dark"]["canvasScript"] == "/* koi */"
    tool = tool_valves(owui, background_animations=False)
    card, said = tool.call(
        "create_theme", user=td.ada, name="Pond", hue=150, chroma=20, background="koi pond"
    )
    assert "without an animated background (an admin turned them off)" in said


def test_the_model_is_told_every_parameter(launcher):
    """Each of the Launcher's parameters is described to the model, from its `:param` line.

    By hand: Workspace > Tools > Theme Designer Pro Launcher: each method lists its parameters.
    """
    specs = {s["name"]: s for s in launcher.specs}
    assert sorted(specs) == ["create_theme", "open_theme_designer"]
    assert "my_theme" in specs["open_theme_designer"]["parameters"]["properties"]
    doc = launcher.module.Tools.create_theme.__doc__
    for name in specs["create_theme"]["parameters"]["properties"]:
        assert f":param {name}:" in doc
