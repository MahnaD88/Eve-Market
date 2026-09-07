# EVE Analytic Engine: technical design

Status: design only. Reviewed 2026-09-07 against repository main
`a84cb15a1d71b7bd0160829b8c775c01051f1342`.
No implementation, deployment, SSO, plugin distribution or calculation changes
are authorized by this document. Numerical policy thresholds below are inputs
to be calibrated, never asserted EVE facts.

## 1. Decision and existing-system boundary

Build a bounded, snapshot-based analytic engine alongside the existing backend.
It should compute reproducible opportunity evidence and feasible portfolios;
ChatGPT explains trade-offs rather than processing thousands of orders.

Reviewed: `api/main.py`, README, `docs/api-contract.md`, SQLite schema,
`mcp_adapter/backend_client.py`, repository inventory and existing test coverage.
The SQLite database contains only `invTypes`, `industryActivityProducts` and
`industryActivityMaterials`. It does NOT contain `industryActivity` timing or
`industryActivitySkills`. No job-duration or character-feasibility result can
therefore be inferred from the present data alone.

| Existing component | Reuse and boundary |
| --- | --- |
| `api/main.py:get_blueprint_and_materials`, `is_buildable`, `build_tree` | Authoritative material and recursive calculation behavior for activities 1 and 11. Recipe identity includes blueprint AND activity. Existing selection prefers manufacturing when alternatives exist. |
| `build_response`, `cost_status`, `combine_cost_status`, plan collectors | Reuse through existing production HTTP API initially; propagate completeness, depth limits and warnings unchanged. |
| `get_buy_price` | Despite its name, minimum Fuzzwork SELL percentile across four regions, with process cache and no TTL. Not an executable buy-order quote or location-specific material cost. Never relabel it. |
| `evaluate_build_vs_buy` | Existing material-cost comparison with a 95% build threshold. Not a net-profit classifier. Preserve independently of new rankings. |
| `market_response`, `get_market_history`, `market_history_response` | Existing single-item sell orders/history remain intact. History is regional; it does not measure Jita-station sales. |
| `get_manufacturing_context` | Time/slot-related context is not actual job duration or proof of free character slots. |
| `mcp_adapter/*` | Pattern for typed inputs, error propagation, 120-second total timeout and 1 MiB response cap. Existing client permits only two paths; future analytics client must be separate/additive. |
| `tests/test_reactions.py`, `test_cost_completeness.py`, `test_market.py`, `test_history.py`, MCP tests | Compatibility regression baseline; new analytics fixture tests should supplement these. |

Production location arguments currently do not alter production pricing. Fit
costs include fitted items but the root comparison quote covers the root alone;
exclude fits from market-wide rankings. Do not use `api/build_tree.py` as another
calculator: the active HTTP dispatch and contract belong to `api/main.py`.

Two result tiers are necessary:

1. **Indicative:** existing backend cost, disclosed cross-region/freshness limits,
   regional history and target-market revenue estimate. Useful research shortlist.
2. **Execution-qualified scenario:** complete quantities, verified durations,
   scoped depth-priced inputs, explicit expenses, access and feasibility checks.
   Still a snapshot, not a guaranteed transaction or job submission.

Existing cost completeness remains mandatory but is not enough for tier 2.
Return separate `pricing_scope_valid`, `freshness_valid`, `fees_complete`,
`duration_complete`, `recipe_supported` and `execution_checks` fields. Unknown
values are null with reasons, not zero. A candidate can have a complete material
estimate and unknown net profit. Incomplete candidates may appear in a diagnostic
list but cannot win an executable ranking or enter an allocation.

## 2. Architecture and storage

```text
Existing read-only SDE + public ESI + existing production API
             |                      (later private ESI / zKill)
             v
Bounded collectors -> versioned normalized snapshots -> candidate filters
             -> shortlisted production evidence -> metrics / anomaly matching
             -> portfolio planning -> bounded API responses -> MCP -> ChatGPT
```

Proposed future files (none created in this change):

