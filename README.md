# Eve-Market

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
