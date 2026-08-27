# Claude Code Master Specification
## Production-Grade Revenue Intelligence & Sales Opportunity Engine

> **Primary execution instruction**
>
> Upgrade the existing sales-analysis application into a production-grade **Revenue Intelligence System** that converts raw transaction data into ranked, explainable, measurable sales actions.
>
> **Do not stop after producing a plan.** First inspect the repository and document the current state, then continue through implementation, migrations, tests, backfills, APIs, UI, documentation, and validation. Pause only for an irreversible production-data operation, missing secret/credential that cannot be substituted locally, or a genuinely ambiguous business rule that would materially change financial results. For ordinary technical ambiguity, choose the safest production-quality default, record the decision, and proceed.

---

# 1. Mission

The existing system must evolve from a file-based sales reporting tool into an **action-first commercial decision engine**.

The final product must answer, for every business day:

1. **Which customer should be contacted?**
2. **What product, category, service, or bundle should be proposed?**
3. **Why is this opportunity relevant now?**
4. **When should the action happen?**
5. **Which channel should be used?**
6. **Is an incentive necessary? If yes, what is the minimum effective incentive?**
7. **What revenue, gross profit, and incremental gross profit can reasonably be expected?**
8. **How confident is the system?**
9. **How will the action and its outcome be measured?**
10. **Did the action truly create incremental value, or would the purchase have happened organically?**

The central output is not a collection of charts. It is a prioritized **Opportunity Inbox** and a closed-loop measurement system.

A representative output should look like this:

| Priority | Customer | Opportunity | Target | Why now | Recommended action | Offer | Channel | Expiry | Expected revenue | Expected incremental gross profit | Confidence |
|---:|---|---|---|---|---|---|---|---|---:|---:|---:|
| 1 | Customer A | Replenishment | Belcando Adult Lamb & Rice 12.5 kg | Typical cycle 46 days; 44 days since last purchase | Send personalized reminder | No discount | WhatsApp | 3 days | 27,000,000 Toman | 4,150,000 Toman | 0.86 |
| 2 | Customer B | Cross-sell | Hairball supplement | Similar customers add this within 21 days | Recommend complementary product | Bundle | Sales call | 7 days | 1,850,000 Toman | 510,000 Toman | 0.74 |
| 3 | Customer C | Win-back | Premium cat food | Customer is 1.8 personalized cycles overdue | Call with service recovery script | 7% only if needed | Call | 5 days | 8,200,000 Toman | 1,230,000 Toman | 0.69 |

All calculations must be traceable to source data, model version, feature snapshot, and business assumptions.

---

# 2. Known Context — Verify in the Repository Before Changing Anything

The current application is understood to have some or all of the following characteristics. Treat these as starting context, not as permission to assume implementation details without inspecting the code:

- Backend based on **FastAPI**.
- Frontend based on **Next.js**, previously observed around version 16.x.
- A scheduler or folder-monitoring workflow that reads newly added sales files.
- Excel ingestion involving `.xls`, `.xlsx`, and `.xlsb` files.
- Prior use of `pyxlsb` for binary Excel files.
- Redis and Docker may exist, but Docker may previously have been used mainly for testing rather than as a proven production deployment.
- Source code is expected to be in Git/GitHub.
- The business may initially be single-tenant, but the data model must be **tenant-ready** by carrying `business_id` through all domain records.
- The primary business domain is pet retail and services, with branches such as Heravi and Tajrish and products for cats and dogs. Do not hardcode those branches or species as the only supported values.

Before implementation, inspect:

- Repository tree, active branches, package managers, lockfiles, environment files, CI workflows, database layer, migrations, queue/scheduler, current import pipeline, frontend architecture, tests, and deployment configuration.
- Existing naming conventions and domain objects.
- Whether a real database already exists and which parts are currently persisted.
- Whether imports currently operate at invoice level or order-line level.
- How customers, products, phone numbers, returns, discounts, branches, and payment methods are represented.
- Whether the system already has authentication, authorization, audit logs, or organization boundaries.

Do not replace working infrastructure merely to match this document. Extend the existing architecture when it is sound. Refactor only when the current implementation blocks correctness, reliability, or the required closed-loop analytics.

---

# 3. Non-Negotiable Engineering Rules

## 3.1 Production, not a prototype

The result must be executable, testable, migration-safe, and maintainable. It must not be a toy dashboard, notebook-only analysis, static mockup, or demo with fake recommendations.

Do not ship:

- Placeholder API responses.
- Hardcoded customer or product IDs.
- Recommendations generated from random values.
- UI cards that are not backed by persisted calculations.
- A model without temporal validation.
- “Incremental revenue” values inferred from attribution alone.
- Business-critical calculations that exist only in frontend code.
- Silent data coercion or discarded rows.
- A destructive migration without a verified rollback path.

## 3.2 Preserve and improve the current product

- Audit the current system before modifying it.
- Reuse current patterns where they are correct.
- Maintain backward compatibility for existing imports and reports unless a versioned migration is explicitly implemented.
- Keep old output available during the transition so results can be compared.
- Implement feature flags for newly introduced opportunity modules.

## 3.3 No “plan-only” stopping behavior

Create the current-state audit and implementation plan, but continue implementation after writing them. Maintain a live checklist in:

`docs/revenue-intelligence/IMPLEMENTATION_STATUS.md`

Every task must be marked as one of:

- `not_started`
- `in_progress`
- `implemented`
- `validated`
- `blocked` with a concrete reason

Do not mark a phase complete merely because code exists. Completion requires tests, migration verification, backfill, API exposure, UI integration where applicable, and documentation.

## 3.4 Financial correctness

- Internally store money in the smallest reliable integer unit or in a fixed-precision decimal type. Never use binary floating-point for persisted financial amounts.
- Explicitly track currency and unit, especially the distinction between **Rial and Toman**.
- Separate gross sales, net sales, tax, discount, refund, cost of goods sold, gross profit, and contribution profit.
- Never count cancelled, voided, or fully returned lines as realized revenue.
- Partial returns must reverse the corresponding quantity, revenue, cost, and margin.
- Historical cost must be based on the best available cost basis at transaction time, not blindly on the latest supplier price.
- Any imputed cost must be identified as imputed and assigned a confidence level.

## 3.5 Explainability and auditability

Every generated opportunity must be reconstructable from:

- Source import batch IDs.
- Relevant order and order-line IDs.
- Feature snapshot timestamp.
- Model or rule version.
- Score components.
- Assumptions and fallback levels.
- Evidence displayed to the operator.

The UI must never show a recommendation without a “Why this?” explanation.

## 3.6 Causal honesty

The system must distinguish among:

- `predicted_revenue`
- `attributed_revenue`
- `incremental_revenue`
- `predicted_gross_profit`
- `incremental_gross_profit`

A recommendation model can estimate purchase probability. It cannot automatically claim causal lift. Incremental impact must be based on randomized holdouts, credible quasi-experimental analysis, or a validated uplift model trained from treatment/control data.

When causal evidence is unavailable, label the value as a **forecast or heuristic opportunity value**, never as proven incremental impact.

---

# 4. Product Outcome and North-Star Metrics

The product must optimize **incremental gross profit**, not vanity metrics and not raw attributed revenue.

Primary business metrics:

1. Incremental gross profit per 1,000 contacted customers.
2. Incremental gross profit per campaign and per opportunity type.
3. Opportunity acceptance rate by operators.
4. Contact-to-purchase conversion uplift versus holdout.
5. Average order value uplift versus matched baseline or control.
6. Repeat purchase rate and churn reduction.
7. Revenue recovered from dormant customers.
8. Gross-margin expansion through cross-sell, upsell, and pricing.
9. Percentage of recommendations that were fulfillable at the relevant branch.
10. Percentage of sent offers that gave unnecessary discount to customers who would likely have purchased at full price.