- `analytics/models.py`: typed evidence, provenance, completeness and policies.
- `analytics/catalog.py`: SDE-derived candidates/recipe graph, no cost algorithm.
- `analytics/sources/{esi,production_backend}.py`: acquisition orchestration using
  existing HTTP semantics; regional bulk order ingestion is genuinely missing
  capability, not a replacement for single-item endpoints.
- `analytics/store.py`: snapshot repositories and atomic publication.
- `analytics/{candidates,metrics,anomalies,portfolio,service}.py`: pure decisions.
- `scripts/run_analytics.py`: bounded resumable batch worker and replay command.
- `api/analytics.py`: future separate read-only result handler; no changes to
  `api/main.py` dispatch. Route configuration requires a later reviewed change.
- `mcp_adapter/analytics_client.py`: later compact high-level tool integration.
- `tests/test_analytics_*.py`, `tests/fixtures/analytics/`: deterministic fixtures.
- Later `analytics/character/`, `analytics/sources/zkill.py`, SSO service and
  versioned supplemental SDE timing/skills import, isolated from existing SQLite.

Start with a single Python batch process and separate writable analytics SQLite
on a machine with durable storage. Read bundled industry SQLite read-only.
Do not write snapshots or tokens into that file or git. Public snapshots can be
shared by all users; request-specific scenarios and private evidence cannot.

Minimum public tables: `sde_versions`, `recipes`, `recipe_inputs`, `scan_runs`,
`order_snapshots`, `orders`, `history_daily`, `candidate_evidence`, `results`.
Key orders by (snapshot, region, order_id); recipes by (SDE version, blueprint,
activity, product); history by (region,type,date,source revision). Keep a bounded
retention policy, indexes on scope/type/side/price, and a current-snapshot pointer.
Store each scan's config hash, code revision, source version, cut-off time,
coverage counts, exclusions and warnings. Publish results atomically only after
validation; failure retains the previous snapshot explicitly marked stale.

Vercel request handlers are not durable workers or writable shared SQLite hosts.
Initially prove batch performance offline/on existing hardware; select a durable
worker and read-snapshot delivery mechanism only after measuring scan time,
storage and refresh needs. A single existing host can run SQLite plus a small
read API; hosted serverless reads would require durable shared snapshot storage.
Do not assume an always-on free scheduler or add Redis, Kafka, a paid database or
an additional platform now. Multi-worker/private-data scaling can later justify
PostgreSQL and a durable queue; hide persistence behind repository interfaces.

## 3. Candidate filtering and acquisition

Scan requested regions as a universe, not one recursive HTTP call per item.
Maintain separate manufacturing and reaction cohorts and count survivors at
every stage. A bounded scan may cover a large fraction without claiming all EVE.

1. **Producible universe:** join published marketable `invTypes` with products
   for activity 1/11; require valid output and material rows. Precompute direct
   dependencies, strongly connected components and recipe variants per SDE
   version. Retain alternate recipes but mark those the existing backend cannot
   select as unsupported; do not silently substitute one. Unknown data is a
   diagnostic exclusion. Published/market-group status alone is not demand.
2. **Active market:** ingest all pages of regional public orders once per refresh
   with both sides, group locally by type. Intersect with the SDE candidates.
   Existing sell-only `top` endpoints cannot implement this bulk scanner.
3. **Volume evidence:** fetch cached history only for active candidates, incrementally
   across bounded jobs. Require user/policy minimum observations, traded days,
   units and ISK turnover. Record calendar gaps separately from genuine zero
   volume. Never fill a failed fetch with zero. Maintain calendar-normalized and
   observed-record averages with explicit denominators.
4. **Usable price:** positive, sufficiently fresh depth and valid scope; distinguish
   immediate sale into bids from listing against asks. Filter on quantity-sized
   quotes rather than one cheap unit; flag outlier prices for review.
5. **Cheap margin screen:** direct-input approximate batch cost from snapshot
   quotes and SDE quantities, with declared baseline modifiers. Label this an
   estimate, not a second authoritative recursive calculator. Buying intermediate
   goods can overstate cheapest achievable chain cost: do not treat a negative
   direct-input margin as a mathematically safe exclusion of recursive profit.
   Keep a separate potential-chain cohort, stratified sample and exclusion audit
   to measure false negatives. Missing prices go to unknown, not profitable.
