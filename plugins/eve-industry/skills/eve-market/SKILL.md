---
name: eve-market
description: Answer current EVE sell-price, regional history and market-volume questions. Choose orders for current offers and history for historical activity; do not trigger production analysis for price-only requests.
---

# EVE market and liquidity

Read [the shared tool and evidence policy](../../references/tool-policy.md).

Current price: call get_sell_orders only. Supply name or positive type_id;
type_id wins if both are given. Translate a named hub such as Jita into
system_name="Jita" to request system offers. region_name="Jita" alone means
its whole region. Do not claim a system filter selects a particular station.
Use top=1 for a simple lowest-price question; request more orders only when
quantity/depth is relevant. Report sell-offer price, scope and available volume,
not a guaranteed sale price for the user's goods. Ask only about ambiguous item
or location inputs, never production modifiers.

History/volume: call get_market_history only, with the item, region_name and
requested days. Ask for an unknown region rather than choosing one secretly.
For a Jita-scoped history question, use The Forge and explicitly state that the
history covers the region. days counts latest available records and is not a
zero-filled calendar interval. Omit days for all available history if no period
was requested, and report the returned period/count.

Liquidity means different things: historical volume needs history; current
order depth needs orders; a request comparing both needs both. Request further
clarification only if this ambiguity changes the answer. Preserve empty results
as empty, not proof of zero value. Do not infer historical buys/sells at a
particular station from regional history. Do not call production tools for a
market-only request. Cached current_vs_average is not a fresh current quote.
