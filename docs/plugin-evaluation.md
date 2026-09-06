# Stage 3 evaluation — 2026-09-06

## Scope and evidence

- Full Python suite with EVE_MCP_LIVE=1: **52 tests passed**, no skips.
- This includes all 37 pre-adapter backend tests, the Stage 2 adapter/protocol
  tests, and six new plugin/connection/deployment-entrypoint tests.
- Live EVE checks exercised all five tools via Streamable HTTP, including Drake
  orders/history, Antimatter Charge S manufacturing, Carbon Fiber reactions and
  unresolved-item missing-price propagation.
- The three skills passed skill-creator's quick_validate.py.
- The local package passed plugin-creator's validate_plugin.py.
- A temporary package bound to an explicitly test-only connection ID also passed
  that validator. This checks the .app.json shape, not a real ChatGPT connection.
- Public-host ASGI tests exercised initialization, discovery, missing-cost output,
  and rejection of unexpected Host/Origin headers. Vercel deployment remains untested.

## Independent skill forward test

An independent agent read only the skills and references, then reasoned through
eight realistic user prompts without receiving the intended tool lists. It did
not use live EVE tools, edit files or claim to be an installed ChatGPT instance.
Its observed choices were saved in `tests/fixtures/plugin_skill_traces.json`.
Automated checks validate those saved arguments against the actual MCP schemas
and audit minimum-call expectations. These checks are not a new production router
and do not prove future model behavior from matching text or fixtures.

| Scenario | Observed choice |
| --- | --- |
| Current Jita price | get_sell_orders, top 1; no production/history |
| Regional historical volume | get_market_history only |
| Reaction recipe | get_production_tree only |
| Raw materials, unknown setup | Clarification first; get_material_requirements after baseline/values |
| Ordinary build/buy, accepted baseline | analyze_build_vs_buy only |
| Worth making, supplied item/setup/market | analyze_build_vs_buy, then current offers and history if complete |
| Incomplete result already supplied | No additional calls; identify Hydrocarbons, withhold reliable judgement |
| Candidate discovery request | No scan; ask for supplied items/scope |

The review found wording tensions around named-market comparisons, whether a
history period implied a separate requested output, and candidate ranking scope.
The skills were narrowed and the agent re-read the changes. It reported those
issues resolved, with no new contradiction or encouraged unnecessary calls.
Order count for opportunity analysis remains an intentional request-specific
choice; the model must disclose that a limited order sample is not all depth.

## Remaining acceptance tests

A real installed ChatGPT run is **pending**. It needs the owner-created connection
ID and local package installation on a supported surface. Record actual selected
tool names/arguments, results, clarifications and response warnings for the README
prompts. Add a named-market build/buy request, paraphrases, follow-ups reusing fresh
results, and failed upstream history. Verify no reliable endorsement is made from
margin alone or when cost/market evidence is incomplete. Do not label instruction
compliance as enforced by the MCP server.

No deployment, app registration, plugin install, or public submission was performed
by these tests. The existing backend and installed custom GPT were preserved.
