# Implemented API contract

Captured from `api/main.py` and `vercel.json`, based on main commit
`580af603b41cf6a6a95fc038142f422e3f73a326`, with the cost-completeness changes
described below. This is an implementation inventory, not an exported GPT Action
schema. The owner-supplied GPT schema and instructions are preserved in the adjacent files.
The deployment origin is `https://eve-market-weld.vercel.app`. Public validation
requests on 2026-09-05 confirmed that `/` and `/api/main` both return the quantity
validation error (400), and `/market-history` returns the days validation error
(400). These probes establish route behavior, not the exact deployed revision.

## Routes and dispatch

| Method/path | Behavior |
| --- | --- |
| `GET /` (live alias), `GET /api/main` | Market orders by default; `mode=tree`, `raw`, or `both` selects production. |
| `GET /market-history` | Regional daily history; Vercel rewrites to `/api/main?_route=market-history`. |

The internal `_route=market-history` query also selects history on `/api/main`.
The Python handler accepts a trailing slash for history; the configured public
rewrite is `/market-history`. No separate `/market` or `/build-tree` route is
configured. There is no application authentication check or custom POST handler.
Responses are JSON. Unexpected errors return HTTP 500 with an `error` field.

Outside history, blank query values are discarded and repeated parameters use
the first value. `mode` is trimmed and lowercased; unrecognised modes fall through
to market lookup rather than returning a mode error. Unknown parameters are ignored.

## Market parameters

| Parameter | Implemented behavior |
| --- | --- |
| `name` | Exact case-insensitive ESI item name; required unless `typeId` supplied. |
| `typeId` | Positive integer item ID; takes precedence over name. |
| `region_name` | Exact region name or Jita/Amarr/Dodixie/Hek region alias. |
| `scan` | Exact solar-system name; infers region if absent; conflicting region gives 400. Filters system, not station. |
| `cheapest` | `true`, `false`, `1`, `0`, case-insensitive. True without location compares all four configured regions. Otherwise defaults to The Forge. Explicit location wins. |
| `top` | Positive integer, default 10; non-integer also falls back to 10. |

Aliases map to The Forge (10000002), Domain (10000043), Sinq Laison (10000032),
and Metropolis (10000042), respectively. ESI supplies public regional sell orders;
all pages are fetched, filtered, sorted ascending by price then order ID, and
limited by `top`. `cheapest=false` does not select buy orders.

Success fields: `status`, `top`, `typeId`, canonical `name`, `region_name`,
`cheapest`, `scan`, `region_ids`, `system_id`, `order_type`, `total_orders`,
`orders`, `cheapest_price`. Orders preserve ESI fields and add `region_id`.
Empty results return 200, empty orders and null cheapest price. Invalid input:
400; unknown names: 404; upstream failure: 502; unavailable/rate-limited: 503;
timeout: 504. No partial results are returned after a page failure.

Example: `/api/main?name=Drake&region_name=The%20Forge&scan=Jita&top=10`

## Production parameters

| Parameter | Implemented behavior |
| --- | --- |
| `mode` | `tree`, `raw`, or `both`. |
| `name` | Required; exact database product name. Unknown/nonbuildable names fall back to market pricing rather than returning 404. |
| `quantity` | Positive integer, default 1. |
| `fit` | Optional text; nonempty lines excluding lines beginning `[`; only text before the first comma is an item name. Each item uses the root quantity. |
| `blueprint_me`, `production_efficiency` | Integers, default 0; manufacturing material modifiers, not applied to reaction materials. |
| `structure_material_bonus`, `rig_material_bonus` | Integers, default 0; material percentage modifiers. |
| `blueprint_te`, `industry_skill`, `advanced_industry_skill` | Integers, default 0; reported time context. |
| `mass_production_skill`, `advanced_mass_production_skill`, `supply_chain_management_skill` | Integers, default 0; reported job/range context. |
| `structure_time_bonus`, `rig_time_bonus` | Integers, default 0; reported time context. |

No explicit ranges are validated for these modifier/skill integers. Quantity and
modifier validation also runs for market requests, although market does not use
them. History dispatch occurs before these validations. Invalid quantity or
non-integer modifiers return 400. Market location parameters, `typeId`, `cheapest`
and `top` do not change production calculations.

Production reads bundled `api/eve-indy.sqlite`: `invTypes`,
`industryActivityProducts`, and `industryActivityMaterials`. Manufacturing (1)
and reactions (11) share recursion and cost selection; the chosen recipe joins
materials on both blueprint and activity, preferring manufacturing if both exist.
Output quantities determine rounded-up runs. Recursion is limited to depth 10.
Pricing uses the existing Fuzzwork resolver and minimum positive sell percentile
across the four configured regions, cached in process; it is not a quote for the
requested market location. Time multipliers are context, not job-duration estimates.

`tree` returns the production node, comparison, `plan`, `hybrid_plan`, and
`inputs`. Nodes include blueprint, activity ID/name, requested/output quantities,
runs, materials, and total cost. Recursive materials have `components`, market
comparison fields and `selected_total_cost`. Nonbuildable leaves include
`buy_price` and `line_total`. `raw` returns flattened `raw_materials` plus plans,
comparison, inputs and fit items; `both` additionally includes `tree`.

For complete costs, building below 95% of market gives `build`; above market gives
`buy`; otherwise `marginal`. Component selection uses the existing cheaper option
in the marginal band. Missing market comparison prices leave comparison fields
null even if the material cost is complete. Fit-item costs are included in the
root total, while the existing root comparison quote covers the root item only.
These are material-cost estimates, not comprehensive profit after fees and hauling.

### Cost completeness (this change)