6. **Detailed shortlist:** allocate a configured request/time budget across cohorts;
   call existing production API once per canonical item/quantity/modifier set.
   Cache evidence by those inputs, backend revision and fetch time. Fetch time
   is not the age of its cached Fuzzwork prices. Preserve full result internally,
   return compact metrics and references. No monkeypatching its global caches.
7. **Feasibility:** validate recipe, quantities, complete prices, market depth,
   expenses and timing before executable ranking. Character checks come later.
8. **Optional signals:** character fit and zKill enrichment after primary economic
   filters; neither repairs missing cost or establishes a sale probability.

Complexity target: order work proportional to downloaded orders/pages; history
requests proportional to uncached active types; recursive calls capped by an
explicit shortlist budget K. Expose K, coverage and truncated status. Rotate
deferred cohorts across scans so popular groups cannot permanently starve others.

SDE graph persists until its version changes. Order snapshots follow upstream
cache expiry/ETag; history refresh follows response cache metadata, with rolling
reconciliation for revisions. Share in-flight requests; bounded concurrency,
timeouts, byte/page budgets, jitter and resumable checkpoints. A failed order
page invalidates that regional snapshot for execution. Pagination is not atomic:
store acquisition interval, detect duplicate/conflicting orders and page-count
changes, retry within budget or mark inconsistent. Revalidate shortlisted quotes
before a proposed transaction; never claim reservation of depth.

ESI currently uses route-specific floating-window limits; read current headers
and specification rather than hard-code a universal requests/second rate.
Honor Retry-After/429 and legacy error-budget headers/420 where applicable.
Regional market orders have had their own rate-limit group since February 2026;
the announcement notes a five-minute cache. Schedule from completion/expiry,
not synchronized bursts. Sources: [ESI limits][esi-limits], [market rollout][orders-limit].

## 4. Metrics, units and ranking

For a proposed batch: n integer runs, y units/run, Q=n*y actual output,
q<=Q units planned sold, T actual occupied slot-hours, C cash production/input
cost, R(q) sale proceeds before selling charges, F known expenses. Use Decimal
ISK arithmetic and explicit rounding policy. Residual output is inventory, not
realized cash. Recipe rounding must use backend quantities for the actual batch,
not multiply a unit estimate (ceilings make that unsafe).

| Metric | Definition and eligibility |
| --- | --- |
| Gross material surplus | R(Q) - existing material estimate; indicative, before unmodeled expenses. |
| Net batch profit | R(Q)-C-F only if all required costs and full-sale scenario are known. Otherwise null. |
| Margin % | 100*net_profit/R(Q), with R>0; not markup. |
| Capital / ROI | Required upfront cash K; ROI=100*net_profit/K if K>0. Distinguish purchase cash from inventory opportunity cost. |
| Slot-hour/day | net_profit/T; daily equivalent=24*net_profit/T. Not expected realized daily cash. Null without duration. |
| Build duration | Verified base activity duration plus validated skill/facility/blueprint rules and rounding; no speculative constants. Separate elapsed critical path from sum of occupied slots. |
| Sustainable runs/day | min(time capacity, input-supported runs, floor(demand allocation/y), blueprint availability); bottleneck across the full chain. |
| Market volume | Units/day, ISK/day, traded-day fraction, observation coverage, median and lower-volume scenario. History scope always region. |
| Sell-through | q/(participation*demand_rate), where positive; model estimate/range, not a fact. Unknown if regional demand cannot reasonably map to selected hub. |
| Competition | Orders/units at better or equal price, depth bands and concentration. Cannot infer queue position or competitors' intent from one snapshot. |
| Supply cover | Local ask depth / estimated local daily demand, same scope required. A regional-denominator variant must be explicitly labeled regional proxy. |
| Material availability | Sum quantity fillable at approved locations and price ceilings, shortfalls and haul needs; allocate shared orders once per portfolio. |
| Confidence | Categorical evidence: complete/partial/missing, age, coverage, scope, depth, outliers. No invented probability or confidence percentage. |

