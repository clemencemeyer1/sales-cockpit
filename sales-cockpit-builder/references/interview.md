# Interview

Three rounds, each one message. Numbered questions, a suggested answer or examples for each, so the seller can reply
"1 yes, 2 EMEA mid-market, 3 …". Adapt the wording to their language (ask it first if unclear: the first message can
be in English with "answer in the language you prefer"). Skip what you already know.

## Round A — who you are and how you sell
1. Name, e-mail, and the language you want the cockpit in.
2. Your role: new business / hunter (greenfield), account manager / farmer (install base, expansion, renewals),
   hybrid, SDR/BDR, or sales manager (team view)?
3. Your book: named accounts, a territory (region, country, segment, industry), or a pool of leads? Roughly how many
   accounts?
4. How your company makes money — one or several:
   - **subscription / licence** (ARR, seats, renewals)
   - **commitment** (customer commits an amount over a term, consumes against it)
   - **consumption / usage-based** (pay as you go, billed on usage)
   - **transactional / one-off** (projects, hardware, services)
5. Fiscal year start month and the period you are measured on (month, quarter, half, year). Currency.
6. What do you sell: product lines or packages you want to track separately (if any)?

## Round B — KPIs and targets
Propose a KPI set from round A (`references/kpis.md`, "Defaults by profile") and ask:
1. Which of these are you measured on (and which are just useful)? Anything missing?
2. How is each one counted at your company — e.g. "bookings = won opportunities by close date, new business only,
   amount in the opportunity currency converted?" Any exclusions (renewals, partner deals, …)?
3. Breakdowns you care about: by product, segment, industry, region, deal type, customer vs prospect, owner?
4. Your targets for the current period, per KPI (and per breakdown if you have one). Is there a table with them
   (quota / target / plan table), or will you type them?
5. What would you like to see first thing every morning? (Used to order pages and pick action rules.)

## Round C — your data
Ask which tools they use, by category, and whether they know it lands in Databricks (a table name or schema is a
great hint, "I don't know" is fine: discovery will look):

| Category | Examples of tools | Entity |
|---|---|---|
| CRM | Salesforce, HubSpot, Dynamics, Pipedrive, Zoho | accounts, opportunities, contacts, activities, leads |
| Product usage / billing | product telemetry, billing system, invoicing, ERP | usage |
| Contracts / subscriptions | CPQ, billing, ERP, subscription platform | contracts |
| Targets / quotas | sales planning tool, spreadsheets, finance tables | targets |
| Prospecting / intent / enrichment | ZoomInfo, Lusha, Apollo, Cognism, Bombora, 6sense, G2, Clearbit, LinkedIn Sales Navigator exports | signals, contacts, leads |
| Marketing | marketing automation, events, webinars, website visits | signals, leads |
| Support / success | ticketing, health scores, NPS | signals (or extra account columns) |
| Calendar / e-mail activity | meeting logs synced to the CRM | activities |

Also ask: how are you identified in the CRM (owner e-mail, owner name, user id)? Which field says an account is a
customer vs a prospect?

## What to write
```json
"seller":  {"name": "...", "email": "...", "language": "fr", "role": "hunter|farmer|hybrid|sdr|manager",
            "book": "named accounts, mid-market France", "currency": "EUR", "crm_owner": "<value in the CRM>"},
"company": {"name": "...", "sales_models": ["subscription", "consumption"], "fiscal_year_start_month": 2,
            "products": ["..."], "customer_definition": "accounts.status = 'Customer'"},
"kpis":    [ ... see references/kpis.md ... ],
"priorities": "what they want to see first, in their words"
```
