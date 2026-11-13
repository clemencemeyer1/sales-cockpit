# Databricks App

The app (`assets/app/`): FastAPI server `server.py` + one static page (`static/index.html`, `static/app.js`,
`static/styles.css`, plain JavaScript, no build step). Design system: dark sticky top bar with pill navigation, hero
banner, cards, KPI stat cards with gauges, P1/P2 action items, sortable tables, account drawer, a **Genie** bubble
(bottom right) and an **Edit the app** bubble (bottom left). Keep that design when changing anything: reuse the
classes of `styles.css` (`card`, `stat lava|ok|warn|blue`, `pill p1|p2|ok|warn|blue`, `btn primary`, `seg`, `tbl`,
`item`, `gauge`, `drawer`…).

`cl.deploy_app(w, cfg)`:
1. on the first deploy, uploads the code to `<workspace_folder>/app`; later deploys keep it (the seller's edits) and
   only rewrite `cockpit_config.json` (without source mappings) and `app.yaml`. `refresh_code=True` overwrites the
   code with the skill's version (ask the seller first: it discards their edits);
2. picks the editor model (`cl.pick_editor_model`: a Claude, then GPT… pay-per-token endpoint) unless
   `cfg["target"]["editor_endpoint"]` is set (set it to `None` to hide the Edit button);
3. creates/updates the app `sales-cockpit-<user>` with its resources: SQL warehouse (CAN_USE), Genie space
   (CAN_RUN), editor endpoint (CAN_QUERY);
4. grants the app's service principal USE CATALOG / USE SCHEMA / SELECT on the cockpit schema (views run with their
   owner's rights, so the app reads nothing else), CAN_MANAGE on its own code folder and on the app (so "Edit the
   app" can save changes and redeploy itself);
5. deploys and waits; the URL is saved in `cfg["target"]["app_url"]`.

Only the seller (the app creator) can open it by default. To share it with their manager: app → Permissions →
CAN_USE. Viewers see the seller's data but cannot edit (the editor checks the signed-in user against
`target.owner_user`).

## Pages (`cfg["pages"]`, order = navigation order)
| page | shown when | content |
|---|---|---|
| actions | always | stat cards (P1 actions, open pipeline, usage, renewals, accounts), next_actions as P1/P2 items, filters |
| overview | always | KPI stat cards: actual, % of target, gauge (target tick + period-elapsed tick), breakdown bars |
| accounts | always | account_overview table with search and status filter; click → account drawer |
| pipeline | opportunities | open pipeline, closing in 30 days, past close date; bars by stage; columns by close month |
| usage | usage | weekly usage per product (stacked columns), biggest movers |
| contracts | contracts | commit burn cards (consumed vs elapsed), ending in 180 days, all active contracts |
| signals | signals | feed of the last 90 days, filter by source |
Genie is a bubble on every page (not a page). Account drawer (from any row): facts, 6-month usage, deals,
contracts, activities, contacts, signals of that account.

## Edit the app
The seller types a change in plain words. The server sends it with the app's code to the editor endpoint, which
answers with exact find/replace edits; they are checked (Python compiles, find text unique), saved locally and in the
app's workspace folder, with the previous version kept in `history/` (Undo). Changes to `static/` apply on reload;
changes to `server.py` / `labels.py` trigger a redeploy (the page waits and reloads, 2–5 minutes). The editor cannot
change the data model: new KPIs, sources or pages backed by new data need Genie Code ("update my sales cockpit").

## Colours
Two options, asked before deploying:
- **Standard** — the cockpit's own colours (red `#FF3621` accent, dark navy top bar and hero). Nothing to do: no
  `cfg["theme"]`.
- **Their brand** — from their website, a brand guidelines page, or hex codes they give:
```python
found = cl.brand_colors_from_url("acme.com")        # or the URL of their brand guidelines page
print(found["error"], found["colors"][:6], found["darks"])
```
  `colors` = candidate accents, most used first (`hint` = where it came from, e.g. a `--brand-primary` CSS variable or
  the page's theme-color); `darks` = coloured dark tones (navy, dark green…) usable for the top bar. Show the top 3–4
  as swatches and let the seller pick the main colour (and a dark one, optional):
```python
displayHTML("".join(f'<span style="display:inline-block;width:90px;padding:28px 0 6px;margin:4px;border-radius:10px;'
            f'background:{c["hex"]};color:#fff;text-align:center;font:12px monospace">{c["hex"]}</span>' for c in found["colors"][:4]))
theme, notes = cl.make_theme("#533AFD", dark="#1C1E54")   # dark=None keeps the standard navy (fits any accent)
displayHTML(cl.theme_preview_html(theme, cfg["company"]["name"]))
```
  `make_theme` adjusts shades only for readability (white text on buttons, accent text, hero texts): tell the seller
  the `notes`. When the page cannot be read (`error`: no internet access from the workspace, or a site built in
  JavaScript), ask for the hex codes (often in their brand guidelines, or ask marketing). When they confirm the
  preview: `cfg["theme"] = theme`. To change later: rerun `make_theme` + `deploy_app` (code and edits are kept), or
  set `cfg.pop("theme")` to go back to the standard colours.

## Language
`labels.py` ships English and French. For another language, write every key of `labels.EN` translated into
`cfg["labels"]` before deploying.

## Errors
- Deployment FAILED: app → Logs. Usual causes: a package version (`requirements.txt` in the app folder), a view that
  errors (rerun `cl.check`).
- A page shows "Could not load … PERMISSION_DENIED": rerun `cl.deploy_app` (it re-grants), or the seller is not
  allowed to grant on that catalog: build in a catalog they own.
- "Edit the app" missing: no chat endpoint in the workspace (`cl.pick_editor_model` returned None).
  "edits will not survive a redeploy" in the deploy log: the seller could not grant CAN_MANAGE to the app's service
  principal; edits still apply until the next deploy.
- `deploy_app` returns None and logs "APP NOT CREATED: …" (Apps not enabled, app quota reached, no permission to
  create apps): tell the seller the reason and that a workspace admin can fix it; the Genie space alone still works
  (give its URL).
