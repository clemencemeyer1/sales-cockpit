# KPIs, targets and next actions

## KPI entry (`cfg["kpis"]`)
```json
{"id": "bookings_new", "label": "New business bookings", "metric": "new_logo_bookings", "period": "quarter",
 "unit": "money", "breakdown": "product",
 "targets": [{"period_start": "2026-11-01", "value": 400000},
             {"period_start": "2026-11-01", "dimension_value": "Platform", "value": 250000}]}
```
- `metric` from the library below, or `"metric": "custom"` with `"sql"`: a SELECT over `{ns}` views returning
  `dimension_value` (use `'All'` for the total) and `actual` for the **current** period — use it when the company
  counts something its own way (always check with the seller).
- `period`: month | quarter | half | year (fiscal year from `company.fiscal_year_start_month`).
- `breakdown`: a column of the KPI's entity or of `accounts` (product, segment, industry, region, type, owner…).
- `unit`: money (default) or count / pct.
- `targets`: only when no targets table is mapped. `period_start` = first day of the period (fiscal), as the view
  computes it: check with `SELECT DISTINCT kpi_id, period_start FROM {ns}.kpi_attainment`.
- Targets table mapped instead (`sources.targets`): columns `kpi_id`, `period_start`, `target_value`, optional
  `dimension_value` — map the seller's quota table onto these (e.g. a CASE turning their metric name into the kpi id).

## Metric library (`cl.METRICS`, `cl.SNAPSHOT_METRICS`)
| metric | needs | definition |
|---|---|---|
| bookings | opportunities | won amount, by close date |
| new_logo_bookings | opportunities | won amount where type contains "new" |
| expansion_bookings | opportunities | won amount, other types (upsell, cross-sell, renewal) |
| deals_won | opportunities | number of won deals |
| win_rate_pct | opportunities | won / closed in the period |
| new_logos | opportunities | distinct accounts with a won "new" deal |
| pipeline_created | opportunities | amount of deals created in the period |
| open_pipeline | opportunities | open amount closing in the period (coverage = open_pipeline / remaining target) |
| consumption | usage | usage amount in the period |
| activities / meetings | activities | count in the period |
| arr | contracts | ARR of active contracts today (snapshot) |
| commit_consumed_pct | contracts | consumed / committed on active contracts (snapshot) |

## Defaults by profile (propose, then let the seller edit)
- **Hunter / new business**: new_logo_bookings, new_logos, pipeline_created, open_pipeline, meetings; pages
  actions → signals → pipeline → accounts.
- **Farmer / account manager**: bookings (expansion), arr or consumption, commit_consumed_pct, win_rate_pct; pages
  actions → overview → usage/contracts → accounts.
- **Consumption model**: consumption (by product) is the main KPI; action rules usage_drop, usage_growth.
- **Commit model**: commit_consumed_pct, renewals; rules commit_underburn, commit_overburn, renewal_due.
- **Subscription**: arr, expansion_bookings, renewal_due.
- **Both commit and consumption**: consumption + commit_consumed_pct, all usage and commit rules.
- **SDR**: meetings, activities, pipeline_created; leads + signals pages.
- **Manager**: same KPIs with `breakdown: "owner"`.

## Next actions (`cfg["action_rules"]`, optional)
Rules in `cl.ACTION_RULES`, each enabled only when its data exists: overdue_deal, closing_soon, usage_drop,
usage_growth, commit_underburn, commit_overburn, renewal_due, no_recent_touch, new_signal. Default = all applicable;
narrow it to the seller's motion (a hunter does not need usage_growth). A company-specific rule = add an entry to
`ACTION_RULES` in a cell before `build_views` (same shape: needed entities, priority, SELECT returning account_id,
reason, detail, action).
