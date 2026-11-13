# Genie space

`cl.build_genie(w, cfg, instructions, examples, sample_questions)` creates (or updates) a private space in the
seller's folder on: the canonical views, `targets`, `kpi_attainment`, `account_overview`, `next_actions`.

## Instructions (one text, in English; tell Genie to answer in the seller's language)
Write it from the interview, never generic. Template:
```
You are the analytics coworker of <name>, <role> at <company>. Every table only contains their own accounts.
Answer in <language>. Amounts are in <currency>; format with thousands separators. Fiscal year starts in <month>;
"this quarter" means the current fiscal quarter (kpi_attainment.period_start).

Glossary:
- Customer / prospect = accounts.status '<…>' / '<…>'.
- <Each KPI>: <definition as agreed in the interview>, see kpi_attainment (kpi_id '<id>'); target = target_value.
- Pipeline = opportunities where NOT is_closed. Stages in order: <stage list from the data>.
- <Sales model specifics: e.g. "commit burn = consumed_amount / commit_amount vs time elapsed in the contract">.
- Signals = signals (sources: <list>): <what each signal_type means>.
- "What should I do" = next_actions ordered by priority (1 = this week).
- <Products / segments / company words the seller used, mapped to columns and values>.
Every table joins on account_id. Always show account_name, never only the id.
```
Get the real values (`SELECT DISTINCT status`, `stage`, `type`, `signal_type`, `product`) and put them in the
glossary: Genie filters much better with exact values.

## Example SQL (6–10, the questions this seller will really ask)
Pairs `(question, sql)` with `{ns}` for the schema; each one is run once by `build_genie` (a broken one fails the
step). Cover: attainment vs target, pipeline closing this period, top accounts by the main KPI, the main breakdown,
next actions, one sales-model specific question, one signal question. Example:
```python
examples = [
 ("Where am I vs my targets this quarter?",
  "SELECT kpi_label, actual, target_value, attainment_pct, period_elapsed_pct FROM {ns}.kpi_attainment WHERE dimension_value = 'All'"),
 ("Which deals close this quarter?",
  "SELECT a.account_name, o.opportunity_name, o.stage, o.amount, o.close_date FROM {ns}.opportunities o JOIN {ns}.accounts a USING (account_id) "
  "WHERE NOT o.is_closed AND o.close_date < add_months(current_date(), 3) ORDER BY o.close_date"),
 ("What should I do this week?",
  "SELECT priority, account_name, reason, detail, action FROM {ns}.next_actions ORDER BY priority, account_name"),
]
sample_questions = ["Where am I vs my targets this quarter?", "What should I do this week?", "..."]  # 4-6, seller's language
```

## Test
`cl.ask_genie(w, cfg, "<question>")` for 3 questions the seller gave in round B. Wrong table, filter or number →
add a glossary line or an example, rerun `build_genie` (it updates the same space).
