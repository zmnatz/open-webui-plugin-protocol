# owpp-live

`owpp live` for [owpp](https://github.com/zmnatz/open-webui-plugin-protocol): it starts a throwaway Open-WebUI in Docker, with [aimock](https://github.com/CopilotKit/aimock) answering as its models, deploys your plugins with `owpp deploy`, and runs your repository's live tests against it, over Open-WebUI's API and in the browser with Playwright.

```sh
uvx --from owpp-live owpp live                 # the tests in ./live
uvx --from owpp-live owpp live --up            # start it and leave it running, to try things
```

It needs Docker (with compose) and, for tests in the browser, Chromium: `uvx --from owpp-live playwright install chromium`.

Released together with owpp, at the same version. Docs: [owpp live](https://zmnatz.github.io/open-webui-plugin-protocol/commands/live/), and [tests on a real Open-WebUI](https://zmnatz.github.io/open-webui-plugin-protocol/testing/live/).