Immediate liquidation R(q) is cumulative bid-depth revenue for eligible orders.
Listing R(q) is a scenario using an explicit listing price, participation and
sale horizon. Listing charges, sales tax, installation, hauling, blueprint/BPC,
invention and other applicable costs must be user-supplied or calculated later
from validated sources; unknown charges stay unknown. Invention is not currently
modeled: exclude candidates requiring unavailable BPC sourcing from executable
lists, or accept an explicit priced BPC supply assumption.

Existing material totals cannot be made location-correct just by attaching Jita
sale prices. Initially show legacy cost evidence plus separate scoped procurement
quotes. Future revaluation may price the backend's explicit quantities in a
separately named analytics scenario, but cannot change its BUILD/BUY choices or
claim optimal recursive sourcing. A quantity/run-aware shared valuation interface
would need separate approval and parity tests before complete chain optimization.

Use hard eligibility gates first, then Pareto fronts of net profit, slot yield,
capital and sell-through. Default indicative ranking is disclosed gross surplus
with liquidity context; execution ranking may sort slot yield then ROI, subject
to demand caps. Stable ties use type/activity IDs. No opaque weighted score in
v1. Later composite scores must publish weights, transforms and version, preserve
underlying metrics and be evaluated out-of-sample. Detect abnormal margins with
median/MAD relative to the item's own valid historical cost/revenue series;
without that series return 'insufficient baseline', not a fabricated z-score.

## 5. Slot and capital optimization

Inputs: separate manufacturing/reaction slot counts, budget, horizon, production
and sale locations, material source policy, baseline modifiers, availability
windows, fees and demand participation assumptions. User-provided counts are
assumptions until character data exists. Ask whether the objective is accounting
profit on eventual sale or cash realized within the horizon; default report both
scenarios and never call produced inventory realized profit.

First implement a deterministic incremental-batch heuristic, not an unqualified
optimizer: rank feasible marginal batches, place each on the earliest compatible
slot, reserve inputs/capital and consume product demand capacity, reprice depth,
then repeat until nothing positive/feasible fits. Compare several orderings
(slot yield, profit, ROI) and perform bounded swap improvements. Report
`solution_method=heuristic`, no optimality claim, residual budget/slots and why
items were excluded. Repeated orders, common materials and correlated products
must share global capacities, not independent per-item allocations.

Absorption cap for product i over H days is floor(alpha_i * D_i * H), less own
existing sell inventory and planned completions when known; alpha is a disclosed
scenario input, not an ESI fact. Apply cohort concentration caps for substitutes
and related doctrine items. Conservative demand scenarios must reduce allocations
rather than merely lower displayed scores. Model sales only after production and
hauling completion. No immediate capital recycling based on hypothetical sales.

Add bounded mixed-integer scheduling after heuristic fixtures and performance
justify it. Integer variables represent batch/start/slot assignments; constraints
enforce one overlapping job per slot, activity compatibility, horizon completion,
BPC run limits, material balance, precedence, order-depth segments, demand caps
and nonnegative cash each time bucket. Maximize scenario realized profit with
explicit unsold-inventory valuation (zero cash credit by default). A simple
sum(T*x)<=N*H constraint is necessary but insufficient to prove a schedulable
portfolio. Return solver status, timeout and optimality gap if available.

V1 scheduling buys intermediates and schedules only eligible final jobs; mark
recursive in-house scheduling unsupported. Later chain scheduling expands the
backend graph, batches shared intermediates, assigns activity-specific slots,
enforces completion before consumption and includes every upstream slot-hour.
Never charge only final-job time for an in-house reaction/manufacturing chain.

## 6. Market anomalies

Use the same all-side snapshots; do not add a second ingestion stream.
For each type/scope construct ask/bid depth curves, not just best prices.

- Crossed book: highest eligible bid >= lowest ask is a theoretical flag.
  Match quantities incrementally at actual locations, respecting minimum volume,
  remaining quantity and buy-order range. Remove consumed depth globally.