Supporting model metrics:

- Precision@K and gross-profit-weighted Precision@K.
- Recall@K where operationally relevant.
- Calibration error and Brier score for probabilities.
- PR-AUC for imbalanced classification.
- Ranking NDCG weighted by realized gross profit.
- Time-dependent concordance for survival models.
- Qini/uplift curves for treatment-effect models.
- Stability and drift metrics across time, branch, channel, and segment.

Do not optimize a model solely for ROC-AUC when the business consumes only the top-ranked actions.

---

# 5. Required Repository Audit

Create:

`docs/revenue-intelligence/CURRENT_SYSTEM_AUDIT.md`

The audit must contain:

## 5.1 Architecture inventory

- Backend modules and request flow.
- Frontend routes and state/data-fetching architecture.
- Database technology, schema, migrations, indexes, and connection lifecycle.
- Background jobs, scheduler, queue, Redis usage, and retry behavior.
- File watcher and import behavior.
- Authentication and authorization.
- Logging, monitoring, CI, and deployment.

## 5.2 Data inventory

For every existing source file or table:

- Source name.
- Granularity.
- Primary and candidate keys.
- Date fields.
- Customer identifiers.
- Product identifiers.
- Quantity and amount fields.
- Discount and return semantics.
- Branch/channel/payment fields.
- Known nulls and malformed values.
- Unit assumptions.
- Duplicate behavior.

## 5.3 Gap analysis

Map existing capabilities against every requirement in this document and classify each item as:

- Already exists and is correct.
- Exists but must be refactored.
- Missing.
- Blocked by unavailable source data.

## 5.4 Migration strategy

Document how current users and historical data will move to the new canonical model without losing existing functionality.

After writing the audit, proceed with implementation.

---

# 6. Target Architecture

Implement a modular architecture with these layers:

```text
Raw files / APIs / manual imports
                ↓
      Immutable ingestion layer
                ↓
 Validation, normalization, mapping, quarantine
                ↓
       Canonical commercial model
                ↓
 Identity resolution + product resolution
                ↓
   Feature computation and feature snapshots
                ↓
 Models + deterministic business rules
                ↓
       Opportunity generation engine
                ↓
 Constraint, eligibility, margin, stock, and policy filters
                ↓
       Expected-value ranking engine
                ↓
 Opportunity Inbox / exports / campaigns / assignments
                ↓
 Action, exposure, outcome, and control-group logging
                ↓
 Attribution + incrementality + model feedback loop
```

## 6.1 Preferred operational choices

Use the current stack where viable. When a required component is absent, use these defaults:

- **System of record:** PostgreSQL.
- **Schema migration:** Alembic or the migration tool already used by the backend.
- **API:** FastAPI with versioned REST endpoints and generated OpenAPI.
- **Durable background execution:** existing queue if sound; otherwise Celery with Redis broker/backend and Celery Beat for schedules.
- **Frontend:** existing Next.js application, TypeScript, server-side data fetching where appropriate, and a strict typed API client.
- **Model artifacts:** versioned artifact store behind an interface; local filesystem in development and object storage compatibility for production.
- **Feature persistence:** versioned relational feature tables/materialized views before introducing an external feature-store platform.
- **Analytics transforms:** SQL plus Python pipelines; do not create notebook-only logic.

Do not run file imports, model training, or large scoring jobs inside the FastAPI request process.

## 6.2 Module boundaries

At minimum, isolate:

```text
backend/
  ingestion/
  normalization/
  identity/
  catalog/
  commercial/
  features/
  models/
  opportunities/
  experiments/
  campaigns/
  attribution/
  analytics/
  api/
  workers/
  observability/
```

Adapt names to the repository’s conventions, but preserve separation of responsibilities.

---

# 7. Canonical Data Model

The exact ORM names may differ, but the semantic model must support the entities below.

## 7.1 Core organization and import entities

### `businesses`

- `id`
- `name`
- `default_currency`
- `money_unit` such as `rial` or `toman`
- `timezone`
- `created_at`

### `branches`

- `id`
- `business_id`
- `name`
- `code`
- `timezone`
- `active`

### `source_systems`

- `id`
- `business_id`
- `name`
- `source_type`
- `mapping_version`
- `configuration_json`

### `import_batches`

- `id`
- `business_id`
- `source_system_id`
- `original_filename`
- `content_hash`
- `received_at`
- `started_at`
- `completed_at`
- `status`
- `row_count`
- `accepted_count`
- `quarantined_count`
- `duplicate_count`
- `mapping_version`
- `parser_version`
- `error_summary_json`
- `source_period_start`
- `source_period_end`

Use content hashes and natural-source identifiers to make imports idempotent.

### `import_rows_raw`

Persist an immutable representation or durable reference for each imported row:

- `import_batch_id`
- `row_number`
- `raw_payload_json`
- `row_hash`
- `parse_status`
- `error_codes_json`

Raw imported data must remain auditable even after normalization rules change.

### `import_quarantine`

- `import_batch_id`
- `row_number`
- `raw_payload_json`
- `reason_code`
- `reason_detail`
- `suggested_resolution`
- `resolved_at`
- `resolved_by`

## 7.2 Customer and identity entities

### `customers`

- `id`
- `business_id`
- `display_name`
- `status`
- `first_purchase_at`
- `last_purchase_at`
- `created_at`
- `merged_into_customer_id`

### `customer_identifiers`

Support multiple identifiers per customer:

- `id`
- `business_id`
- `customer_id`
- `identifier_type`: phone, email, loyalty_id, source_customer_id, normalized_name_address, etc.
- `normalized_value`
- `value_hash`
- `is_primary`
- `verified`
- `source_system_id`
- `confidence`

Do not use phone number alone as an irreversible identity truth. Preserve merge provenance and permit unmerge/review.

### `customer_contacts`

- normalized phone/email
- channel consent status
- do-not-contact status
- opt-in source and timestamp
- last successful contact
- invalid/bounced status

### `customer_households` and `pets` — optional but first-class when data exists

For pet retail, support:

- Species.
- Breed.
- Sex.
- Birth date or age range.
- Weight.
- Life stage.
- Neutered status.
- Dietary constraints.
- Allergies/sensitivities.
- Chronic conditions only when lawfully and appropriately collected.
- Preferred food form and brand.

Never infer these as certain facts from one purchase. Store inferred values separately with confidence and evidence.

## 7.3 Product and catalog entities

### `products`

- `id`
- `business_id`
- `sku`
- `barcode`
- `canonical_name`
- `brand_id`
- `category_id`
- `species_compatibility`
- `life_stage_compatibility`
- `package_size`
- `package_unit`
- `product_form`
- `active`
- `discontinued_at`

### `product_aliases`

Map inconsistent source descriptions to canonical products:

- `raw_name_normalized`
- `source_system_id`
- `product_id`
- `match_method`
- `confidence`
- `approved_by`

### `brands`, `categories`, and `category_hierarchy`

Categories must support parent/child relationships and stable IDs. Do not rely on display text as a key.

### `product_compatibility_rules`

Support hard exclusions and soft recommendations:

- incompatible species.
- inappropriate life stage.
- mutually exclusive product types.
- substitution relationships.
- complementary relationships.
- service eligibility rules.

## 7.4 Commercial transaction entities

### `orders`

- `id`
- `business_id`
- `source_order_id`
- `customer_id`
- `branch_id`
- `channel_id`
- `salesperson_id`
- `ordered_at`
- `status`
- `currency`
- `money_unit`
- `gross_amount`
- `discount_amount`
- `tax_amount`
- `net_amount`
- `refund_amount`
- `payment_method`
- `import_batch_id`

### `order_lines`

