# EVE Industry — private plugin package

Stage 3 packages the existing Stage 2 MCP adapter. The backend, custom GPT,
five tool schemas and tool behavior are unchanged. No custom UI is required.

## Package structure

```text
plugins/eve-industry/
  .codex-plugin/plugin.json
  .mcp.json
  skills/
    eve-production/SKILL.md
    eve-market/SKILL.md
    eve-manufacturing-opportunity/SKILL.md
  references/tool-policy.md
```

The repository catalog is `.agents/plugins/marketplace.json` (source name
`personal`, display name Personal). Its local path points to this package.
The initial MCP configuration points to the existing adapter at
`http://127.0.0.1:8000/mcp`; it does not bundle a second server implementation.
This catalog has been prepared, not installed into the user's application.

`.app.json` is intentionally absent until ChatGPT creates a real connection ID.
The current specification uses that file for registered connections, not arbitrary
server URLs. `scripts/configure_plugin_connection.py` creates it from the owner's
`plugin_asdk_app...` ID, points the manifest at it, removes the manifest's local
MCP reference, and preserves `.mcp.json` as `.mcp.local.json` so automatic discovery
cannot enable duplicate connections. Do not insert a made-up ID or register the
existing REST API URL as though it were an MCP endpoint.

## Skills and tool discipline

- **eve-production**: recipes, manufacturing/reactions, raw quantities, build/buy,
  completeness and relevant modifier clarification.
- **eve-market**: current offers versus regional history/volume and scope.
- **eve-manufacturing-opportunity**: supplied-item cost, sale offers and turnover;
  no candidate-universe discovery or scanning.

All three load the shared policy and choose the minimum set of EVE tools. Price,
history, recipe, raw-material and ordinary build/buy requests normally use one
matching tool. A supplied-item opportunity assessment uses build/buy evidence,
orders and history only as needed; it stops a reliable opportunity judgement
when costs are incomplete. Existing suitable results are reused. No duplicate
tree call is needed after analyze_build_vs_buy.

This is model instruction logic, not an enforced programmatic router. It does
not alter MCP schemas, prevent a host from calling a tool directly, or replace
installed-model evaluation. Model reasoning may combine returned facts, but may
not invent EVE prices, volumes, costs, modifiers or unprovided expenses.

Zero-default material modifiers must not be presented as personalised values.
Ask about materially relevant unknowns or obtain explicit baseline acceptance.
A recipe-only question can use defaults to identify components without a twelve-
variable questionnaire. Do not ask about time/capacity modifiers for price-only
or material-only questions. Reaction nodes ignore manufacturing ME/PE, but their
manufacturing children may still depend on them.

## Local private testing on desktop

From the repository root:

```sh
python -m pip install -r mcp_adapter/requirements.txt
python -m mcp_adapter.server
```

Keep this server running while testing. In another terminal, add this explicit
repository source before attempting to install from it:

```sh
codex plugin marketplace add .
```

Restart the ChatGPT desktop/Codex app, open Plugins, choose the Personal local
source associated with this repository, and install EVE Industry. Start a new
conversation, select EVE Industry or mention it, and try the prompts below. Local
marketplace availability varies by surface. A browser-only ChatGPT session cannot
reach the PC's loopback URL; use the registered remote/tunnel path below for that.
No claim is made that this installation has already occurred.

## Registered connection for ordinary ChatGPT