- Compressed spread: (ask-bid)/midpoint, with positive midpoint, depth and age;
  low spread is not automatically profit after charges.
- Regional arbitrage: ask source versus bid destination, shipment volume/capacity,
  route/security constraints, travel time and explicit costs. Unknown access or
  haul cost prevents execution qualification. Compare timestamps and quote age.
- Abnormal production margin: require matching cost basis and historical baseline;
  stale/partial price changes are data anomalies before economic opportunities.
- Thin supply: depth relative to scoped/proxy volume and concentration; distinguish
  a genuine shortage from one overpriced listing or a rarely traded item.

Matched gross spread=sum(q_l*(bid_l-ask_l)); net spread subtracts all supplied
transaction/transport expenses. Never assume zero taxes, broker fees, relisting
or hauling. Return theoretical quantity, qualified quantity, gross spread,
nullable net spread, exact order/location IDs, acquisition timestamps and failed
execution checks. A crossed regional book may simply reflect unreachable order
range, inaccessible structures, minimum volume or noncontemporaneous pages.
No tool places orders. Public-book coverage excludes private structure depth
that is not actually present in the fetched data.

## 7. Future character-aware analysis and EVE SSO

SSO is a separate future account service, not another public tool argument.
Use the current EVE authorization-code flow, state/PKCE as appropriate to the
registered client, validated issuer/audience/signature/expiry and server-side
refresh management. EVE character identity is not the application's user identity.
Derive linked character from verified token claims, not a user-supplied ID.
See [EVE SSO documentation][sso]; recheck endpoint scopes in the [ESI explorer][explorer]
before implementation. The following are planned scope requirements to verify
against the then-current OpenAPI, not scopes requested in this change.

| Private data / proposed scope | Decision benefit |
| --- | --- |
| Skills: `esi-skills.read_skills.v1` | Required-skill eligibility, validated time/material modifiers and theoretical slot capacity. |
| Blueprints: `esi-characters.read_blueprints.v1` | Actual blueprint identity/location, ME/TE, BPO/BPC and remaining copy runs; concurrent use constraints. |
| Assets: `esi-assets.read_assets.v1` | Owned inputs at accessible locations; cash reduction without zeroing opportunity cost. |
| Industry jobs: `esi-industry.read_character_jobs.v1` | Occupied slots, availability times, queued output and input reservations; handle job status and snapshot delay. |
| Wallet: `esi-wallet.read_character_wallet.v1` (optional) | Budget ceiling; manual budget suffices initially and is not permission to spend all wallet ISK. |
| Character orders: `esi-markets.read_character_orders.v1` (optional) | Existing competing inventory, capital already committed and absorption deductions. |

Minimum multi-user model: accounts -> character_links(account_id,character_id,
owner identity) -> oauth_grants(link_id,scopes,encrypted_refresh_token,expiry,
revoked_at) -> private_snapshots(link_id,scope,as_of,payload_ref). Add profiles,
reservations and plans keyed by account/link plus snapshot versions. An account
can link several characters; any sharing must be explicit. Store secrets encrypted
with keys outside DB/git, never in logs, MCP responses or model context. Enforce
tenant authorization on every read/cache lookup. Serialize refresh per grant,
handle rotation/revocation, delete private snapshots on unlink per retention policy.

Available slots = validated skill-derived capacity minus jobs active over the
planning interval, separately by activity, then constrained by facility access.
Skills/jobs do not alone prove facility usability or blueprint access. Derive
future slots from expected completion and include snapshot uncertainty. Corporate
assets/jobs, structure access and roles are later scope expansions, not minimum
requirements. Private MCP calls will require secure account association before
release; the current no-auth public MCP is not sufficient for tenant identity.

## 8. zKillboard demand enrichment