- `id`
- `order_id`
- `product_id`
- `raw_product_description`
- `quantity`
- `unit_list_price`
- `unit_selling_price`
- `line_discount_amount`
- `line_tax_amount`
- `line_net_amount`
- `unit_cost_at_sale`
- `line_cogs`
- `line_gross_profit`
- `cost_confidence`
- `promotion_id`
- `returned_quantity`

The canonical analytical grain must be order line, even when the source only provides invoice-level exports.

### `returns`

Persist return events rather than merely editing original transactions:

- original order/line reference.
- return timestamp.
- quantity.
- refund amount.
- reason.
- restock status.

### `payments`

Support split payments and payment providers when available.

## 7.5 Cost, price, inventory, and promotion entities

### `supplier_cost_history`

- product.
- supplier.
- effective timestamp.
- cost.
- quantity tier.
- freight/landed-cost components if available.
- source invoice.

### `price_history`

- product.
- branch/channel.
- list price.
- effective interval.

### `inventory_snapshots`

- product.
- branch.
- on-hand.
- reserved.
- available.
- snapshot timestamp.

### `promotions`

- promotion type.
- eligibility.
- start/end.
- affected products.
- discount economics.
- funding source.

## 7.6 Action and learning entities

### `opportunities`

Required fields:

- `id`
- `business_id`
- `customer_id`
- `opportunity_type`
- `target_product_id`
- `target_category_id`
- `target_service_id`
- `generated_at`
- `valid_from`
- `expires_at`
- `status`
- `eligibility_status`
- `recommended_channel`
- `recommended_offer_id`
- `recommended_action`
- `score`
- `rank`
- `purchase_probability_baseline`
- `purchase_probability_if_contacted`
- `estimated_treatment_effect`
- `expected_revenue`
- `expected_gross_profit`
- `expected_incremental_revenue`
- `expected_incremental_gross_profit`
- `incentive_cost`
- `channel_cost`
- `confidence`
- `urgency`
- `evidence_json`
- `reason_codes_json`
- `feature_snapshot_id`
- `generator_type`
- `generator_version`
- `model_run_id`
- `supersedes_opportunity_id`

Nullable causal fields must remain null when causal evidence does not exist. Do not fill them with predicted revenue.

### `opportunity_actions`

- opportunity.
- action type.
- assigned operator.
- action timestamp.
- status.
- actual channel.
- actual offer.
- message/script version.
- operator notes.

### `campaigns`, `campaign_memberships`, and `exposures`

Every customer exposed to a campaign or recommendation must receive an immutable exposure record. Control-group membership must also be recorded.

### `outcomes`

- exposure/action reference.
- customer.
- outcome type.
- order/line reference.
- timestamp.
- attribution window.
- attributed revenue/profit.
- incremental estimate where available.

### `experiments`

- hypothesis.
- treatment arms.
- randomization unit.
- eligibility population.
- primary metric.
- guardrail metrics.
- start/end.
- analysis plan.
- status.

### `model_runs` and `feature_snapshots`

Persist training period, code version, data hash, parameters, metrics, calibration artifact, feature schema, drift baseline, and promoted status.

---

# 8. Import, Normalization, and Data-Quality Engine

This is foundational. Do not build sophisticated models on silently corrupted Excel data.

## 8.1 Supported files

Maintain and test support for:

- `.xlsx`
- legacy `.xls`
- `.xlsb`
- CSV when useful

Select the parser based on file signature and format, not only extension. Reject password-protected or structurally invalid files with a clear error.

## 8.2 Schema mapping

Implement source-specific, versioned mappings rather than scattering column aliases through code.

A mapping should define:

- Header aliases.
- Required and optional fields.
- Data types.
- Date parsing rules.
- Currency and money-unit rules.
- Quantity rules.
- Status mappings.
- Order and customer key extraction.
- Product resolution strategy.

Create a mapping-preview UI or API that shows:

- Detected sheet.
- Detected headers.
- Sample rows.
- Proposed canonical mapping.
- Validation errors.
- Money-unit interpretation.

## 8.3 Persian and Excel normalization

Implement and test:

- Persian and Arabic digit conversion.
- Arabic/Persian character normalization such as `ي/ی` and `ك/ک`.
- Removal or controlled handling of LRM, RLM, ZWNJ, non-breaking spaces, zero-width characters, and hidden Excel artifacts.
- Trim and whitespace collapsing.
- Phone normalization for Iranian numbers, including `09...`, `989...`, `+989...`, spaces, punctuation, and Excel numeric/scientific notation.
- Preservation of leading zeroes.
- Jalali and Gregorian date parsing with explicit timezone handling.
- Thousands separators and locale-specific decimal marks.
- Rial/Toman detection and explicit operator confirmation when inference is ambiguous.

## 8.4 Idempotency and duplicate control

An identical file must not duplicate transactions when imported twice.

Use a layered strategy:

1. File content hash.
2. Source-system + source-order ID.
3. Source-system + invoice number + timestamp + customer + amount.
4. Order-line row hash for sources without stable IDs.

Do not silently delete suspected duplicates. Store duplicate decisions and confidence.

## 8.5 Data quality score

For each batch, calculate and expose:

- completeness.
- validity.
- uniqueness.
- product match rate.
- customer identifier rate.
- cost coverage.
- branch coverage.
- return/status clarity.
- date-range consistency.

Provide blocking and non-blocking rules. Financially dangerous issues such as unknown money unit, reversed signs, or impossible totals must block canonical posting until resolved.

## 8.6 Reconciliation

For every batch, reconcile:

- Sum of canonical order-line gross/net values against source totals.
- Order count.
- Customer count.
- Product count.
- Discounts.
- returns/refunds.

Persist reconciliation results and make them visible in the UI.

---

# 9. Identity Resolution

Customer and product resolution must be deterministic first, probabilistic second.

## 9.1 Customer identity strategy

Apply in order:

1. Exact verified source customer ID.
2. Exact normalized verified phone/email.
3. Existing approved identifier link.
4. High-confidence composite match using name plus address or other stable fields.
5. Probabilistic candidate requiring review.

Never automatically merge on name alone.

Store:

- match method.
- confidence.
- evidence.
- merge history.
- manual override.

## 9.2 Product resolution strategy

Apply:

1. Exact SKU/barcode.
2. Approved source alias.
3. Normalized exact name plus package size/brand.
4. Fuzzy candidate constrained by brand, category, package size, and species.
5. Manual review queue.

Do not allow an uncertain match to contaminate recommendation models as if it were certain. Carry match confidence into feature and opportunity confidence.

---

# 10. Feature Layer and Customer 360

Build versioned, reproducible feature snapshots. Avoid ad hoc calculation inside API endpoints.

## 10.1 Customer-level features

At minimum:

### Value and frequency

- Lifetime gross sales.
- Lifetime net sales.
- Lifetime gross profit.
- Gross margin percentage.
- Order count.
- Active months.
- Average order value.
- Median order value.
- Average and median order gross profit.
- Purchase frequency over 30/60/90/180/365 days.
- Days since first and last purchase.

### Purchase cadence

- Median interpurchase interval.
- Mean interval.
- Median absolute deviation.
- Coefficient of variation.
- Personalized expected next-purchase date.
- Current overdue ratio: `days_since_last / expected_interval`.
- Cadence by product, category, and brand.

### Mix and affinity

- Spend and margin by category, brand, species, life stage, package size, price tier, branch, and channel.
- Category penetration.
- Brand concentration and switching rate.
- Premium versus economy share.
- Consumables versus durable-goods share.
- Service usage.

### Promotion behavior

- Discounted order share.
- Full-price purchase share.
- Average realized discount.
- Purchase probability around prior discounts.
- Coupon redemption behavior.
- Estimated discount dependence, clearly marked observational until experimentally validated.

### Engagement and contactability

- Channel consent.
- Last contact and last successful contact.
- Response rate by channel.
- Contact fatigue.
- Bounce/invalid status.

### Risk and growth

