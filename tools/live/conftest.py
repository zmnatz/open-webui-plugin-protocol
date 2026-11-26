"""The live suite (test_*.py here): `tools/screenshots/run.py --live` runs it with `owpp live`,
which starts Open-WebUI with aimock, deploys examples/plugins and runs these with pytest; the
repository's own test run never collects them.

The fixtures are owpp-live's (docs/testing/live.md#the-fixtures): `api` and `user_api` for
Open-WebUI's API, `aimock` for what it sent the model, and the Playwright pages `admin`, `user`
and `signed_out`, with `send(page, text)` from owpp_live to chat."""