Use destroyed victim hull counts and destroyed item quantities (including nested
cargo where present), separately from dropped quantities that may re-enter supply.
Count each killmail once; never count attacker fittings as destroyed demand.
Aggregate type/day/region and optional conflict/co-occurrence cohorts. Measure
trends versus the same item's baseline, geography concentration and lagged
relationships to market volume; require minimum samples and confidence bands.
Doctrine inference is a labeled hypothesis from repeated co-occurrence, not proof
of fleet plans. Geographic destruction does not identify the replacement market.

Missing/unreported losses, delayed uploads, reprocessing and changed coverage
limit inference. Store killmail event time separately from ingestion time, update
aggregates idempotently by killmail ID, and recompute corrected buckets. Do not
add kill counts directly to ESI volume: replacement trades may already be counted.
Initially display enrichment only; enable a bounded ranking contribution only
after time-split backtests show incremental value over market-only baselines.
It must never override negative verified economics or missing prices.

Current usage rules checked 2026-09-07: use descriptive User-Agent, compression,
cache and spacing; API paths require trailing slashes. Query responses use a
one-hour client cache and may return JSON errors with successful HTTP status.
R2Z2 permits up to 15 requests/second/IP; wait at least six seconds after 404,
and files remain at least 24 hours. These R2Z2 limits are not a universal REST
quota. Prefer daily raw archives for batch analysis; use a checkpointed R2Z2
consumer only if freshness justifies it. Bound downloads, back off on errors and
recheck policy before launch. Source: [current zKillboard API][zkill]. The old wiki
redirects readers here; do not implement the retired RedisQ design.

## 9. Proposed API and MCP contract

Four future high-level read-only tools, with thin typed translation to additive
backend routes. Do not add these now or expose ingestion loops to ChatGPT.

| Capability / proposed route | Inputs | Output |
| --- | --- | --- |
| `find_manufacturing_opportunities` / GET `/analytics/opportunities?activity=manufacturing` | Region/system/location IDs, budget, horizon, material/fee profile, min volume, rank metric, limit/cursor, snapshot ID | Ranked batches with production evidence reference, metrics, missing data, exclusion counts and coverage. |
| `find_reaction_opportunities` / same route with activity=reaction | Same, reaction-specific profile | Same envelope with reaction identities; do not imply manufacturing slot interchangeability. |
| `optimize_industry_slots` / POST `/analytics/plans/evaluate` | Manufacturing/reaction counts, budget/horizon, eligible candidate set/snapshot, availability and demand policy, optional authorized profile | Schedule, batch quantities, cash timeline, aggregate demand/material use, unsold inventory, bottlenecks, scenario assumptions and solution status. POST computes only; no in-game writes. |
| `find_market_anomalies` / GET `/analytics/anomalies` | Source/destination scopes, kinds, quantity/capital limits, expense/route policy, limit/cursor | Matched depth evidence and theoretical versus qualified status, not raw regional books. |

Common response: `schema_version`, `analysis_id`, `snapshot_id`, `as_of`,
`source_intervals`, `scope`, `assumptions`, `policy_version`, `coverage`,
`status` (ready/stale/partial/unavailable), `warnings`, `items`, `next_cursor`.
Each result includes type/activity/recipe, quantity/runs, price basis, metric
units, nullable values, `cost_complete`, `missing_prices`, `incomplete_reasons`,
execution gates and evidence IDs. Preserve existing backend warnings verbatim
alongside added analytical warnings. Quantity shortfalls are not missing-price
names; represent them separately. Missing timing is not a zero-duration job.

Bound inputs, page sizes and compute; query precomputed snapshots, not thousands
of live calls. Long planning work needs a bounded internal job with an opaque
continuation token returned by the same capability, quota and expiry; no promise
of background completion without a durable worker. Cache public identical queries
and authorize private tokens. Reject arbitrary upstream URLs and private profile
IDs without ownership. Errors return structured non-success status; no failed
scan may become an empty successful recommendation. Keep current five MCP tools
and deployments untouched until a separate API/MCP release is approved.

## 10. Implementation roadmap and acceptance gates

1. **Snapshot foundation + market-wide candidate scanner.** Add catalog/store and
   bounded regional order/history acquisition. Acceptance: fixture replay yields
   identical candidates; page failure/staleness explicit; no recursion before
   shortlist; report counts, bytes, requests, peak memory and elapsed time. Start
   with one chosen region, expand coverage only within measured resource budget.