- Lifecycle state.
- Churn risk.
- CLV forecast and confidence interval.
- Revenue expansion gap.
- Future-whale probability.
- Win-back value.

## 10.2 Product-level features

- Unit sales and revenue over time.
- Gross profit and margin.
- Repeat rate.
- Reorder interval distribution.
- Attach rate.
- Substitution and complement scores.
- Price and promotion history.
- Stockout days.
- Return rate.
- Branch availability.
- Customer concentration.
- Lifecycle status and trend.

## 10.3 Customer-product features

- Last purchase date.
- Total quantity and spend.
- Repeat count.
- Typical interval.
- Recency relative to personal cycle.
- Typical package size.
- Average price paid.
- Discount history.
- Affinity score.
- predicted next-purchase probability.

## 10.4 Feature snapshots

A feature snapshot must include:

- `as_of_timestamp`.
- feature schema version.
- source data watermark.
- code commit/version.
- business ID.

Training and scoring must use point-in-time correct features to prevent leakage.

---

# 11. Lifecycle State Engine

Every customer must have one primary lifecycle state with transparent rules or model evidence.

Recommended states:

```text
Prospect / Imported-only
New
Activated
Growing
Established
Loyal
VIP
Slipping
At-risk
Dormant
Lost
Reactivated
```

The state logic must be personalized by category and purchase cadence rather than relying exclusively on a universal 30/60/90-day rule.

Example principles:

- `New`: first purchase within configured period.
- `Activated`: second qualifying purchase completed.
- `Growing`: positive trend in frequency, category breadth, or value.
- `VIP`: high expected future gross profit, not merely high historical revenue.
- `Slipping`: beyond normal personalized cadence but not yet severely overdue.
- `At-risk`: materially beyond expected cadence with meaningful expected future value.
- `Dormant`: prolonged inactivity where win-back remains economically rational.
- `Lost`: extremely low return probability or explicitly churned.
- `Reactivated`: dormant/at-risk customer returned after intervention or organically.

Persist state transitions and reasons. The UI must display a timeline of transitions.

---

# 12. Opportunity Engine — Common Contract

Each opportunity generator must implement a common interface conceptually equivalent to:

```python
class OpportunityGenerator(Protocol):
    name: str
    version: str

    def eligible_population(self, as_of: datetime) -> QuerySet: ...
    def generate(self, as_of: datetime) -> Iterable[OpportunityCandidate]: ...
    def explain(self, candidate: OpportunityCandidate) -> OpportunityEvidence: ...
```

All candidates pass through:

1. Customer eligibility.
2. Contact consent and fatigue rules.
3. Product compatibility.
4. Branch inventory or fulfillability.
5. Product active/discontinued checks.
6. Margin floor.
7. Duplicate/conflict suppression.
8. Existing open-opportunity suppression.
9. Offer-policy validation.
10. Expected-value scoring.
11. Confidence and evidence completeness.

Implement deterministic rule baselines before or alongside ML models. Baselines are required for comparison and fallback.

---

# 13. Replenishment Prediction

This is one of the highest-priority modules for consumable products.

## 13.1 Goal

Predict when a customer is likely to need a repeat purchase and which SKU, package size, category, or acceptable substitute should be offered.

## 13.2 Hierarchical evidence

Use the most specific trustworthy level available:

1. Customer + exact product.
2. Customer + product family/package class.
3. Customer + category.
4. Customer segment + product.
5. Business-wide product/category distribution.

Do not use customer-product cadence when only one purchase exists. Fall back explicitly and lower confidence.

## 13.3 Deterministic baseline

For repeated purchases, estimate the expected interval using robust statistics:

- Weighted median of valid interpurchase gaps.
- Recent intervals may receive higher weight.
- Exclude gaps caused by returns, obvious bulk purchases, or stockout periods where detectable.
- Use median absolute deviation to quantify uncertainty.

A baseline due score may use:

```text
expected_interval = robust weighted interval estimate
elapsed = as_of_date - last_qualifying_purchase_date
overdue_ratio = elapsed / expected_interval
uncertainty = robust dispersion / expected_interval
```

Map the overdue ratio and uncertainty into a probability-like score using a calibrated historical backtest, not an arbitrary display percentage.

## 13.4 Quantity and depletion adjustment

When package size and quantity are known:

- Normalize purchased quantity into comparable units.
- Detect whether a purchase was likely a stock-up event.
- Scale expected duration according to purchased quantity.
- When pet count, pet weight, or feeding rate exists, use it as an additional feature, not as an unverified replacement for observed cadence.

## 13.5 Advanced model

When data volume supports it, benchmark:

- Survival analysis with time-varying covariates.
- Gradient-boosted time-to-event or discrete-time hazard model.
- Recurrent-event modeling for repeat purchases.

The model must handle censoring and be temporally validated.

## 13.6 Outputs

For each recommendation:

- predicted purchase window.
- exact or family-level target.
- confidence interval.
- evidence level used.
- expected revenue and gross profit.
- substitute list constrained by compatibility, availability, and customer price/brand preferences.

Example explanation:

> “This customer bought the 12.5 kg product three times with gaps of 43, 47, and 45 days. It has been 44 days since the last purchase. The recommended contact window is now through the next three days.”

---

# 14. Next-Best-Product and Sequential Purchase Engine

## 14.1 Goal

Predict the product or category most likely to create additional gross profit without recommending irrelevant or incompatible items.

## 14.2 Candidate generation

Combine:

1. Association rules: support, confidence, lift, and conviction.
2. Sequential patterns: what customers buy after a particular event and within what time window.
3. Customer-to-product collaborative affinity.
4. Segment-level category penetration.
5. Curated product compatibility and merchandising rules.
6. Product substitution and replenishment logic.

## 14.3 Avoid common mistakes

- High confidence caused only by a globally popular product is insufficient; inspect lift.
- Do not recommend a product already purchased very recently unless replenishment logic supports it.
- Do not mix cats/dogs or incompatible life stages.
- Do not recommend out-of-stock or margin-negative items.
- Do not infer causality from co-occurrence.
- Do not show ten weak products. Rank a small number of strong actions.

## 14.4 Hybrid ranking

A candidate score should incorporate:

- customer affinity.
- sequential timing relevance.
- complement lift.
- gross-profit potential.
- stock availability.
- compatibility.
- novelty/repetition penalty.
- confidence.
- contact fatigue.

## 14.5 Time-windowed outputs

Examples:

- “Recommend within the same basket.”
- “Recommend 7–14 days after food purchase.”
- “Recommend at next replenishment.”
- “Recommend only after customer enters grooming lifecycle.”

---

# 15. Basket-Building Engine

The system must quantify which additions expand order gross profit, not merely which products often co-occur.

Required analyses:

- Attach rate by anchor product/category.
- Incremental basket value associated with each attachment.
- Gross-profit change.
- Bundle discount cost.
- Cannibalization and substitution risk.
- Branch/channel differences.
- Customer-segment differences.

Generate:

- Cashier/salesperson suggestions.
- Website cart suggestions where integration exists.
- Predefined bundles with minimum margin safeguards.
- Personalized bundle candidates.

Backtest whether a bundle tends to increase gross profit compared with similar baskets without the attachment. Label observational estimates appropriately until experimentally tested.

---

# 16. Churn, Slipping, and Win-Back Engine

## 16.1 Personalized churn definition

Do not define churn only as “no purchase for 90 days.” A customer who normally buys every 20 days is at risk far earlier than one who buys every 120 days.

Construct labels from personalized expected cadence and historical return behavior.

## 16.2 Baseline

Use:

- overdue ratio.
- trend in frequency.
- trend in order value and margin.
- category/brand switching.
- failed contacts.
- returns or service failures.
- recent stockouts for preferred products.
- loss of category breadth.

## 16.3 Advanced model

Benchmark a calibrated tabular model or survival model. Use temporal holdout and exclude post-outcome information.