All production nodes and material entries report `cost_complete`, `missing_prices`
(sorted unique material names), and `incomplete_reasons`. A missing required price
makes `total_cost` null; the available subtotal is never presented as a full cost.
Recursive children and fit items propagate incompleteness to parents. Unresolved
names also count as missing prices. A depth cutoff reports `Max depth reached`
without inventing missing price names.

Comparisons that depend on incomplete totals return null `build_vs_buy`,
`margin_threshold`, `difference_percent`, and `savings`; a component market quote
does not turn an unknown build cost into a valid comparison. Complete independent
branches may still have valid decisions. Both plans carry the same completeness
metadata so their lists must not be interpreted as complete recommendations when
false. All three response modes expose root completeness; raw/both also expose
root `total_cost`. A missing comparison quote alone does not invalidate a fully
priced material cost. Incomplete calculations retain HTTP 200 with explicit state.

Example fragment for a missing material price:

```json
{"total_cost":null,"cost_complete":false,"missing_prices":["Tritanium"],"incomplete_reasons":["Missing material prices"],"build_vs_buy":null,"savings":null}
```

## History parameters and response

`name` and `region_name` are required nonblank exact case-insensitive ESI names;
region aliases above also work. `days` is optional; if present it must be a
positive integer (blank is invalid). It selects the latest N available daily
records, returned oldest first, not a calendar window or zero-filled series.
Other parameters are ignored.

Success fields: `status`, `name`, `type_id`, `region_name`, `region_id`, `days`,
`history`, `summary`. Each daily row preserves `date`, `average`, `highest`,
`lowest`, `order_count`, `volume`. Summary fields: arithmetic `average_price`,
`average_daily_volume`, `total_volume`, `lowest_price`, `highest_price`,
`average_order_count`, `days_returned`, `current_vs_average`. Optional comparison
only uses an already cached manufacturing quote and labels its cross-region
source and unknown freshness; it does not fetch a current regional quote.
Empty history succeeds with zero volume/count, null price/average values, and an
empty history array. Validation and upstream errors use the market error statuses.

Example: `/market-history?name=Drake&region_name=The%20Forge&days=30`

## Captured GPT configuration and mismatches

The owner supplied both snapshots on 2026-09-05. The Action is OpenAPI 3.1.0,
API version 1.2.0, server `https://eve-market-weld.vercel.app`, with one operation:
`analyzeItem`, `GET /`, and 21 query parameters. The original JSON has been kept
in the `.yaml` file: JSON syntax is valid YAML, so this is not a malformed format.
It parses and all local schema references resolve. This is a structural check,
not certification by the GPT editor or a complete OpenAPI validator.
Instructions retain the supplied Markdown escapes verbatim. Neither snapshot
has been corrected, and neither has been installed back into the GPT.

| Area | Supplied GPT configuration versus current implementation |
| --- | --- |
| Route | `/` is the registered Action path and works on the public deployment. `/api/main` also works. The repository's explicit rewrite only covers history; the root alias's deployment-level source is not established by `vercel.json`. Do not label `/` broken. |
| Market descriptions | `typeId`, `region_name`, `cheapest`, `scan`, and `top` still say "Market mode placeholder parameter". All now drive real market lookups. |
| Market response | `MarketPlaceholderResponse` is obsolete. It lacks orders, resolved location IDs, order count and cheapest price. Its `typeId` allows string/null, but successful market responses return an integer. `additionalProperties: true` allows undeclared fields, but does not correct a conflicting declared type. |
| History | No `/market-history` operation or `days` parameter is exposed, despite the working backend route. The current Action cannot describe or directly select that operation. |
| Cost completeness | The schema does not describe `cost_complete`, `missing_prices`, or `incomplete_reasons` on nodes, responses or plans. Raw/both also omit the newly exposed `total_cost`. Null totals are already allowed where declared. |
| Reactions | Reaction calculations work, but `activity` and `activity_id` are not described in the response schemas. |
| Default mode | Instructions and schema say tree; backend omission selects market. A schema default is not evidence the HTTP client will send `mode=tree`. |
| Required name | Schema marks name optional for every mode; backend requires it for production, and market requires either name or typeId. |
| Variables | Instructions require asking for all twelve variables before any API call. Schema marks them optional with zero defaults; backend defaults to zero. The unqualified instruction can also interrupt market-only queries unnecessarily. |
| Errors and validation | Schema describes only 200/400/500, omitting 404/502/503/504. `top` lacks a positive minimum; `typeId` lacks positive-integer constraints; `cheapest` lacks its accepted-value constraints. The backend validates these. |
| Response alternatives | `oneOf` alternatives overlap: permissive TreeResponse and MarketPlaceholderResponse can both validate the same object. MarketPlaceholderResponse has no required fields. Thus real responses may fail exclusive-one validation even though the document parses. This is a schema-design defect, not invalid JSON. |
| Output instructions | "Output ONLY" BUILD/BUY/SHOPPING LIST when hybrid_plan exists does not require showing incomplete-cost state or missing prices. It can hide the backend warning, and omits marginal components. The captured instructions need a future reviewed change to surface incompleteness before recommendations. |
| Name handling | Removing numbers and forcing singular names can corrupt legitimate EVE item names. Preserve this as a documented instruction risk rather than silently modifying the snapshot. |

No `security` or `securitySchemes` entries are present. This establishes only
what the supplied schema declares; GPT-editor authentication settings were not
provided and remain unverified. The backend has no application authentication check.

The missing-price fix is already committed in
`c6e19b0b4b74eed37b09bfe7ff6b82e4de06409c`; its 37-test suite passed, including
market history and reactions. This configuration capture introduces no runtime
changes. Updating the installed Action, changing GPT instructions, and adding a
plugin/MCP adapter remain outside this task.
