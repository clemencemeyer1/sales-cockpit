# Find and map the data

## 1. Discover
```python
cats = cl.list_catalogs(w)                # pick the relevant ones with the seller (crm, sales, billing, gold…)
found = cl.discover(w, wh, ["crm", "billing"])   # optional schemas=["gold"]: faster on big catalogs
for ent, cands in found.items():
    print(ent, [(c["table"], c["score"]) for c in cands])
```
Use the seller's hints from round C first (a schema they named beats the ranking). For the top 1–3 candidates of each
entity, `cl.describe(w, wh, table)` (columns, types, 5 rows). Prefer, in this order: curated / gold tables over raw
ingestion tables; tables with comments; the table the seller's reports already use (ask). Ignore `_history`,
`_staging`, `_tmp`, backup copies.

Typical CRM shapes (examples, not assumptions — always check the columns):
- Salesforce: `Account` (Id, Name, OwnerId, Type, Industry, BillingCountry), `Opportunity` (Id, AccountId, Amount,
  CloseDate, IsClosed, IsWon, StageName, Type), `User` (Id, Email) to resolve the owner.
- HubSpot: `companies` (id, properties_name, hubspot_owner_id, lifecyclestage), `deals` (dealstage, amount,
  closedate, hs_is_closed_won), `owners` (id, email); deal-company links in an association table.
- Dynamics: `account`, `opportunity` (statecode 1 = won, 2 = lost), `systemuser`.

## 2. Map
Each entity of `cl.ENTITIES` = canonical columns (required + optional). A mapping says, for one source table, the SQL
expression of each canonical column, plus a filter:
```json
"accounts": {
  "table": "crm.gold.account",
  "columns": {"account_id": "Id", "account_name": "Name", "status": "CASE WHEN Type = 'Customer' THEN 'Customer' ELSE 'Prospect' END",
              "segment": "Segment__c", "industry": "Industry", "country": "BillingCountry", "owner": "OwnerId"},
  "filter": "OwnerId IN (SELECT Id FROM crm.gold.user WHERE Email = 'jane@acme.com')",
  "extra_columns": {"health_score": "Health_Score__c"}
}
```
- Expressions are Spark SQL over the source table (CASE, joins via sub-queries, casts). `is_closed` / `is_won` must
  be booleans; dates are cast to DATE; amounts to DOUBLE (convert currency here if needed, ask how).
- **The seller filter goes on `accounts`.** Every other entity is automatically limited to the seller's accounts
  (`account_id IN accounts`). If an entity must be filtered differently (e.g. opportunities owned by the seller even
  on accounts they do not own), give it its own `filter` and `"own_scope": true`.
- Several sources for one entity = a list of mappings, stacked; use `extra_columns` with the same keys in each, and map
  `source` (`"source": "'ZoomInfo'"`).
- `status` should end up with two readable values (e.g. 'Customer' / 'Prospect'); `type` on opportunities should
  contain "new" for new business (used by `new_logos` / `new_logo_bookings`) — map it with a CASE if needed.
- Show the seller the mapping as a short table (entity → table, key columns, filter) and ask for confirmation
  before building. Then test: `SELECT count(*)` with the filter = the number of accounts they expect?

## 3. Missing data
Two different situations — tell them apart, because the right person to ask is not the same:

| Situation | How you know | Who to ask |
|---|---|---|
| **Not in Databricks** (tool not ingested, or only part of it, e.g. no activities) | `discover` finds nothing, seller confirms the tool exists | the data platform / data engineering team that runs ingestion (often "data team", "BI team", "analytics engineering") |
| **In Databricks but no access** | the seller knows the table name but gets PERMISSION_DENIED / table not found; or a colleague's report uses it | the table owner (`table_owner` in `system.information_schema.tables` if visible, else the schema/catalog owner) — in Catalog Explorer the seller can also click **Request access** |
| **Present but unusable** (no account id to join, no owner field, stale) | describe/sample show it | the table owner, with the precise column or refresh needed |

For each gap add to `cfg["missing"]`: `{"entity", "tool", "situation", "needed_for", "table" (if known)}`;
`cl.gaps(cfg)` also lists KPIs whose entity is missing. Build the rest anyway; the page or KPI simply does not appear.

At hand-over, offer to **draft the message** (in the seller's language, short, ready to paste in Slack/Teams/e-mail),
one per recipient:

> Subject: Data access for my sales cockpit in Databricks
>
> Hi <team / name>,
> I am building a personal sales cockpit in Databricks (views + a Genie space, only on my own accounts). I am missing:
> - **<tool / data>** — <not ingested in Databricks | table `<catalog.schema.table>`: I don't have SELECT>.
>   I need: <the fields, e.g. account id, date, amount, product> refreshed <daily/weekly>, to track <KPI / use>.
> Could you tell me whether it can be ingested / shared with me (read-only), and roughly when? Happy to go through the
> details. Thanks!

Fill in the exact fields from the canonical entity (`cl.ENTITIES[...]`), the KPI it unlocks and, for an access
request, the exact table name. Never include data values in the message.