The official flow is documented in [Package your plugin](https://developers.openai.com/plugins/build/plugins)
and [Connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt).

1. Obtain a reachable MCP endpoint: deploy the separate adapter after resolving
   hosting access, or connect its local HTTP endpoint through the official Secure
   MCP Tunnel developer-mode flow. Public HTTPS URLs must include `/mcp`.
2. In ChatGPT open Settings → Security and login → Developer mode. Availability
   depends on the account/workspace. Open Plugins and select the plus button.
3. Name it EVE Industry MCP. Under Connection choose the HTTPS URL or Tunnel.
   The adapter uses public read-only data and has no user authentication; use
   the no-auth choice where the connection form asks. Create the connection.
4. Confirm the five discovered tools: get_sell_orders, get_market_history,
   get_production_tree, get_material_requirements, analyze_build_vs_buy.
5. Copy the connection's technical ID from its browser URL. It begins with
   `plugin_asdk_app`. From this repository run the command below, substituting
   the actual copied value (the script rejects the literal example token):

   ```sh
   python scripts/configure_plugin_connection.py --app-id YOUR_COPIED_ID
   ```

6. If the local repository source has not yet been added, run
   `codex plugin marketplace add .`. Refresh/reinstall EVE Industry from that
   source and start a new conversation. Verify `.app.json` points to your real
   ID and the plugin is enabled. Do not keep the separate raw MCP connection and
   plugin both selected if they expose duplicate tool lists.
7. Invoke EVE Industry from the conversation's plugin/tools selector or an
   @mention. Run the scenario prompts below and inspect the selected tools.

The connection, local-source installation, and application refresh are manual
account steps. Registration alone gives the five tools; installing the complete
package is what adds these skills. If your surface does not expose local sources,
use the desktop local-source workflow rather than assuming raw MCP registration
also installs skills. No public Plugin Directory submission is involved.

If editing an already installed local copy, use plugin-creator's cachebuster and
reinstall flow; local plugins are cached and a new chat is needed. The `.app.json`
mapping is account-specific and can remain in your local checkout.

## Hosting status and exact remaining work

**Not deployed in Stage 3.** On 2026-09-06 the connected Vercel app returned the
team `onyx7` but an empty projects list. The existing production project's settings
could not be verified. Per the requested stop condition, no project was created,
linked, reconfigured or deployed, and the existing root `vercel.json` is unchanged.

Recommended target: a separate Vercel project for the adapter, using the same
account and existing backend URL. Restore Vercel access to the intended account
or confirm the new project in its dashboard. The original EVE backend must not
be selected as the deployment target.

The preparation command creates a new standalone folder and refuses to overwrite
an existing folder:

```sh
python scripts/prepare_mcp_deployment.py ../eve-industry-mcp-deploy
```

It copies the existing adapter (no API, SQLite, credentials or plugin skills) and
adds an ASGI `app.py`, adapter requirements, Python 3.14 selection, and a separate
`vercel.json` with a 180-second function allowance. It does not invoke Vercel.
The ASGI wrapper uses the existing create_server factory and stateless Streamable
HTTP; the five tool schemas and handler behavior stay identical.

After access and the new project are confirmed, an operator can deploy this
standalone folder with Vercel CLI, selecting a **new** project:

```sh
vercel deploy --cwd ../eve-industry-mcp-deploy
```

Verify preview startup/lifespan, initialization, discovery and all five calls
before production promotion. The new entrypoint has passed ASGI tests locally;
its behavior on Vercel is not yet verified. Expose the production `/mcp` URL to
ChatGPT only after those checks. A Vercel login-protected preview is not a usable
public ChatGPT MCP URL.

The wrapper accepts exact hosts from VERCEL_URL and VERCEL_PROJECT_PRODUCTION_URL.
For a custom domain set EVE_MCP_PUBLIC_HOST to its bare hostname. Host/origin
protection remains enabled. Confirm the chosen function allowance exceeds the
adapter's 120-second total backend deadline. All public access and project
settings must be reviewed on the new project; no existing protection is disabled.

[Vercel Python hosting](https://vercel.com/docs/functions/runtimes/python) supports
ASGI entrypoints and streaming. The wrapper/staging files prepare that path;
they do not establish a deployed URL. A private ChatGPT connection does not by
itself make a separately hosted no-auth endpoint private.

## Tests and prompts

```sh
python -m pip install -r requirements.txt -r mcp_adapter/requirements.txt -r tests/requirements-plugin.txt
python -m unittest discover -s tests -v
```

Enable EVE_MCP_LIVE=1 for live backend checks (PowerShell:
`$env:EVE_MCP_LIVE='1'`). See [the evaluation report](../../docs/plugin-evaluation.md)
for results and the distinction between automated tests, independent reasoning
traces, and installed ChatGPT tests still pending.

Try these in fresh conversations with the plugin enabled:

| Prompt | Expected behavior |
| --- | --- |
| How much is Carbon Fiber in Jita? | Sell orders only; system scope. |
| Show Carbon Fiber volume in The Forge over the last 30 days. | History only. |
| What is Carbon Fiber made from? | Production tree only; no setup questionnaire. |
| What raw materials do I need for 10 Drakes? | Clarify material modifiers/baseline, then requirements only. |
| Use a zero baseline: is it cheaper to build or buy one Drake? | Build/buy only; disclose pricing scope. |
| Is Carbon Fiber worth making? Sell in Jita, use a zero baseline and 30 days history. | Build/buy, then orders/history if needed and cost complete. |
| A returned cost is incomplete and Hydrocarbons is missing. Is it worth making? | Lead with missing price, no reliable profitability claim or redundant fetch. |

No SSO, authenticated ESI, character/corporation data, jobs, assets, blueprint
ownership, wallet access, zKillboard, scanning or public submission was added.
