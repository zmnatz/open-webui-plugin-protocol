# Dynamic Vision Router

**Adapted from [Dynamic Vision Router](https://github.com/open-webui/functions/tree/main/functions/filters/dynamic_vision_router) by open-webui and atgehrhardt** (credits to @iamg30 for 0.1.5 to 0.1.7; Open WebUI License, see `NOTICE.md`), written to this repository's conventions with the same behaviour: the header is in `plugin.yaml`, the imports and types are tidied. The list of changes is at the top of `function.py`.

A **filter** with only an inlet. When the user's last message has a picture in it (an `image_url` part, or an `images` list), the request is sent to the model in `vision_model_id` instead of the one the chat is with. So a chat can stay on a text model and still answer about pictures.

It leaves the request alone when `vision_model_id` is empty (the default), when the chat is already with that model or with one in `skip_reroute_models`, and for admins unless `enabled_for_admins` is on. With `status` on, the chat shows "Request routed to <model>".

The vision model must be one the user can use: a user who is not an admin gets "Model not found" for a model with no read grant.

Valves: `priority`, `vision_model_id`, `skip_reroute_models`, `enabled_for_admins` (off), `enabled_for_users` (on), `status` (off). Global.

## Test

- `owpp check vision_router` bundles it exactly as the deploy does, compiles it and lists names it uses but never defines.
- `owpp bundle vision_router out.py` writes the deployed code to read or diff.
- `owpp test vision_router` runs `tests/` against the real Open-WebUI, in process (docs/testing.md).
- On a live Open-WebUI: set `vision_model_id` to a model that can see pictures, and as a user who is not an admin send a picture in a chat with another model. The vision model answers. The live suite (`tools/screenshots/run.py --live`) checks this with aimock as the model.

## Deploy

- Function type: **filter**, global.
- `owpp deploy --only vision_router --dry-run`, then without `--dry-run`. A single-plugin deploy never prunes.
