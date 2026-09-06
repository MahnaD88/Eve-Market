---
name: eve-manufacturing-opportunity
description: Evaluate whether a user-supplied EVE manufacturing or reaction product is worth making using cost, current offers and historical turnover. Does not discover or scan candidates; do not activate for simple price, recipe or raw-material questions.
---

# EVE supplied-item opportunity analysis

Read [the shared tool and evidence policy](../../references/tool-policy.md)
and [production-variable guidance](../eve-production/SKILL.md) for material
assumptions. This skill handles supplied items only, including reactions.

1. Establish item, quantity, intended sale market, history period if specified,
   and materially relevant unknown production modifiers. Reuse supplied context.
   A user-approved zero baseline is acceptable and must be labelled. Do not ask
   for irrelevant time/capacity inputs or access to the user's character.
2. Call analyze_build_vs_buy once for production evidence unless already present.
   If cost is incomplete, identify missing prices/reasons and stop the reliable
   opportunity judgement. Do not spend two more calls solely to decorate a result
   that cannot answer "worth making?". If the user separately requested market
   evidence as a separate deliverable (for example "also show me the history"),
   fulfil that part while keeping the production conclusion unresolved. A period
   supplied only as an opportunity-analysis parameter is not a separate deliverable.
3. For complete costs, obtain get_sell_orders for the intended sale market and
   get_market_history for the corresponding region, as needed. Reuse suitable
   existing results; do not call get_production_tree or get_material_requirements
   just because they are available. Never silently mix markets or periods.
4. Compare cost on the correct requested-output basis with observed sell offers;
   preserve runs and batch-output context. A cheapest sell order is competition,
   not a buy order guaranteeing revenue. Assess regional historical daily volume
   and order count alongside current offered volume. Do not imply a few cheapest
   orders describe all depth, or that regional activity proves Jita demand.
5. Give a conditional, evidence-based judgement covering material margin,
   turnover uncertainty and missing expenses such as fees, hauling and job costs.
   Do not invent those expenses. Distinguish a material-margin indication from
   net profit, sale certainty or guaranteed market share. If history or prices
   fail, say the opportunity is not fully assessed instead of endorsing it based
   on theoretical margin alone.

The backend's cost scope remains cached cross-region pricing even when the
output market is Jita. Report that mismatch. Do not rewrite backend decisions to
hide it. No automatic discovery or scanning of candidate universes is available.
