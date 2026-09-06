---
name: eve-production
description: Answer EVE manufacturing or reaction recipe, raw-material and build-versus-buy questions using the minimum required tool. Use for supplied items, not current-price-only requests or candidate scanning.
---

# EVE production and build-versus-buy

Read [the shared tool and evidence policy](../../references/tool-policy.md).

Start with the tool matching the request: get_production_tree for recipes,
get_material_requirements for raw quantities, analyze_build_vs_buy for cost
comparisons. A named-market comparison may also need current orders, as described
in the shared policy. Manufacturing and reactions follow the same evidence rules; retain
activity/activity_id and the backend's quantities. Do not special-case formulas
or compute another recipe. Do not ask about blueprint ownership or character data.

## Production variables

The MCP schema defaults twelve modifiers to zero; those defaults are a baseline,
not evidence about the user's setup. Retain known values from the conversation.
Before personalised quantities, costs or build/buy recommendations, clarify the
unknown modifiers that materially affect the requested calculation. Ask together
and allow the user to explicitly choose an all-zero baseline. Do not make the
old GPT's blanket request for all twelve values on every question.

Material modifiers: blueprint_me, production_efficiency, structure_material_bonus,
rig_material_bonus. Manufacturing applies all four. Reactions ignore the first
two at that node; manufacturing children in a reaction chain can still use them.
Do not assume an entire reaction chain ignores manufacturing modifiers. If recipe
structure is already available, use it to decide relevance; otherwise ask for
material assumptions or a baseline rather than adding exploratory tool calls.

Time/capacity context: blueprint_te, industry_skill, advanced_industry_skill,
mass_production_skill, advanced_mass_production_skill,
supply_chain_management_skill, structure_time_bonus, rig_time_bonus. Ask about
these only when that context is material to the request. The API reports context
multipliers, not actual job durations; do not invent completion times.

A simple "what is it made from?" can call the tree with defaults to identify
components without setup questions. Label any displayed quantities as baseline,
and do not turn incidental costs into a personalised estimate. For "raw materials
for 10 Drakes", clarify relevant material modifiers or obtain baseline acceptance,
then make one material-requirements call with quantity=10.

## Present the result

Inspect completeness first and identify missing material names. Answer the
requested recipe, quantities, or decision concisely; expose assumptions that
change its meaning. Keep marginal decisions visible when relevant. Do not label
a partial hybrid plan complete or silently omit uncertain components. If a fit
was supplied, disclose that backend total includes fit items while its comparison
quote covers only the primary item. Do not promise net profitability from this
comparison. Stop once the question is answered.
