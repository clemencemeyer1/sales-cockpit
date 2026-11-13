---
name: sales-cockpit-builder
description: Build a personal sales cockpit for a B2B seller (account executive, account manager, SDR, sales leader) on data already in Unity Catalog - interview the seller about their data sources (CRM, product usage, contracts, prospecting tools), KPIs, targets and sales motion, find and map the right tables, then create views, a private Genie space and a Databricks App. Use when someone asks for a sales cockpit, a sales dashboard on their accounts, a territory/pipeline/quota tracker, or a Genie space for their book of business.
---

# Sales cockpit builder

You build **one seller's** cockpit, for the person chatting with you, on data they can already read in Unity
Catalog. Output: a schema of views (their accounts only), a private Genie space and a Databricks App.

The skill folder holds `scripts/cockpit_lib.py` (all the building blocks), `assets/app/` (the app template) and
`references/` (read each one when its step starts). Nothing is specific to one company: every table, column, KPI and
word comes from the interview and from what you find in Unity Catalog.

## Rules
- **Ask, never guess** business meaning: which table is the source of truth, which value identifies the seller,
  what "customer" means, how a KPI is computed, the target values. Propose your best guess and let them confirm.
- Ask in **batches** (3 to 6 questions per message, numbered, with suggested answers), never one question at a
  time and never a 30-question wall. Talk in the seller's language once you know it. Skip questions the data or
  earlier answers already settle.
- Read-only on source data: you only create objects in the cockpit schema and the seller's workspace folder.
- Never print personal data (contact names, e-mails, phones) in the chat beyond what the seller asks to see.
- When data the seller needs is **not in Unity Catalog, or they cannot read it**, do not invent or approximate it:
  log it in `cfg["missing"]`, keep building with what exists, and at the end help them ask the right people for it
  (`references/data-mapping.md`, "Missing data").
- Keep the state in one file, `cockpit_config.json` (`references/config.md`), saved after every step, so a run can
  stop and resume, and a rerun ("update my cockpit", "add a KPI") starts from it.

## Steps
**0. Setup.** In a notebook (create `<workspace folder>/build_cockpit` if none is open), one Python cell:
```python
import sys, os
from databricks.sdk import WorkspaceClient
user = WorkspaceClient().current_user.me().user_name
import glob  # default skills folders first, then a Git folder / registered skills folder in the user's home
skill = next((p for p in [f"/Workspace/Users/{user}/.assistant/skills/sales-cockpit-builder",
                          "/Workspace/.assistant/skills/sales-cockpit-builder"] if os.path.exists(p)), None) \
    or sorted(glob.glob(f"/Workspace/Users/{user}/**/sales-cockpit-builder/SKILL.md", recursive=True))[0].rsplit("/", 1)[0]
sys.path.insert(0, skill + "/scripts")
import importlib, cockpit_lib as cl; importlib.reload(cl)
w = cl.client()
folder = f"/Users/{user}/sales-cockpit"; cfg_path = f"{folder}/cockpit_config.json"
```
If `cfg_path` exists, load it (`cl.load_config`), summarise it in 5 lines and ask what to change: jump to that step.
Pick the SQL warehouse with `cl.pick_warehouse(w)` (first one by default, say which).

**1. Interview** — `references/interview.md`. Three rounds: (a) who they are and how they sell, (b) KPIs and
targets, (c) which data they use. Write the answers into `cfg["seller"]`, `cfg["company"]`, `cfg["kpis"]`.

**2. Find and map the data** — `references/data-mapping.md`. `cl.discover(...)` ranks candidate tables per entity;
`cl.describe(...)` shows columns and sample rows. Propose a mapping per entity (table, column expressions, the filter
that keeps only the seller's book), confirm it with the seller, write it to `cfg["sources"]`. Log gaps in
`cfg["missing"]`. `accounts` is mandatory; everything else is optional.

**3. Choose where to build.** Default `cfg["target"]`: a catalog the seller can create schemas in (try their
personal/sandbox catalog; otherwise ask) and schema `sales_cockpit_<first name>`; `workspace_folder` = `folder`.
Never build into a schema that holds objects you did not create (its comment must start with "Sales cockpit of").

**4. Build the views.** `cl.build_views(w, cfg)` creates the canonical views, `targets`, `kpi_attainment`,
`account_overview` and `next_actions` (`references/kpis.md`). Then `cl.check(w, cfg)`. 0 rows in `accounts` = wrong
seller filter: fix it before going on. For each KPI, show the current actual and ask "does this match what you see
in your CRM / reports?" — fix the definition until it does.

**5. Genie space** — `references/genie-space.md`. Write the instructions, 6–10 example SQL and sample questions from
the interview, then `cl.build_genie(w, cfg, instructions, examples, sample_questions)`. Test 3 questions with
`cl.ask_genie` and fix the instructions when an answer is wrong.

**6. App** — `references/app.md`. First ask, in one message: **standard colours** (the cockpit's own: red accent on
dark navy) or **their brand colours**? For brand colours, ask for their company website, or a brand guidelines page,
or the hex codes. Build the theme as in `references/app.md` ("Colours"), show the preview, and save it in
`cfg["theme"]` once they confirm (standard = no `theme`). Then choose pages (`cfg["pages"]`), write `cfg["labels"]`
if the seller's language is neither English nor French, and run `cl.deploy_app(w, cfg)` (3–6 min). Save the config.
The layout is fixed (dark top bar, cards, gauges, Genie bubble, "Edit the app" bubble): only colours change.

**7. Hand-over.** Give: the app URL, the Genie space URL (`<host>/genie/rooms/<id>`), what each page shows, the KPIs
with today's values, what is missing and why (with the drafted data request, see step 2), and how to change things:
look and layout with the app's **✏️ Edit the app** button (undoable); new data, KPIs or pages by asking Genie Code
"update my sales cockpit". Views are live: data refreshes by itself as the sources refresh.

## Edge cases
- Several sources for one entity (e.g. two prospecting tools for `signals`): give a list of mappings, they are
  stacked (`references/config.md`).
- The seller is a manager: the filter keeps their team's book (owner IN their reports) and KPIs get an `owner`
  breakdown.
- No targets anywhere: ask for the numbers and store them in `kpis[].targets` (a small table is created).
- A build step fails: read the SQL error (`cl.sql` prints the statement), fix the mapping expression, rerun only that
  step: every function is idempotent.