## 16.4 Win-back economics

Prioritize by expected recoverable gross profit:

```text
win_back_value = probability_of_return_if_contacted
                 × expected_future_gross_profit
                 - offer_cost
                 - channel_cost
                 - expected_service_recovery_cost
```

Until treatment-effect data exists, keep `probability_of_return_if_contacted` as a heuristic forecast and label it accordingly.

## 16.5 Treatment selection

Possible actions:

- reminder with no discount.
- availability notification.
- service recovery call.
- category-specific content.
- small incentive.
- larger incentive only when predicted incremental profit remains positive.

Do not use the same win-back offer for every dormant customer.

---

# 17. Revenue Expansion Gap

## 17.1 Goal

Estimate what a customer is economically likely to buy from the business but currently purchases elsewhere or not at all.

## 17.2 Peer definition

Compare customers using relevant dimensions such as:

- species/pet household.
- life stage.
- spending tier.
- category mix.
- preferred brand/price tier.
- branch/channel.
- tenure and purchase cadence.

Use nearest-neighbor or segment-based comparison only after excluding leakage features and obvious mismatches.

## 17.3 Calculation

For each category:

```text
expected_category_gross_profit_from_similar_customers
- observed_customer_category_gross_profit
= category_expansion_gap
```

Apply:

- eligibility.
- compatibility.
- current stock.
- confidence.
- customer contact and offer cost.

Output the top missing categories and the evidence behind each one.

Do not present the gap as guaranteed revenue. It is a ranked commercial potential estimate.

---

# 18. Future-Whale Detection

## 18.1 Goal

Identify recent customers likely to become top-value customers early enough for proactive retention and service.

## 18.2 Label

Define a future whale using **future gross profit or future CLV percentile**, not historical revenue measured inside the prediction window.

## 18.3 Early features

Examples:

- Time between first and second purchases.
- First-30/60-day frequency.
- Category breadth.
- Premium share.
- Margin quality.
- Full-price purchase behavior.
- Service adoption.
- Responsiveness.
- Branch/channel behavior.

## 18.4 Leakage prevention

At prediction time, use only data available in the early observation window. Validate on later customer cohorts.

## 18.5 Actions

Future-whale actions should emphasize:

- exceptional service.
- proactive replenishment.
- priority access.
- relationship building.
- relevant recommendations.

Do not immediately train these customers to wait for discounts.

---

# 19. Customer Lifetime Value

Implement at least two levels:

## 19.1 Transparent baseline

Forecast future gross profit using:

- recent purchase rate.
- retention probability.
- average gross profit per order.
- category cadence.
- a configurable forecast horizon.

## 19.2 Advanced probabilistic or supervised model

Benchmark a non-contractual CLV model such as BG/NBD or Pareto/NBD plus monetary modeling when assumptions fit. Otherwise benchmark a supervised, temporally validated model.

CLV must be:

- gross-profit based.
- horizon-specific, such as 90/180/365 days.
- accompanied by uncertainty.
- recalculated on a schedule.
- evaluated against realized future gross profit.

Do not use CLV as a static customer label without model version and as-of date.

---

# 20. Offer Sensitivity and Minimum Effective Incentive

## 20.1 Goal

Avoid unnecessary discounting while selecting the smallest incentive likely to create incremental profit.

## 20.2 Required logging before advanced modeling

The system must log:

- Who was eligible.
- Who was contacted.
- Which offer was shown.
- Which channel and message variant were used.
- Who was placed in control.
- Whether and when the customer purchased.
- Margin and discount cost.

## 20.3 Baseline policy

Before sufficient experimental data exists:

- Classify customers by historical full-price behavior.
- Default high full-price propensity customers to no discount.
- Use rule-based incentive ladders with strict margin floors.
- Randomize a small, safe holdout and treatment split to learn.

Never represent observational discount correlation as causal sensitivity.

## 20.4 Advanced treatment-effect model

When randomized or credible treatment/control data is sufficient, benchmark:

- Two-model uplift.
- T-learner/S-learner/X-learner.
- Causal forest or doubly robust estimation.

Predict incremental purchase probability and incremental gross profit for each offer level.

## 20.5 Decision rule

Choose the action with maximum positive expected incremental gross profit:

```text
EIGP(offer, channel) =
    treatment_effect_on_purchase_probability
    × expected_order_gross_profit_before_incentive
    - expected_incentive_cost
    - channel_cost
    - expected_return_cost
    - expected_cannibalization_cost
```

Select “no contact” when every action has non-positive EIGP.

---

# 21. Price Elasticity Engine

Price recommendations are high-risk and require strict data gates.

## 21.1 Required controls

Model quantity or demand while accounting for:

- price.
- promotion.
- seasonality.
- branch/channel.
- stockouts and availability.
- competitor data only if legitimately available.
- product lifecycle.
- holidays/events.
- category trend.

## 21.2 Hierarchical estimation

Sparse SKUs must borrow strength from category/brand levels. Do not calculate a confident SKU elasticity from minimal price variation.

## 21.3 Outputs

- Estimated elasticity and confidence interval.
- Evidence strength.
- Historical price range.
- Simulated volume, revenue, and gross profit under candidate prices.
- Margin and brand guardrails.
- “Insufficient evidence” when data gates fail.

## 21.4 Safety

Price changes must remain recommendations requiring approval unless the current system already has an authorized pricing workflow. Never auto-publish price changes from an unvalidated model.

---

# 22. Campaign Incrementality and Experimentation

## 22.1 Experiment-first campaign system

Every eligible campaign should support:

- Randomized holdout.
- Treatment variants.
- Stratification by key segment when necessary.
- Predeclared primary metric.
- Guardrails.
- Exposure tracking.
- Analysis window.

Default randomization unit is customer or household, not individual message, to avoid contamination.

## 22.2 Metrics

Report separately:

- Sent.
- Delivered.
- Viewed/clicked where available.
- Purchased.
- Attributed revenue.
- Control conversion.
- Treatment conversion.
- Absolute lift.
- Relative lift.
- Incremental orders.
- Incremental revenue.
- Incremental gross profit.
- Cost per incremental order.
- Confidence interval.

## 22.3 Observational fallback

When randomization is impossible, use a documented method such as:

- matched controls.
- difference-in-differences.
- interrupted time series.
- doubly robust adjustment.

Clearly label limitations and never merge observational and randomized estimates without distinction.

## 22.4 Attribution

Attribution is still useful operationally, but must not be confused with causality. Support configurable windows by opportunity type and category cadence.

---

# 23. Opportunity Expected-Value and Ranking Engine

## 23.1 Distinguish predictive and causal modes

### Predictive/heuristic mode

When no validated treatment effect exists:

```text
expected_action_gross_profit =
    predicted_purchase_probability
    × expected_order_gross_profit
    × conservative_contact_effect_factor
    - incentive_cost
    - channel_cost
```

The contact-effect factor must be configurable, conservative, and visibly marked as heuristic.

### Causal mode

When validated treatment effects exist:

```text
expected_incremental_gross_profit =
    (P(purchase | treatment) - P(purchase | control))
    × expected_order_gross_profit_before_incentive
    - expected_incentive_cost
    - channel_cost
    - expected_return_cost
    - expected_cannibalization_cost
```

## 23.2 Priority score

Use an auditable composite such as:

```text
priority_score =
    economic_value
    × urgency_factor
    × confidence_factor
    × fulfillability_factor
    × contactability_factor
    × policy_factor
```

Each factor must be stored and visible in evidence.

Do not let a high probability but tiny margin outrank a lower probability with substantially higher expected profit unless the economics justify it.

## 23.3 Opportunity conflicts

Implement conflict resolution:

- Do not send multiple overlapping offers to the same customer in a short period.
- Replenishment may supersede a generic cross-sell.
- Service recovery may supersede promotional messaging.
- A recent purchase should close or invalidate stale opportunities.
- If multiple products are substitutes, choose one primary recommendation and expose alternatives.

