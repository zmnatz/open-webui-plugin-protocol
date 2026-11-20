# Security

## Reporting a vulnerability

Please report it privately, not in a public issue: use GitHub's **Security** tab on this repository,
**Report a vulnerability**. If that is not available, open an issue that says only that you have a
security report and ask for a private channel; leave the details out.

Supported: the latest release. This is pre-1.0 software, written against Open-WebUI v0.13.4 and
checked on a live Open-WebUI only by hand, not in CI (see
[status and limits](docs/README.md#status-and-limits)), so treat it accordingly.

## The trust model, in one paragraph

A plugin is **code that runs inside Open-WebUI with admin rights**, and `owpp deploy` signs in **as an admin**
(an API key, a password, an OIDC token, or an instance that needs none) to put it there. Whoever can change the plugins repository, or the repository a plugin's
`source:` points at, can therefore run code as an Open-WebUI admin, so a CI job that deploys on push
makes *write access to that repository* equivalent to *admin on Open-WebUI*. Everything below is
about keeping that explicit and narrow, not about making untrusted plugins safe.

## What runs where

| | Runs as | Notes |
|---|---|---|
| A plugin's `function.py`, `tool.py`, `shared.py` | Python in the Open-WebUI process, admin rights | Arbitrary code. Read it before you deploy it. |
| `assets/loader.js` | JavaScript in **every user's browser, on every page** | It is a fragment of the shared `/static/loader.js`: it can read and change the whole interface, including other users' content and their session. Treat it as full access to the UI. |
| `assets/custom.css` | CSS on every page | Can restyle or hide anything (a phishing-grade overlay is possible). |
| `owpp check`, `bundle`, `list` | Your machine | They parse and compile plugin code but never run it. `check` and `list` fetch `source:` files with `git`. |
| `owpp deploy` | Your machine / CI | Sends code to Open-WebUI with the admin key. |

## What `owpp` does to limit the damage

- **Pinned third-party code.** A `source:` is a git URL (https or ssh only) and a **full 40-character
  commit SHA**, never a branch or tag; it is fetched by that SHA, shallow, into a scratch repository.
  Upgrading means reviewing the upstream diff and changing the SHA.
- **Reproducible bundles.** A bundle depends only on the plugin folder and the pinned commits. In
  particular **environment variables are never read while bundling or deploying**: `${NAME:-x}` in
  `config.yaml` or `jobs:` is embedded as written and resolved inside the Open-WebUI container when
  the plugin loads, so the machine that deploys cannot change the code or leak its environment into it.
  A secret goes in a plugin as a reference, `${NAME}`, never as text.
- **It only deletes what it created.** Functions it deploys carry an ownership marker, and pruning acts
  on that marker alone. A mass delete (more than half) is refused without `--force-prune`.
- **Signed in by default; public only on purpose.** Every route a plugin mounts requires a signed-in
  Open-WebUI user, and the library refuses to mount one that does not (`plugin_mount`, including the
  `static/` files). A route that needs more is marked on its handler (`user: PluginAdmin`,
  `chat_id: WritableChat`); the checks are not hand-written. Serving people who are not signed in takes
  `access="public"` on a mount of its own, or `static: {access: public}`, in exactly those words, and
  **`owpp check` lists every one as a `note`** so a reviewer sees it. `owpp check` also refuses a
  `function.py` that adds routes straight to the app, which would skip the guard, and refuses unknown or
  removed keys in `plugin.yaml` (including the old `public:` and `routes:`) rather than ignoring a
  setting that was meant to restrict something.

## Known limits

- **A public mount is open to the internet** (or to whatever can reach Open-WebUI). It gets no
  session, no admin check and no rate limit from this library, and its handlers must treat every input as
  hostile. Keep them few, small and idempotent, and check the `note` lines `owpp check` prints.
- **`plugin_mount(guard=...)` is the one exception to "every route needs a login".** It exists for an
  API called from a sandboxed iframe, which sends no cookies (Excalidraw's editor). The route is
  protected by a short-lived, signed token (`plugin_token`) that is scoped to the plugin and to one
  subject and is only minted on a guarded page, but a holder of a token keeps access until it expires
  even if their access to the chat is removed in the meantime.
- **Temporary chats** (`local:...`) have no stored record, so `WritableChat` and `ReadableChat` cannot
  check ownership: any signed-in user who knows the id passes. Do not keep anything private in them.
- **A page opened with no session tries the no-input sign-ins first.** For a browser navigation the
  guard calls Open-WebUI's own sign-in endpoint, inside the app, with the request's headers (as its
  login page does), so a trusted-header or no-auth setup works without visiting the home page first;
  otherwise the browser is sent to the login page. This inherits Open-WebUI's own assumption about
  trusted headers: **your reverse proxy must strip a client-supplied trusted-identity header** and
  Open-WebUI must not be reachable except through it. If it is, anyone can claim any identity at the
  login page already, and now at plugin pages too.
- **Excalidraw and Inline Visualizer need Open-WebUI's "iframe Sandbox Allow Same Origin".** With it
  on, the script of every artifact, not only theirs, runs with Open-WebUI's origin and can act as the
  user. This is an Open-WebUI setting the plugins cannot narrow; enable them only where you trust what
  the models put into artifacts. Why it is required, and why it is not worked around:
  `docs/libraries.md`, "Pages in the Artifacts panel".
- **Third-party hosting is yours to secure.** Excalidraw loads its editor from esm.sh unless you
  self-host it (see its README); either way the code runs in your users' browsers with no integrity
  check.
- **Not tested against a live Open-WebUI.** The tests use stand-ins for its session check, chat access
  and function table. Several behaviours are assumptions until verified (that `/api/v1/auths/signin`
  accepts empty credentials under trusted-header auth, that the login page honours `?redirect=`, the
  argument names Open-WebUI passes to an Event function's `event()`).

## For people deploying plugins

- Give CI a **dedicated admin user** used for nothing else, with its API key, password or token
  stored as a secret, and rotate it. Deploying with no credentials only works on an instance where
  anyone who can reach it is already an admin (sign-in off) or a proxy vouches for them: do not
  leave such an instance reachable.
- Restrict who can push to the plugins repository (and to any repository a `source:` names). Require
  review for changes to `plugin.yaml`, `assets/` and anything that touches `ref:`.
- **Pin `owpp`** (`uvx owpp@0.2.0`) and pin the action to a tag or SHA: the runtime and libraries are
  copied into what you deploy, so an upgrade changes your deployed code.
- Run `owpp deploy --dry-run` before the first deploy and read the plan; run `owpp check --strict`
  in CI.
- Serve anything you self-host (such as Excalidraw's editor) over HTTPS.
