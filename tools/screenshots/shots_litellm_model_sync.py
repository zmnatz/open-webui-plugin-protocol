"""LiteLLM Model Sync on a real Open-WebUI. The stack's second OpenAI connection answers
/model/info as a LiteLLM gateway would (gateway/), so the sync runs against Open-WebUI's real
connections."""

from __future__ import annotations

from conftest import URL


def test_users_see_the_gateways_names(user, shot):
    """By hand: as a user who is not an admin, open the model selector in a new chat. The
    models carry the gateway's display names, and the embedding model is not listed."""
    user.goto(f"{URL}/")
    user.locator("#model-selector-model-button").click()
    user.get_by_text("Screenshot Model").last.wait_for()
    user.wait_for_timeout(500)
    shot(
        user,
        "litellm_model_sync",
        "model-selector",
        "A user's model selector after a sync: the gateway's display name, readable by every "
        "user, and the embedding model hidden.",
        illustrates=[
            "test_each_model_gets_its_display_name_tags_and_vision",
            "test_non_chat_models_are_hidden_but_stay_usable",
        ],
    )


def test_the_admin_model_list(admin, shot):
    """By hand: open Admin Settings > Models. Each synced model has the gateway's name and is
    marked Public, and the embedding model is greyed out: hidden, but still switched on."""
    admin.goto(f"{URL}/admin/settings")
    admin.locator("button", has_text="Models").last.click()
    admin.get_by_text("Screenshot Embeddings").wait_for()
    admin.wait_for_timeout(800)
    shot(
        admin,
        "litellm_model_sync",
        "admin-models",
        "Admin Settings > Models after a sync: display names from the gateway, each readable "
        "by every user (Public), and the embedding model greyed out (hidden) but still on.",
        illustrates=[
            "test_each_model_gets_its_display_name_tags_and_vision",
            "test_non_chat_models_are_hidden_but_stay_usable",
        ],
    )