## 23.4 Expiration

Every opportunity must have an expiry based on the underlying event or purchase window. Stale opportunities must automatically close with reason `expired`.

---

# 24. Pet-Retail Domain Intelligence

Implement the system generically, with a pet-retail domain layer.

## 24.1 Compatibility safeguards

Never recommend:

- Cat products to a dog-only household or vice versa unless confidence is low and the UI asks for verification.
- Kitten/puppy products to adult/senior animals without evidence.
- Therapeutic or condition-specific nutrition based solely on weak transaction inference.
- Conflicting product forms or sizes where package metadata disproves fit.

## 24.2 Household inference

Infer probable pet ownership from repeated category evidence, but store:

- inferred species/life stage.
- confidence.
- evidence count.
- last supporting purchase.

A single gift purchase must not permanently label a household.

## 24.3 Consumable depletion

Food, litter, pads, supplements, treats, hygiene products, and similar items should receive replenishment logic. Durable goods should use different repeat and cross-sell logic.

## 24.4 Services

Support grooming, veterinary consultation, training, or other service records as products/services with separate cadence and eligibility rules.

Examples:

- Grooming rebooking interval.
- Grooming customer → compatible home-care products.
- Food purchase → supplement only when appropriate.
- Puppy/kitten lifecycle → age-stage transition opportunity.

## 24.5 Branch fulfillment

Recommendations must account for stock at the branch the customer is most likely to use. When unavailable:

- offer another branch.
- offer a compatible substitute.
- suppress the opportunity.

The policy must be configurable.

---

# 25. Next-Best-Action Policy

The target is not merely “next product.” The system must choose among actions:

- No action.
- Reminder without offer.
- Product recommendation.
- Bundle recommendation.
- Replenishment reminder.
- Availability notification.
- Upgrade/upsell.
- Win-back.
- Service recovery.
- Human call assignment.
- SMS.
- WhatsApp.
- Email/push when available.
- In-store salesperson prompt.

The policy must consider:

- expected economic value.
- customer channel preference.
- consent.
- fatigue.
- urgency.
- operator capacity.
- branch inventory.
- offer cost.
- evidence strength.

Where data is insufficient, use transparent rules and collect outcomes to improve future policy.

---

# 26. API Requirements

Use versioned endpoints. Adapt route naming to existing conventions.

## 26.1 Imports and data quality

```text
POST   /api/v1/imports
GET    /api/v1/imports
GET    /api/v1/imports/{id}
POST   /api/v1/imports/{id}/validate
POST   /api/v1/imports/{id}/commit
GET    /api/v1/imports/{id}/reconciliation
GET    /api/v1/imports/{id}/quarantine
POST   /api/v1/imports/{id}/quarantine/{row_id}/resolve
GET    /api/v1/source-mappings
POST   /api/v1/source-mappings
```

## 26.2 Customer 360

```text
GET    /api/v1/customers
GET    /api/v1/customers/{id}
GET    /api/v1/customers/{id}/timeline
GET    /api/v1/customers/{id}/features
GET    /api/v1/customers/{id}/opportunities
GET    /api/v1/customers/{id}/orders
GET    /api/v1/customers/{id}/identity
POST   /api/v1/customers/{id}/merge
POST   /api/v1/customers/{id}/unmerge-or-review
```

## 26.3 Opportunities

```text
GET    /api/v1/opportunities
GET    /api/v1/opportunities/{id}
POST   /api/v1/opportunities/generate
POST   /api/v1/opportunities/{id}/accept
POST   /api/v1/opportunities/{id}/dismiss
POST   /api/v1/opportunities/{id}/assign
POST   /api/v1/opportunities/{id}/complete-action
POST   /api/v1/opportunities/{id}/invalidate
GET    /api/v1/opportunities/summary
POST   /api/v1/opportunities/export
```

Filters must include:

- opportunity type.
- branch.
- category/product/brand.
- lifecycle state.
- minimum expected value.
- confidence.
- expiry.
- channel.
- assigned operator.
- status.

## 26.4 Models and scoring

```text
GET    /api/v1/models
GET    /api/v1/models/{id}
POST   /api/v1/models/train
POST   /api/v1/models/{id}/validate
POST   /api/v1/models/{id}/promote
POST   /api/v1/models/{id}/rollback
GET    /api/v1/models/{id}/metrics
GET    /api/v1/models/{id}/drift
```

Promotion must require validation status and authorization.

## 26.5 Campaigns and experiments

```text
POST   /api/v1/campaigns
GET    /api/v1/campaigns
GET    /api/v1/campaigns/{id}
POST   /api/v1/campaigns/{id}/build-audience
POST   /api/v1/campaigns/{id}/randomize
POST   /api/v1/campaigns/{id}/launch
POST   /api/v1/campaigns/{id}/record-exposure
GET    /api/v1/campaigns/{id}/results
POST   /api/v1/experiments
GET    /api/v1/experiments/{id}
POST   /api/v1/experiments/{id}/analyze
```

## 26.6 Example opportunity response

```json
{
  "id": "opp_123",
  "opportunity_type": "replenishment",
  "customer": {
    "id": "cus_456",
    "display_name": "Customer A",
    "lifecycle_state": "loyal"
  },
  "target": {
    "type": "product",
    "id": "prd_789",
    "name": "Belcando Adult Lamb & Rice 12.5 kg"
  },
  "recommended_action": {
    "channel": "whatsapp",
    "offer": null,
    "message_strategy": "personalized_replenishment_reminder"
  },
  "timing": {
    "valid_from": "2026-08-12T08:00:00+03:30",
    "expires_at": "2026-08-15T23:59:59+03:30",
    "urgency": 0.91
  },
  "economics": {
    "currency": "IRR",
    "display_unit": "toman",
    "expected_revenue": "27000000",
    "expected_gross_profit": "5100000",
    "expected_incremental_gross_profit": null,
    "valuation_mode": "predictive_heuristic"
  },
  "confidence": 0.86,
  "evidence": {
    "summary": "Customer is inside the predicted replenishment window.",
    "interval_days": [43, 47, 45],
    "days_since_last_purchase": 44,
    "evidence_level": "customer_product",
    "source_order_ids": ["..."],
    "feature_snapshot_id": "fs_...",
    "generator_version": "replenishment_rule_v1.2"
  }
}
```

Use decimal strings or integer minor units in APIs for money.

---

# 27. Frontend and UX Requirements

The interface should be action-oriented, fast, and usable in Persian RTL while keeping internal API keys and code identifiers in English.

## 27.1 Daily Revenue Command Center

Show:

- Number of currently valid opportunities.
- Forecasted revenue and gross profit.
- Proven incremental gross profit where experiments support it.
- Opportunity count by type.
- Opportunities expiring today.
- High-value customers at risk.
- Data freshness and last successful import.
- Blocking data-quality warnings.

Do not merge forecasted and proven incremental values in one number.

## 27.2 Opportunity Inbox

Primary table/card fields:

- Customer.
- Opportunity type.
- Target product/category/service.
- Why now.
- Expected economics.
- Confidence.
- Recommended channel and offer.
- Expiry.
- Branch availability.
- Assigned operator.
- Status.

Actions:

- View customer.
- Accept.
- Dismiss with reason.
- Assign.
- Export.
- Record contact.
- Mark outcome.

Provide bulk actions with safety confirmation and clear selection counts.

## 27.3 Customer 360 page

Sections:

1. Identity and contactability.
2. Pet/household profile and confidence.
3. Lifecycle state and transition timeline.
4. Value, margin, CLV, and expansion gap.
5. Purchase timeline.
6. Category and brand affinity.
7. Replenishment calendar.
8. Open and historical opportunities.
9. Campaign exposures and outcomes.
10. Explanation of current scores.