2. **Indicative manufacturing/reaction ranking.** Existing backend shortlist
   evidence, null-safe metrics and scope labels; test direct and recursive missing
   prices, batch output rounding, recipe ambiguity, gaps and outliers. Then add
   supplemental versioned duration/required-skill data and validated fee/scoped
   procurement scenarios as a gate for executable rankings. Do not change the
   existing production calculator to make a metric appear available.
3. **Anomaly scanner.** Reuse both-side snapshots. Acceptance: a crossed spread
   blocked by location/range/minimum volume/fees is never qualified; consume depth
   once; show timestamps, partial books and explicit hauling assumptions.
4. **Slot heuristic, then optional integer scheduling.** Only qualified inputs;
   start final jobs with purchased intermediates. Acceptance: slot overlaps,
   budget at every time, demand capacity and common-material depth never exceeded;
   zero feasible jobs is valid. Small exhaustive fixtures benchmark heuristic gap.
   Add recursive chain scheduling only after quantity/time parity gates.
5. **SSO and minimal private snapshots.** Separate tenant/account service; manual
   budgets first. Acceptance: cross-account denial, token revocation/rotation,
   missing-scope behavior and no secret exposure. No in-game job submission.
6. **Character-aware rankings/portfolios.** Skill eligibility, BPC runs, assets,
   facility confirmation and existing jobs/orders. Compare manual and linked
   profiles on the same frozen snapshots; disclose stale character evidence.
7. **zKill signals.** Offline archives first, coverage/deduplication tests and
   event-time backtest; ranking contribution only after measured improvement.

All stages require existing reaction/history/completeness/backend tests to remain
green, plus analytic tests using synthetic labeled values (not invented live EVE
prices). Backtests use only information available at the historical cut-off;
include fees, delayed sale scenarios and survivorship/selection bias. Do not
treat backtest profitability as guaranteed future profit. Shadow-mode outputs
precede user-facing recommendations. Review model calibration, false exclusions,
fill assumptions and refresh costs before broadening scale.

## 11. Risks and unresolved decisions

- Main blocker: existing price freshness/scope and absent timing/skill tables.
  This design intentionally permits an indicative release while withholding net
  slot optimization. A source-of-truth calculator upgrade is a separate decision.
- Need current SDE provenance/build process and compatible supplemental dataset;
  blueprint alternate selection, invention/BPC costs and multi-output recipes
  require explicit support policy. Never count full input cost or outputs twice.
- Need operator-selected initial markets, fee/facility profiles, horizon, budget,
  acceptable data age and absorption assumptions. Do not silently choose EVE rates.
- No atomic regional order snapshot, guaranteed listing fill, accessible-structure
  inventory, or observed hub-specific history. Revalidation reduces but cannot
  eliminate execution risk. Thin books are manipulation-sensitive.
- Persistent serverless ingestion and private tokens need a durable storage/worker
  decision. Benchmark first; no paid/free-tier capacity is assumed.
- Public data are shared, private scenarios isolated. Authenticated character
  analysis is blocked until application identity and token storage exist.
- Existing README/GPT snapshots have historical text; use implementation contract
  and code for behavior. This task does not repair GPT instructions or distribution.

## Sources checked

[esi-limits]: https://developers.eveonline.com/docs/services/esi/rate-limiting/
[orders-limit]: https://developers.eveonline.com/blog/market-orders-rate-limit-rolls-out-on-february-24-2026
[sso]: https://developers.eveonline.com/docs/services/sso/
[explorer]: https://developers.eveonline.com/api-explorer
[zkill]: https://zkillboard.com/api/docs/

Repository evidence: [implemented API contract](api-contract.md),
[production and HTTP implementation](../api/main.py),
[MCP backend client](../mcp_adapter/backend_client.py),
[reaction regression tests](../tests/test_reactions.py),
[completeness regression tests](../tests/test_cost_completeness.py).

