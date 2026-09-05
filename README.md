# Eve-Market

The implemented routes and parameters are recorded in [the API contract](docs/api-contract.md).
The files `docs/current-gpt-actions.openapi.yaml` and
`docs/current-gpt-instructions.md` preserve the configuration supplied by the owner.
The Action schema retains its original JSON syntax (also valid YAML). Known
differences from the backend are documented in the contract; these snapshots
have not been corrected or installed into the GPT.

Production responses expose `cost_complete`, `missing_prices`, and
`incomplete_reasons`. Missing required material prices make `total_cost` null
and suppress dependent build-vs-buy comparisons. This propagates through
manufacturing, reaction chains and fitted items, including raw/both responses
and plan completeness metadata. Fully priced calculations retain their previous
costs and decisions.

`GET /api/main` serves market lookups unless `mode=tree`, `raw`, or `both`
selects the existing manufacturing API.

## Market lookup

Example: `/api/main?name=Drake&region_name=The%20Forge&scan=Jita&cheapest=true&top=10`

- `name`: exact EVE item name (case insensitive), resolved through ESI.
- `typeId`: positive item ID; takes precedence over `name` when supplied.
- `region_name`: exact region name, or existing aliases Jita, Amarr, Dodixie,
  and Hek. An alias selects the whole region; use `scan` to restrict the system.
- `scan`: exact solar system name. Its region is inferred if omitted; a
  conflicting `region_name` returns 400.
- `cheapest`: `true`/`false` (also `1`/`0`, case insensitive). When true and no
  location is supplied, compares the four configured regions: The Forge,
  Domain, Sinq Laison, and Metropolis. Explicit location filters take precedence.
  Otherwise an omitted location defaults to The Forge.
- `top`: positive maximum number of returned orders. Defaults to 10, including
  non-integer values for compatibility with the existing query parser.

Results contain `status: "ok"`, the existing request metadata fields, resolved
`typeId` and canonical `name`, `region_ids`, `system_id`, `order_type: "sell"`,
`total_orders`, `cheapest_price` (ISK per unit), and `orders`. Orders retain ESI
fields (including price, location/system IDs and remaining volume) and add
`region_id`. All pages are fetched before sorting by ascending price, then
order ID, and applying `top`. `cheapest=false` still returns cheapest-first sell
orders within its scope; it does not request buy orders.

An empty market returns 200 with `orders: []` and `cheapest_price: null`.
Invalid parameters return 400, unknown items/locations 404, upstream failures
502, temporary unavailability/rate limits 503, and timeouts 504. Errors never
return partial market results. Data comes from public ESI regional orders;
private structure orders are outside this endpoint's scope. Freshness follows
ESI's own cache; this application does not retain market prices between calls.

ESI references: [API explorer](https://developers.eveonline.com/api-explorer)
and [market pagination](https://developers.eveonline.com/blog/esi-concurrent-programming-and-pagination).

## Tests

Install `requirements.txt`, then run `python -m unittest discover -s tests -v`.
The tests mock ESI, covering filtering, pagination, sorting, scope selection,
validation, failure handling, and preservation of manufacturing dispatch.

## Regional market history

`GET /market-history?name=Drake&region_name=The%20Forge&days=2`

`name` and `region_name` are required, case-insensitive exact EVE names.
The existing Jita, Amarr, Dodixie and Hek region aliases also work. Item
resolution uses the existing market-mode ESI resolver so outages are not
mistaken for unknown items. The manufacturing resolver remains unchanged.

`days` is optional and must be a positive integer when supplied. Omit it for
all history available from ESI. It selects the latest N **available daily
records**, sorted oldest to newest, rather than a calendar window ending
today; days without a record are not filled with zeros. A limit larger than
the available history returns all records.

Illustrative response (prices and volumes are example data):

```json
{
  "status": "ok",
  "name": "Drake",
  "type_id": 24698,
  "region_name": "The Forge",
  "region_id": 10000002,
  "days": 2,
  "history": [
    {"date": "2026-09-03", "average": 100, "highest": 120, "lowest": 80, "order_count": 10, "volume": 20},
    {"date": "2026-09-04", "average": 150, "highest": 180, "lowest": 120, "order_count": 20, "volume": 40}
  ],
  "summary": {
    "average_price": 125,
    "average_daily_volume": 30,
    "total_volume": 60,
    "lowest_price": 80,
    "highest_price": 180,
    "average_order_count": 15,
    "days_returned": 2,
    "current_vs_average": null
  }
}
```

Summaries use only returned rows. `average_price` is the arithmetic mean of
ESI daily averages (not volume weighted); daily volume and order count are
also arithmetic means. Lowest/highest are the extrema of daily lowest/highest
prices. ESI row fields are preserved. Prices are ISK per unit, volume is units.

`current_vs_average` is null unless the existing manufacturing price cache
already contains a positive price and the history average is positive. No
additional pricing calls are made. When available, it contains `current_price`,
`difference` (current minus average), `difference_percent` (difference divided
by average times 100), `source: "cached_manufacturing_sell_percentile"`, the
four configured `region_ids`, and `freshness: "unknown"`. This optional context
is a cached cross-region Fuzzwork sell percentile, **not a fresh quote for the
requested region**; the existing cache has no timestamps.

Empty history returns 200, an empty list, zero total volume/days, and null
averages/extrema/comparison. Invalid/missing inputs return 400; unknown names
404; upstream or malformed ESI responses 502; ESI rate limits/unavailability
503; timeouts 504. The Vercel rewrite maps only `/market-history` to the
existing Python handler; existing market and manufacturing URLs still work.

## Manufacturing and reactions

Build modes recognise SDE activity 1 (manufacturing) and 11 (reactions).
Each buildable tree node includes `activity_id` and `activity` (`manufacturing`
or `reaction`). Recipes are selected as a single blueprint/activity pair;
when alternatives exist, manufacturing is preferred, then the lowest blueprint
ID. Inputs from different recipes or activities are never combined.

Reaction batch output and input quantities come from the SDE. Requested output
is rounded up to whole runs. Manufacturing ME/PE inputs do not reduce reaction
materials; the existing explicit structure/rig material bonuses still apply.
Manufacturing calculations are otherwise unchanged. Existing recursive cost,
build-vs-buy, raw-material and hybrid-plan logic also traverses reaction nodes.
The existing manufacturing timing context is not a reaction duration estimate.

Example: `/api/main?mode=tree&name=Carbon%20Fiber&quantity=201` uses Carbon Fiber
Reaction Formula (activity 11), runs twice, and produces batches of 200. With
zero structure/rig bonuses it needs 10 Hydrogen Fuel Blocks, 200 Hydrocarbons
and 200 Evaporite Deposits. Query the **product name**, not the formula item name.