## 27.4 Product Intelligence

Show:

- Sales, gross profit, margin, trend.
- Repeat and replenishment behavior.
- Complement and substitute network.
- Attach rates.
- Price/promotion response.
- Branch stock and stockout impact.
- Customer segments.

## 27.5 Campaign and Experiment Center

Allow an operator to:

- Build an audience from opportunities or segments.
- Exclude ineligible/over-contacted customers.
- Configure treatment and control.
- Select message/offer variants.
- Preview economics and sample size assumptions.
- Launch through available connectors or export.
- Read incremental results separately from attribution.

## 27.6 Data Quality Center

Show import history, row errors, mapping issues, reconciliation, unmatched products, suspected customer duplicates, and money-unit warnings.

## 27.7 Model Health

Show:

- Active model version.
- Training window.
- Validation window.
- Business metrics.
- Calibration.
- Drift.
- Last scoring time.
- Rollback action.

Do not expose raw ML complexity without a business interpretation.

---

# 28. Background Jobs and Scheduling

Required jobs:

1. File discovery/upload processing.
2. Parsing and validation.
3. Canonical commit and reconciliation.
4. Identity and product resolution.
5. Incremental feature recomputation.
6. Daily opportunity generation.
7. Expiration/invalidation.
8. Outcome matching.
9. Campaign analysis.
10. Scheduled model retraining.
11. Drift monitoring.
12. Data retention and cleanup for temporary files.

Requirements:

- Idempotent jobs.
- Retry policy with exponential backoff.
- Dead-letter/failure visibility.
- Job progress and status.
- Correlation IDs.
- Concurrency control per business/import.
- No overlapping scoring jobs for the same business and as-of timestamp.
- Safe restart behavior.

Expose job status in the UI/API.

---

# 29. Model Development and Validation Protocol

## 29.1 Temporal splits only

Use chronological train/validation/test periods. Random row splits are invalid for future purchase and churn prediction.

## 29.2 Point-in-time correctness

No feature may contain information recorded after the prediction timestamp.

## 29.3 Baseline comparison

Every advanced model must beat a documented baseline on business-relevant metrics. A complex model that does not materially improve top-K gross profit should not be promoted.

## 29.4 Calibration

Calibrate probabilities where needed and report reliability curves. A displayed 80% probability should approximately correspond to an 80% outcome rate in the relevant bucket.

## 29.5 Confidence and abstention

The system must abstain or lower confidence when:

- Data is too sparse.
- Product match confidence is low.
- Cost is missing.
- No valid stock data exists.
- The customer has conflicting identity signals.
- Drift exceeds thresholds.

## 29.6 Data gates

Make thresholds configurable, but implement conservative defaults and explicit “insufficient data” states.

Examples:

- Customer-product cadence requires multiple valid purchases; otherwise use fallback.
- Uplift modeling requires treatment/control exposure data and adequate positives in each arm.
- SKU elasticity requires meaningful price variation and enough time periods.
- Future-whale modeling requires mature historical cohorts.

Do not train a meaningless model merely to satisfy a feature checklist.

## 29.7 Drift

Monitor:

- Feature distribution shift.
- Target rate shift.
- Calibration decay.
- Segment performance.
- Product/category changes.
- Branch/channel changes.

Trigger warning and rollback/retraining policy where configured.

---

# 30. Experiment and Feedback Loop

Every recommendation must create learning data.

Flow:

```text
Opportunity generated
→ operator accepts/dismisses
→ customer selected for treatment/control
→ exposure/action recorded
→ purchase or non-purchase observed
→ revenue/margin matched
→ attribution calculated
→ incremental effect estimated
→ policy/model metrics updated
```

Capture dismissal reasons such as:

- customer not relevant.
- product incompatible.
- customer already purchased elsewhere.
- bad contact data.
- no stock.
- value too low.
- duplicate opportunity.

Use operator feedback as a quality signal, but do not treat it as unbiased ground truth.

---

# 31. Security, Privacy, and Access Control

Implement or extend:

- Authentication.
- Business/tenant scoping in every query.
- Role-based access for admin, analyst, campaign operator, salesperson, and viewer.
- PII masking in logs.
- Encryption in transit.
- Secret management through environment/configuration, never source control.
- Audit logs for customer merges, model promotion, opportunity actions, campaign launch, exports, and price recommendations.
- Export permissions and rate limits.
- Contact consent and do-not-contact enforcement.
- Data retention configuration.

Model training datasets should use internal IDs and avoid unnecessary raw PII.

---

# 32. Observability

Implement structured logs and metrics for:

- Import duration and error rate.
- Rows accepted/quarantined.
- Product/customer match rates.
- Job queue depth and failures.
- Feature freshness.
- Model training/scoring duration.
- Opportunity generation count by type.
- Suppression reasons.
- API latency/error rate.
- Campaign delivery and outcome matching.

Include correlation IDs from import through opportunity generation where practical.

Create operational health endpoints and a concise runbook.

---

# 33. Performance and Scalability

- Use database-side aggregation and indexes for large filters.
- Avoid N+1 queries.
- Paginate opportunity and customer lists.
- Compute features incrementally based on source watermarks.
- Partition or index time-series/event tables appropriately.
- Cache only where invalidation is explicit.
- Keep heavy model artifacts out of web-worker memory unless required for low-latency scoring.
- Batch score daily opportunities; use event-triggered refresh for important purchases/imports.

Carry `business_id` throughout schema, jobs, caches, artifacts, and model versions even in single-business deployments.

---

# 34. Testing Strategy

## 34.1 Unit tests

Cover:

- Persian text and phone normalization.
- Rial/Toman conversion.
- Date parsing.
- duplicate detection.
- return handling.
- margin calculations.
- lifecycle transitions.
- replenishment intervals.
- compatibility filters.
- opportunity scoring.
- experiment randomization.

## 34.2 Integration tests

Cover:

- Import file → canonical orders → features → opportunity.
- Retry/idempotency.
- migration from current schema.
- background job execution.
- API authorization and tenant isolation.
- frontend API contract.

## 34.3 Golden data tests

Create small, deterministic fixtures representing:

- Repeat buyer with stable cadence.
- Irregular buyer.
- customer with return.
- duplicate phone formats.
- ambiguous product aliases.
- cat-only and dog-only households.
- full-price loyal customer.
- discount-dependent customer.
- dormant high-value customer.
- control and treatment campaign outcomes.

Expected outputs must be explicit and reviewed.

## 34.4 Model tests

- Temporal leakage checks.
- Reproducibility with fixed seeds and data hashes.
- baseline comparison.
- calibration.
- segment fairness/stability.
- artifact loading compatibility.
- no-scoring behavior on schema mismatch.

## 34.5 End-to-end tests

At minimum:

1. Upload an Excel file.
2. Resolve mapping.
3. Validate and reconcile.
4. Commit canonical data.
5. Compute Customer 360.
6. Generate opportunities.
7. Accept and assign an opportunity.
8. Record an exposure/action.
9. Import a later purchase.
10. Match the outcome and update campaign reporting.

## 34.6 CI requirements

CI must run:

- backend tests.
- frontend typecheck/lint/tests.
- migration checks.
- API schema compatibility check.
- deterministic model smoke tests.

---

# 35. Delivery Phases

Implement phases sequentially, maintaining the application in a working state. Continue automatically after each validated phase.

## Phase 0 — Audit and safety foundation

Deliver:

- Current-system audit.
- Target architecture document.
- Schema migration plan.
- Implementation status checklist.
- Baseline test suite around current imports.
- Backup/rollback instructions.

Then proceed.

## Phase 1 — Canonical data and trustworthy Customer 360

Deliver:

- Immutable imports and quarantine.
- Versioned mappings.
- canonical orders/order lines/customers/products.
- identity and product resolution.
- returns, discounts, cost, margin, and reconciliation.
- Customer 360 feature snapshots.
- data-quality UI/API.

