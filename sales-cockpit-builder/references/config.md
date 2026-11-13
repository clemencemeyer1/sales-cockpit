# cockpit_config.json

One file in `/Users/<seller>/sales-cockpit/`, written with `cl.save_config(w, cfg, cfg_path)` after every step.

```json
{
  "seller":  {"name": "Jane Doe", "email": "jane@acme.com", "language": "en", "role": "farmer",
              "book": "named accounts, DACH enterprise", "currency": "EUR", "crm_owner": "0055g00000AbCdE"},
  "company": {"name": "Acme", "sales_models": ["commit", "consumption"], "fiscal_year_start_month": 1,
              "products": ["Platform", "Analytics", "Support"], "customer_definition": "Type = 'Customer'"},
  "priorities": "renewals and accounts whose usage drops",
  "kpis": [
    {"id": "consumption", "label": "Consumption", "metric": "consumption", "period": "quarter", "breakdown": "product",
     "targets": [{"period_start": "2026-10-01", "value": 1200000}]},
    {"id": "commit_burn", "label": "Commit consumed", "metric": "commit_consumed_pct", "unit": "pct"}
  ],
  "sources": {
    "accounts": {"table": "...", "columns": {...}, "filter": "..."},
    "opportunities": {"table": "...", "columns": {...}},
    "usage": {"table": "...", "columns": {...}},
    "signals": [{"table": "...", "columns": {..., "source": "'ZoomInfo'"}},
                {"table": "...", "columns": {..., "source": "'Website'"}}]
  },
  "missing": [{"entity": "activities", "tool": "Outreach", "situation": "not ingested",
               "needed_for": "no_recent_touch rule, meetings KPI"}],
  "action_rules": ["usage_drop", "commit_underburn", "renewal_due", "overdue_deal"],
  "pages": ["actions", "overview", "usage", "contracts", "accounts", "pipeline"],
  "labels": {},
  "theme": {"lava": "#533AFD", "hero": "#1C1E54", "...": "(from cl.make_theme; absent = standard colours)"},
  "target": {"catalog": "sandbox", "schema": "sales_cockpit_jane", "warehouse_id": "...",
             "workspace_folder": "/Users/jane@acme.com/sales-cockpit",
             "genie_space_id": "(set by build_genie)", "app_name": "(set by deploy_app)", "app_url": "(set by deploy_app)",
             "owner_user": "(set by deploy_app)", "editor_endpoint": "(set by deploy_app; null = no Edit button)"},
  "genie": {"sample_questions": ["(set by build_genie, shown in the app's Genie bubble)"]}
}
```
Entities and their canonical columns: `cl.ENTITIES`. Mapping format: `references/data-mapping.md`.