Acceptance gate: historical imports can be reprocessed idempotently and reconcile to source totals within documented tolerances.

## Phase 2 — Actionable deterministic opportunity engine

Deliver:

- Lifecycle states.
- Rule-based replenishment.
- rule-based churn/slipping.
- association/sequential next-best-product baseline.
- basket-building baseline.
- expansion-gap baseline.
- opportunity common contract.
- filters, conflict suppression, expiry, expected-value ranking.
- Opportunity Inbox and Customer 360 UI.

Acceptance gate: every opportunity is backed by evidence and can be reproduced.

## Phase 3 — Closed-loop campaigns and experiments

Deliver:

- action/exposure/outcome events.
- campaign audience builder.
- treatment/control randomization.
- attribution reporting.
- incremental analysis.
- exports/connectors supported by current infrastructure.
- operator feedback.

Acceptance gate: a test campaign can be run end-to-end with treatment/control and incremental gross profit reporting.

## Phase 4 — Predictive models

Deliver:

- calibrated churn/survival model.
- advanced replenishment model.
- CLV.
- future-whale model.
- hybrid next-best-product ranking.
- model registry, promotion, rollback, and drift.

Acceptance gate: promoted models beat deterministic baselines on temporal holdout and top-K economic metrics.

## Phase 5 — Causal offer optimization and pricing intelligence

Deliver only when data gates pass:

- uplift/treatment-effect models.
- minimum effective incentive policy.
- price elasticity and simulation.
- next-best-action optimization.

Acceptance gate: methods have adequate treatment/control or price-variation evidence and uncertainty is visible.

## Phase 6 — Operational optimization

Deliver:

- operator assignment/capacity constraints.
- branch-aware fulfillment.
- notification and scheduled workflows.
- performance tuning.
- advanced monitoring.
- documented deployment/runbook.

---

# 36. Required Documentation Deliverables

Create and maintain:

```text
docs/revenue-intelligence/
  CURRENT_SYSTEM_AUDIT.md
  TARGET_ARCHITECTURE.md
  DATA_DICTIONARY.md
  SOURCE_MAPPING_GUIDE.md
  FINANCIAL_CALCULATION_RULES.md
  IDENTITY_RESOLUTION.md
  FEATURE_CATALOG.md
  OPPORTUNITY_ENGINE.md
  MODEL_CARDS.md
  EXPERIMENTATION_GUIDE.md
  API_GUIDE.md
  OPERATIONS_RUNBOOK.md
  SECURITY_AND_PRIVACY.md
  IMPLEMENTATION_STATUS.md
  RELEASE_NOTES.md
```

Also update:

- Root README.
- `.env.example`.
- migration instructions.
- local development instructions.
- production deployment instructions.
- backup and restore procedure.

---

# 37. Acceptance Criteria — System Level

The upgrade is complete only when all applicable criteria pass.

## Data correctness

- Re-importing the same file does not duplicate transactions.
- Source and canonical totals reconcile.
- Returns and discounts are correctly reflected.
- Rial/Toman unit is explicit.
- Customers and products have reviewable resolution evidence.

## Opportunity quality

- Each opportunity has a customer, target/action, timing, economics, confidence, expiry, and explanation.
- Incompatible or unavailable products are suppressed.
- Stale opportunities close automatically.
- The ranking prioritizes expected economic value rather than raw probability.
- Predictive values are not mislabeled as incremental.

## Closed-loop measurement

- Actions and exposures are persisted.
- Control groups are supported.
- Later purchases are matched to outcomes.
- Attribution and incrementality are reported separately.

## Engineering quality

- Migrations are reversible or have a safe rollback strategy.
- Backend and frontend tests pass.
- Jobs are idempotent and observable.
- APIs are typed and documented.
- No secrets or PII leaks exist in source/logs.
- Existing core workflows remain functional.

## Usability

An operator can open the application and answer:

- What should I do today?
- Which opportunities are most profitable?
- Why was each one recommended?
- Which ones expire soon?
- What happened after prior actions?
- Which campaigns created real incremental gross profit?

---

# 38. Example Daily Executive Output

The system should be capable of generating an output similar to:

```text
As of: 2026-08-12 08:00 Asia/Tehran
Data freshness: through 2026-08-11 23:59

Valid opportunities: 1,842
Forecasted revenue from accepted actions: 2.10B Toman
Forecasted gross profit: 512M Toman
Proven/experiment-backed incremental gross profit: 146M Toman
Heuristic opportunity gross profit not yet causally validated: 366M Toman

Highest-value opportunity groups:
1. Replenishment: 620 customers, 179M forecast gross profit
2. High-value win-back: 148 customers, 96M forecast gross profit
3. Cross-sell: 731 customers, 84M forecast gross profit
4. Future-whale relationship actions: 74 customers
5. Basket expansion: 269 customers, 53M forecast gross profit

Urgent:
- 93 opportunities expire today.
- 27 VIP customers entered At-risk.
- 41 recommendations suppressed due to insufficient stock.
- 18 import rows require financial-unit review.
```

Forecasted and proven incremental values must never be visually combined without clear labeling.

---

# 39. Implementation Decisions Claude Code Must Make During Repository Inspection

For each item below, inspect the existing code, choose the best compatible design, document the decision, and proceed:

1. Whether to extend the current database or migrate to PostgreSQL.
2. Whether the existing scheduler is durable enough or requires a queue.
3. Where feature computation belongs in the current module structure.
4. How to preserve current reports while canonical data is introduced.
5. Which model library best fits the installed environment and benchmark.
6. How to package model artifacts and migrations for deployment.
7. How to implement tenant scoping without breaking the current single-business flow.
8. How to expose RTL Persian UI while retaining typed English internal identifiers.
9. Which current import formats can be mapped automatically and which require an operator mapping step.
10. Which features are blocked by missing inventory, cost, campaign exposure, or pet-profile data.

Record decisions in `TARGET_ARCHITECTURE.md`. Do not use missing optional data as a reason to stop the whole upgrade. Implement graceful fallbacks and accurately label limitations.

---

# 40. Required Final Verification by Claude Code

Before declaring completion:

1. Run the full backend test suite.
2. Run frontend typecheck, lint, and tests.
3. Run migrations from a clean database.
4. Run migrations against a copy of the current schema/data where available.
5. Process representative `.xls`, `.xlsx`, and `.xlsb` fixtures.
6. Verify idempotent re-import.
7. Reconcile financial totals.
8. Generate each implemented opportunity type.
9. Verify explanations and source evidence.
10. Complete an end-to-end campaign/control/outcome flow.
11. Confirm no predictive value is labeled incremental without valid evidence.
12. Verify tenant isolation.
13. Verify no PII appears in logs.
14. Document any feature that remains blocked by unavailable source data.
15. Update `IMPLEMENTATION_STATUS.md` and `RELEASE_NOTES.md` with exact results.

The final Claude Code response should summarize:

- What was implemented.
- Major architecture decisions.
- Database migrations.
- Tests and exact results.
- Backfill/import results.
- Models and validation results.
- Remaining data-dependent limitations.
- Exact commands for local and production execution.
- Files changed.

Do not claim success for a module that has only scaffolding, mocked output, or no validated end-to-end path.

---

# 41. Final Product Principle

The system’s purpose is not to describe the past. It is to create the highest-quality next commercial decision while protecting margin and measuring true impact.

Every component should move the product toward this operating loop:

```text
Know the customer
→ detect the commercial moment
→ choose the best action
→ execute with the minimum necessary incentive
→ measure the true incremental result
→ learn and improve
```

The default homepage should therefore answer:

> **“Which actions should the team execute today to create the highest expected incremental gross profit, and why?”**

That question—not the number of charts, models, or pages—is the final standard for this upgrade.
