"""Sales cockpit builder: config -> views -> KPIs -> Genie space -> Databricks App.

Run from a Databricks notebook (Genie Code) or locally:
    import sys; sys.path.insert(0, "<skill folder>/scripts")
    import cockpit_lib as cl
    w = cl.client()                      # notebook: default auth; locally: cl.client(profile="...")
    cfg = cl.load_config(w, path)        # the seller's cockpit_config.json (see references/config.md)

Every function takes the WorkspaceClient `w` and the config dict `cfg`. All SQL runs on cfg["target"]["warehouse_id"]
as the signed-in user, so Unity Catalog permissions apply.
"""
import io
import json
import re
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

# Canonical entities: column -> description. Required columns first; the rest are optional.
ENTITIES = {
    "accounts": {"required": ["account_id", "account_name"],
                 "optional": ["status", "segment", "industry", "country", "region", "employees", "annual_revenue",
                              "owner", "website", "created_date"]},
    "opportunities": {"required": ["opportunity_id", "account_id", "amount", "close_date", "is_closed", "is_won"],
                      "optional": ["opportunity_name", "stage", "type", "product", "owner", "created_date",
                                   "next_step", "probability", "forecast_category"]},
    "usage": {"required": ["account_id", "usage_date", "amount"],
              "optional": ["product", "quantity", "unit"]},
    "contracts": {"required": ["contract_id", "account_id", "start_date", "end_date"],
                  "optional": ["commit_amount", "consumed_amount", "arr", "product", "status", "auto_renew"]},
    "activities": {"required": ["account_id", "activity_date"],
                   "optional": ["activity_type", "subject", "contact_id", "owner", "outcome"]},
    "contacts": {"required": ["contact_id", "account_id"],
                 "optional": ["full_name", "title", "seniority", "department", "email", "phone", "linkedin_url"]},
    "signals": {"required": ["account_id", "signal_date", "signal_type"],
                "optional": ["source", "detail", "score", "url"]},
    "leads": {"required": ["lead_id"],
              "optional": ["full_name", "company", "title", "email", "status", "source", "created_date", "score",
                           "account_id"]},
}

# Keywords used by discover() to rank candidate tables per entity.
KEYWORDS = {
    "accounts": ["account", "customer", "company", "organization", "organisation", "client"],
    "opportunities": ["opportunit", "deal", "pipeline", "opp"],
    "usage": ["usage", "consumption", "billing", "invoice", "revenue", "metering", "spend"],
    "contracts": ["contract", "subscription", "commit", "agreement", "renewal", "arr"],
    "activities": ["activit", "task", "event", "meeting", "call", "email", "engagement"],
    "contacts": ["contact", "person", "people", "stakeholder"],
    "signals": ["intent", "signal", "technograph", "firmograph", "enrich", "hiring", "job_post", "news",
                "website_visit", "prospect"],
    "leads": ["lead", "mql", "inbound"],
    "targets": ["target", "quota", "plan", "objective"],
}

# KPI metric library: metric -> (entity it needs, SQL expression over that entity aliased `t`, date column)
METRICS = {
    "bookings": ("opportunities", "sum(CASE WHEN t.is_won THEN t.amount END)", "close_date"),
    "new_logo_bookings": ("opportunities", "sum(CASE WHEN t.is_won AND lower(t.type) LIKE '%new%' THEN t.amount END)",
                          "close_date"),
    "expansion_bookings": ("opportunities",
                           "sum(CASE WHEN t.is_won AND lower(coalesce(t.type, '')) NOT LIKE '%new%' THEN t.amount END)",
                           "close_date"),
    "deals_won": ("opportunities", "count(CASE WHEN t.is_won THEN 1 END)", "close_date"),
    "win_rate_pct": ("opportunities", "100 * count(CASE WHEN t.is_won THEN 1 END) / nullif(count(CASE WHEN t.is_closed "
                     "THEN 1 END), 0)", "close_date"),
    "pipeline_created": ("opportunities", "sum(t.amount)", "created_date"),
    "open_pipeline": ("opportunities", "sum(CASE WHEN NOT t.is_closed THEN t.amount END)", "close_date"),
    "consumption": ("usage", "sum(t.amount)", "usage_date"),
    "new_logos": ("opportunities", "count(DISTINCT CASE WHEN t.is_won AND lower(t.type) LIKE '%new%' "
                  "THEN t.account_id END)", "close_date"),
    "activities": ("activities", "count(*)", "activity_date"),
    "meetings": ("activities", "count(CASE WHEN lower(t.activity_type) LIKE '%meeting%' THEN 1 END)", "activity_date"),
}
# Point-in-time metrics (not bound to a period): metric -> (entity, expression, filter)
SNAPSHOT_METRICS = {
    "arr": ("contracts", "sum(t.arr)", "t.start_date <= current_date() AND t.end_date >= current_date()"),
    "commit_consumed_pct": ("contracts", "100 * sum(t.consumed_amount) / nullif(sum(t.commit_amount), 0)",
                            "t.start_date <= current_date() AND t.end_date >= current_date()"),
}
PERIOD_MONTHS = {"month": 1, "quarter": 3, "half": 6, "year": 12}

# Next-best-action rules: rule -> (entities needed, priority, SQL). {ns} = cockpit schema.
ACTION_RULES = {
    "overdue_deal": (["opportunities"], 1, """
SELECT o.account_id, 'Deal past its close date' AS reason,
  concat(coalesce(o.opportunity_name, o.opportunity_id), ' · ', coalesce(o.stage, ''), ' · close date ', o.close_date) AS detail,
  'Update the close date or close the deal' AS action
FROM {ns}.opportunities o WHERE NOT o.is_closed AND o.close_date < current_date()"""),
    "closing_soon": (["opportunities"], 1, """
SELECT o.account_id, 'Deal closing in the next 30 days' AS reason,
  concat(coalesce(o.opportunity_name, o.opportunity_id), ' · ', coalesce(o.stage, ''), ' · ', format_number(o.amount, 0)) AS detail,
  'Confirm next step and decision process' AS action
FROM {ns}.opportunities o WHERE NOT o.is_closed AND o.close_date BETWEEN current_date() AND current_date() + INTERVAL 30 DAYS"""),
    "usage_drop": (["usage"], 1, """
SELECT account_id, 'Usage dropped more than 20%' AS reason,
  concat('last 30 days ', format_number(last30, 0), ' vs previous 30 days ', format_number(prev30, 0)) AS detail,
  'Check in with the account: blocker, churn risk or seasonality?' AS action
FROM (SELECT account_id,
  sum(CASE WHEN usage_date > current_date() - INTERVAL 30 DAYS THEN amount END) AS last30,
  sum(CASE WHEN usage_date <= current_date() - INTERVAL 30 DAYS AND usage_date > current_date() - INTERVAL 60 DAYS THEN amount END) AS prev30
  FROM {ns}.usage GROUP BY account_id) WHERE prev30 > 0 AND coalesce(last30, 0) < 0.8 * prev30"""),
    "usage_growth": (["usage"], 2, """
SELECT account_id, 'Usage grew more than 30%' AS reason,
  concat('last 30 days ', format_number(last30, 0), ' vs previous 30 days ', format_number(prev30, 0)) AS detail,
  'Expansion opportunity: understand the new use case' AS action
FROM (SELECT account_id,
  sum(CASE WHEN usage_date > current_date() - INTERVAL 30 DAYS THEN amount END) AS last30,
  sum(CASE WHEN usage_date <= current_date() - INTERVAL 30 DAYS AND usage_date > current_date() - INTERVAL 60 DAYS THEN amount END) AS prev30
  FROM {ns}.usage GROUP BY account_id) WHERE prev30 > 0 AND last30 > 1.3 * prev30"""),
    "commit_underburn": (["contracts"], 1, """
SELECT account_id, 'Commitment under-consumed' AS reason,
  concat(CAST(round(100 * consumed_amount / commit_amount) AS INT), '% consumed, ',
         CAST(round(100 * datediff(current_date(), start_date) / greatest(datediff(end_date, start_date), 1)) AS INT), '% of term elapsed') AS detail,
  'Build a consumption plan before renewal' AS action
FROM {ns}.contracts WHERE commit_amount > 0 AND start_date <= current_date() AND end_date >= current_date()
  AND 100 * consumed_amount / commit_amount < 100 * datediff(current_date(), start_date) / greatest(datediff(end_date, start_date), 1) - 15"""),
    "commit_overburn": (["contracts"], 2, """
SELECT account_id, 'Commitment will run out early' AS reason,
  concat(CAST(round(100 * consumed_amount / commit_amount) AS INT), '% consumed, ',
         CAST(round(100 * datediff(current_date(), start_date) / greatest(datediff(end_date, start_date), 1)) AS INT), '% of term elapsed') AS detail,
  'Propose an early renewal or a bigger commitment' AS action
FROM {ns}.contracts WHERE commit_amount > 0 AND start_date <= current_date() AND end_date >= current_date()
  AND 100 * consumed_amount / commit_amount > 100 * datediff(current_date(), start_date) / greatest(datediff(end_date, start_date), 1) + 15"""),
    "renewal_due": (["contracts"], 1, """
SELECT account_id, 'Contract ends within 120 days' AS reason, concat('ends ', end_date) AS detail,
  'Start the renewal conversation' AS action
FROM {ns}.contracts WHERE end_date BETWEEN current_date() AND current_date() + INTERVAL 120 DAYS"""),
    "no_recent_touch": (["activities"], 2, """
SELECT a.account_id, 'No activity in 60 days' AS reason,
  concat('last activity ', coalesce(cast(max(x.activity_date) AS STRING), 'never')) AS detail,
  'Re-engage: share something relevant to their business' AS action
FROM {ns}.accounts a LEFT JOIN {ns}.activities x ON x.account_id = a.account_id
GROUP BY a.account_id HAVING max(x.activity_date) IS NULL OR max(x.activity_date) < current_date() - INTERVAL 60 DAYS"""),
    "new_signal": (["signals"], 2, """
SELECT account_id, concat('New signal: ', signal_type) AS reason,
  concat(coalesce(source, ''), ' · ', coalesce(detail, ''), ' · ', signal_date) AS detail,
  'Use it as a reason to reach out' AS action
FROM {ns}.signals WHERE signal_date >= current_date() - INTERVAL 14 DAYS"""),
}


# ----------------------------------------------------------------------------- client, config, SQL
def client(profile=None):
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient(profile=profile) if profile else WorkspaceClient()


def me(w):
    return w.current_user.me().user_name


def load_config(w, path):
    return json.loads(w.workspace.download(path).read().decode())


def save_config(w, cfg, path):
    upload(w, path, json.dumps(cfg, indent=2, ensure_ascii=False).encode())


def upload(w, path, data):
    from databricks.sdk.service.workspace import ImportFormat
    w.workspace.mkdirs(path.rsplit("/", 1)[0])
    w.workspace.upload(path, io.BytesIO(data), format=ImportFormat.AUTO, overwrite=True)


def sql(w, warehouse_id, statement, rows=True):
    """Run one statement, wait, return a list of dicts (or [] for DDL). Raises RuntimeError with the SQL error."""
    r = w.api_client.do("POST", "/api/2.0/sql/statements", body={
        "warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s",
        "disposition": "INLINE", "format": "JSON_ARRAY", "on_wait_timeout": "CONTINUE"})
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        r = w.api_client.do("GET", f"/api/2.0/sql/statements/{r['statement_id']}")
    if r["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"{r['status'].get('error', {}).get('message', r['status']['state'])}\n--- SQL:\n{statement}")
    if not rows or "manifest" not in r:
        return []
    cols = [c["name"] for c in r["manifest"]["schema"]["columns"]]
    data = list(r.get("result", {}).get("data_array") or [])
    chunk = r.get("result", {}).get("next_chunk_internal_link")
    while chunk:
        nxt = w.api_client.do("GET", chunk)
        data += nxt.get("data_array") or []
        chunk = nxt.get("next_chunk_internal_link")
    return [dict(zip(cols, row)) for row in data]


def pick_warehouse(w):
    """Return [{id, name, state, serverless}] the user can use, serverless first."""
    out = [{"id": x.id, "name": x.name, "state": str(x.state.value if x.state else ""),
            "serverless": bool(x.enable_serverless_compute)} for x in w.warehouses.list()]
    return sorted(out, key=lambda x: (not x["serverless"], x["state"] != "RUNNING", x["name"]))


def q(name):
    """Quote a column name for SQL."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else f"`{name.replace('`', '``')}`"


# ----------------------------------------------------------------------------- 1. discovery
def list_catalogs(w):
    """Catalogs the user can see (fast, no SQL): pick the relevant ones with the seller before discover()."""
    skip = {"system", "samples", "__databricks_internal"}
    return sorted(c.name for c in w.catalogs.list() if c.name not in skip)


def discover(w, warehouse_id, catalogs, entities=None, schemas=None, limit=6):
    """Rank tables the user can read in `catalogs` for each entity, from table/column names and comments.

    Returns {entity: [{"table", "score", "comment", "owner", "type", "columns": [...]}]}. Read-only: uses each
    catalog's information_schema, which only lists objects the user can access. Keep `catalogs` short (the
    ones list_catalogs() + the seller point to): scanning every catalog of a big workspace is slow.
    """
    entities = entities or list(KEYWORDS)
    pattern = "|".join(sorted({k for e in entities for k in KEYWORDS[e]}))
    in_schemas = ("AND table_schema IN (" + ", ".join(f"'{x}'" for x in schemas) + ")") if schemas else ""
    tables, colmap = [], {}
    for cat in catalogs:
        try:
            tabs = sql(w, warehouse_id, f"""
SELECT table_catalog || '.' || table_schema || '.' || table_name AS fqn, lower(table_name) AS name,
  lower(coalesce(comment, '')) AS comment, table_owner AS owner, table_type AS type
FROM {cat}.information_schema.tables
WHERE table_schema <> 'information_schema' {in_schemas}
  AND (lower(table_name) RLIKE '{pattern}' OR lower(coalesce(comment, '')) RLIKE '{pattern}')""")
        except RuntimeError as e:
            print(f"skipped catalog {cat}: {str(e).splitlines()[0][:150]}")
            continue
        tables += tabs
        for i in range(0, len(tabs), 200):
            names = ", ".join("'" + t["fqn"].split(".", 1)[1].replace("'", "''") + "'" for t in tabs[i:i + 200])
            for r in sql(w, warehouse_id, f"""
SELECT table_catalog || '.' || table_schema || '.' || table_name AS fqn,
  concat_ws(',', collect_list(lower(column_name))) AS cols
FROM {cat}.information_schema.columns
WHERE table_schema || '.' || table_name IN ({names}) GROUP BY 1"""):
                colmap[r["fqn"]] = (r["cols"] or "").split(",")
    out = {}
    for ent in entities:
        kws = KEYWORDS[ent]
        hints = ENTITIES.get(ent, {}).get("required", [])
        ranked = []
        for t in tables:
            c = colmap.get(t["fqn"], [])
            score = 5 * sum(k in t["name"] for k in kws) + 2 * sum(k in t["comment"] for k in kws)
            score += sum(any(k in col for col in c) for k in kws)
            score += sum(any(h.split("_")[0] in col for col in c) for h in hints)
            if any(x in t["name"] for x in ("_history", "_staging", "_tmp", "_backup", "_bak")):
                score -= 5
            if score >= 5:
                ranked.append({"table": t["fqn"], "score": score, "comment": t["comment"][:200], "owner": t["owner"],
                               "type": t["type"], "columns": c[:60]})
        out[ent] = sorted(ranked, key=lambda x: -x["score"])[:limit]
    return out


def describe(w, warehouse_id, table, sample=5):
    """Columns with types, plus a few sample rows, to propose a mapping."""
    cols = sql(w, warehouse_id, f"DESCRIBE TABLE {table}")
    cols = [c for c in cols if c.get("col_name") and not c["col_name"].startswith("#")]
    rows = sql(w, warehouse_id, f"SELECT * FROM {table} LIMIT {int(sample)}")
    return {"columns": [(c["col_name"], c["data_type"]) for c in cols], "sample": rows}


# ----------------------------------------------------------------------------- 2. views
def ns(cfg):
    return f"{cfg['target']['catalog']}.{cfg['target']['schema']}"


def _mappings(cfg, entity):
    m = cfg.get("sources", {}).get(entity)
    if not m:
        return []
    return m if isinstance(m, list) else [m]


def present(cfg):
    """Entities that have a mapping (plus targets when the seller typed them in)."""
    have = {e for e in ENTITIES if _mappings(cfg, e)}
    if _mappings(cfg, "targets") or any(k.get("targets") for k in cfg.get("kpis", [])):
        have.add("targets")
    return have


def _select(entity, m, extra_keys):
    cols = m["columns"]
    spec = ENTITIES[entity]
    missing = [c for c in spec["required"] if c not in cols]
    if missing:
        raise ValueError(f"{entity} mapping of {m['table']}: required columns missing: {missing}")
    parts = []
    for c in spec["required"] + spec["optional"]:
        expr = cols.get(c)
        parts.append(f"{expr} AS {c}" if expr else f"CAST(NULL AS STRING) AS {c}")
    extra = m.get("extra_columns") or {}
    for alias in extra_keys:  # same extra columns in every source of the entity (NULL when absent)
        parts.append(f"{extra[alias] if alias in extra else 'NULL'} AS {q(alias)}")
    where = [f"({m['filter']})"] if m.get("filter") else []
    body = f"SELECT {', '.join(parts)}\nFROM {m['table']}" + (f"\nWHERE {' AND '.join(where)}" if where else "")
    return body


def _typed(entity, inner, ns_, scope_to_accounts, extra_keys):
    """Cast canonical columns to stable types and scope to the seller's accounts."""
    types = {"amount": "DOUBLE", "commit_amount": "DOUBLE", "consumed_amount": "DOUBLE", "arr": "DOUBLE",
             "quantity": "DOUBLE", "probability": "DOUBLE", "score": "DOUBLE", "employees": "BIGINT",
             "annual_revenue": "DOUBLE", "is_closed": "BOOLEAN", "is_won": "BOOLEAN",
             "close_date": "DATE", "created_date": "DATE", "usage_date": "DATE", "start_date": "DATE",
             "end_date": "DATE", "activity_date": "DATE", "signal_date": "DATE"}
    spec = ENTITIES[entity]
    cols = []
    for c in spec["required"] + spec["optional"]:
        t = types.get(c, "STRING")
        cols.append(f"CAST({c} AS {t}) AS {c}" if t != "STRING" else f"CAST({c} AS STRING) AS {c}")
    sel = ", ".join(cols + [q(k) for k in extra_keys])
    where = ""
    if scope_to_accounts and "account_id" in spec["required"] + spec["optional"]:
        where = f"\nWHERE CAST(account_id AS STRING) IN (SELECT account_id FROM {ns_}.accounts)"
    return f"SELECT {sel}\nFROM ({inner}) src{where}"


def build_views(w, cfg, log=print):
    """Create the schema, one canonical view per mapped entity, the targets table and derived views."""
    wh, n = cfg["target"]["warehouse_id"], ns(cfg)
    sql(w, wh, f"CREATE SCHEMA IF NOT EXISTS {n} COMMENT 'Sales cockpit of {cfg['seller']['email']}'", rows=False)
    have = present(cfg)
    if "accounts" not in have:
        raise ValueError("accounts mapping is required: every page starts from the seller's accounts")
    for entity in ["accounts"] + [e for e in ENTITIES if e != "accounts" and e in have]:
        maps = _mappings(cfg, entity)
        keys = sorted({k for m in maps for k in (m.get("extra_columns") or {})})
        inner = "\nUNION ALL\n".join(f"({_select(entity, m, keys)})" for m in maps)
        scope = entity != "accounts" and not any(m.get("own_scope") for m in maps)
        stmt = f"CREATE OR REPLACE VIEW {n}.{entity} AS\n{_typed(entity, inner, n, scope, keys)}"
        sql(w, wh, stmt, rows=False)
        cnt = sql(w, wh, f"SELECT count(*) AS n FROM {n}.{entity}")[0]["n"]
        log(f"view {n}.{entity}: {cnt} rows")
    build_targets(w, cfg, log)
    build_derived(w, cfg, log)


def build_targets(w, cfg, log=print):
    """targets = mapped targets table, or a table of the values the seller typed (kpis[].targets)."""
    wh, n = cfg["target"]["warehouse_id"], ns(cfg)
    m = _mappings(cfg, "targets")
    if m:
        m = m[0]
        c = m["columns"]
        dim = c.get("dimension_value", "'All'")
        stmt = (f"CREATE OR REPLACE VIEW {n}.targets AS SELECT CAST({c['kpi_id']} AS STRING) AS kpi_id, "
                f"CAST({c['period_start']} AS DATE) AS period_start, CAST({dim} AS STRING) AS dimension_value, "
                f"CAST({c['target_value']} AS DOUBLE) AS target_value FROM {m['table']}"
                + (f" WHERE {m['filter']}" if m.get("filter") else ""))
        sql(w, wh, stmt, rows=False)
    else:
        rows = []
        for k in cfg.get("kpis", []):
            for t in k.get("targets", []):
                rows.append("('{}', DATE'{}', '{}', {})".format(
                    k["id"], t["period_start"], str(t.get("dimension_value", "All")).replace("'", "''"),
                    float(t["value"])))
        sql(w, wh, f"CREATE OR REPLACE TABLE {n}.targets (kpi_id STRING, period_start DATE, dimension_value STRING, "
                   f"target_value DOUBLE) COMMENT 'Targets typed in by the seller'", rows=False)
        if rows:
            sql(w, wh, f"INSERT INTO {n}.targets VALUES {', '.join(rows)}", rows=False)
    log(f"targets: {sql(w, wh, f'SELECT count(*) AS n FROM {n}.targets')[0]['n']} rows")


def period_bounds_sql(period, fy_start_month):
    """SQL expressions (start, end) for the current period, fiscal-year aware."""
    months = PERIOD_MONTHS[period]
    shift = int(fy_start_month) - 1
    shifted = f"add_months(current_date(), -{shift})"
    if months == 1:
        start = "date_trunc('MONTH', current_date())"
    elif months == 12:
        start = f"add_months(date_trunc('YEAR', {shifted}), {shift})"
    else:
        start = (f"add_months(date_trunc('YEAR', {shifted}), {shift} + "
                 f"{months} * floor((month({shifted}) - 1) / {months}))")
    start = f"CAST({start} AS DATE)"
    return start, f"add_months({start}, {months})"


def _kpi_sql(k, n, fy, have):
    metric = k["metric"]
    custom = k.get("sql")  # optional: a full SELECT returning dimension_value, actual over {ns}
    period = "now" if metric in SNAPSHOT_METRICS else k.get("period", "quarter")
    start, end = ("current_date()", "date_add(current_date(), 1)") if period == "now" else period_bounds_sql(period, fy)
    dim = k.get("breakdown")
    head = (f"'{k['id']}' AS kpi_id, '{k['label'].replace(chr(39), chr(39) * 2)}' AS kpi_label, '{period}' AS period, "
            f"{start} AS period_start, {end} AS period_end")
    if custom:
        return f"SELECT {head}, CAST(dimension_value AS STRING) AS dimension_value, CAST(actual AS DOUBLE) AS actual " \
               f"FROM ({custom.replace('{ns}', n)})"
    if metric in METRICS:
        entity, expr, dcol = METRICS[metric]
        where = f"t.{dcol} >= {start} AND t.{dcol} < {end}"
    elif metric in SNAPSHOT_METRICS:
        entity, expr, where = SNAPSHOT_METRICS[metric]
    else:
        raise ValueError(f"KPI {k['id']}: unknown metric {metric} (use a custom 'sql')")
    if entity not in have:
        return None
    if not metric.endswith("_pct"):
        expr = f"coalesce({expr}, 0)"
    src = f"{n}.{entity} t"
    if dim:
        acc_cols = ENTITIES["accounts"]["required"] + ENTITIES["accounts"]["optional"]
        dim_expr = f"a.{dim}" if dim in acc_cols and dim not in ENTITIES[entity]["required"] + ENTITIES[entity]["optional"] \
            else f"t.{dim}"
        if dim_expr.startswith("a."):
            src += f" LEFT JOIN {n}.accounts a ON a.account_id = t.account_id"
        by = (f"SELECT {head}, coalesce(CAST({dim_expr} AS STRING), 'Unknown') AS dimension_value, "
              f"CAST({expr} AS DOUBLE) AS actual FROM {src} WHERE {where} GROUP BY 1, 2, 3, 4, 5, 6")
    total = f"SELECT {head}, 'All' AS dimension_value, CAST({expr} AS DOUBLE) AS actual FROM {n}.{entity} t WHERE {where}"
    return total + (f"\nUNION ALL\n{by}" if dim else "")


def build_derived(w, cfg, log=print):
    wh, n, have = cfg["target"]["warehouse_id"], ns(cfg), present(cfg)
    fy = cfg.get("company", {}).get("fiscal_year_start_month", 1)
    # KPI attainment
    parts = [s for s in (_kpi_sql(k, n, fy, have) for k in cfg.get("kpis", [])) if s]
    if parts:
        sql(w, wh, f"""CREATE OR REPLACE VIEW {n}.kpi_attainment COMMENT 'Actual vs target per KPI for the current period' AS
SELECT k.*, tg.target_value, round(100 * k.actual / nullif(tg.target_value, 0), 1) AS attainment_pct,
  CASE WHEN k.period <> 'now' THEN round(100 * datediff(current_date(), k.period_start) / datediff(k.period_end, k.period_start), 1)
  END AS period_elapsed_pct
FROM ({' UNION ALL '.join(f'({p})' for p in parts)}) k
LEFT JOIN {n}.targets tg ON tg.kpi_id = k.kpi_id AND tg.period_start = k.period_start
  AND tg.dimension_value = k.dimension_value""", rows=False)
        log(f"kpi_attainment: {len(parts)} KPIs")
    # Account overview
    sel, joins = ["a.*"], []
    if "opportunities" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id, sum(CASE WHEN NOT is_closed THEN amount END) AS open_pipeline,
  count(CASE WHEN NOT is_closed THEN 1 END) AS open_deals, max(CASE WHEN is_won THEN close_date END) AS last_won_date,
  sum(CASE WHEN is_won AND close_date >= current_date() - INTERVAL 365 DAYS THEN amount END) AS won_last_12m
  FROM {n}.opportunities GROUP BY account_id) o ON o.account_id = a.account_id""")
        sel += ["o.open_pipeline", "o.open_deals", "o.last_won_date", "o.won_last_12m"]
    if "usage" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id,
  sum(CASE WHEN usage_date > current_date() - INTERVAL 90 DAYS THEN amount END) AS usage_last_90d,
  sum(CASE WHEN usage_date <= current_date() - INTERVAL 90 DAYS AND usage_date > current_date() - INTERVAL 180 DAYS THEN amount END) AS usage_prev_90d
  FROM {n}.usage GROUP BY account_id) u ON u.account_id = a.account_id""")
        sel += ["u.usage_last_90d", "u.usage_prev_90d",
                "round(100 * (u.usage_last_90d - u.usage_prev_90d) / nullif(u.usage_prev_90d, 0), 1) AS usage_trend_pct"]
    if "contracts" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id, sum(arr) AS arr, sum(commit_amount) AS commit_amount,
  sum(consumed_amount) AS consumed_amount, min(end_date) AS next_contract_end
  FROM {n}.contracts WHERE end_date >= current_date() GROUP BY account_id) c ON c.account_id = a.account_id""")
        sel += ["c.arr", "c.commit_amount", "c.consumed_amount", "c.next_contract_end",
                "round(100 * c.consumed_amount / nullif(c.commit_amount, 0), 1) AS commit_consumed_pct"]
    if "activities" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id, max(activity_date) AS last_activity_date,
  count(CASE WHEN activity_date >= current_date() - INTERVAL 90 DAYS THEN 1 END) AS activities_last_90d
  FROM {n}.activities GROUP BY account_id) x ON x.account_id = a.account_id""")
        sel += ["x.last_activity_date", "x.activities_last_90d"]
    if "signals" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id, count(*) AS signals_last_90d, max(signal_date) AS last_signal_date
  FROM {n}.signals WHERE signal_date >= current_date() - INTERVAL 90 DAYS GROUP BY account_id) s ON s.account_id = a.account_id""")
        sel += ["s.signals_last_90d", "s.last_signal_date"]
    if "contacts" in have:
        joins.append(f"""LEFT JOIN (SELECT account_id, count(*) AS contacts FROM {n}.contacts GROUP BY account_id) ct
  ON ct.account_id = a.account_id""")
        sel += ["ct.contacts"]
    sql(w, wh, f"CREATE OR REPLACE VIEW {n}.account_overview COMMENT 'One row per account of the seller' AS\n"
               f"SELECT {', '.join(sel)}\nFROM {n}.accounts a\n" + "\n".join(joins), rows=False)
    log("account_overview: ok")
    # Next best actions
    rules = cfg.get("action_rules") or [r for r, (need, _, _) in ACTION_RULES.items() if set(need) <= have]
    parts = []
    for r in rules:
        need, prio, body = ACTION_RULES[r]
        if set(need) <= have:
            parts.append(f"SELECT '{r}' AS rule, {prio} AS priority, z.* FROM ({body.format(ns=n)}) z")
    if parts:
        sql(w, wh, f"""CREATE OR REPLACE VIEW {n}.next_actions COMMENT 'Rule-based next best actions (priority 1 = this week)' AS
SELECT x.priority, a.account_name, a.status AS account_status, x.rule, x.reason, x.detail, x.action, x.account_id
FROM ({' UNION ALL '.join(parts)}) x JOIN {n}.accounts a ON a.account_id = x.account_id""", rows=False)
        log(f"next_actions: {len(parts)} rules")


# ----------------------------------------------------------------------------- 3. Genie space
def _id(s):
    import hashlib
    return hashlib.md5(s.encode()).hexdigest()


def genie_tables(cfg):
    have = present(cfg)
    t = [e for e in ENTITIES if e in have] + ["targets", "account_overview"]
    if cfg.get("kpis"):
        t.append("kpi_attainment")
    t.append("next_actions")
    return sorted(set(t))


def build_genie(w, cfg, instructions, examples, sample_questions, log=print):
    """Create or update the seller's private Genie space. `instructions` = text written from the interview
    (references/genie-space.md); `examples` = [(question, sql with {ns})]. Saves the id in cfg["target"]."""
    n, t = ns(cfg), cfg["target"]
    space = {
        "version": 1,
        "config": {"sample_questions": sorted([{"id": _id(x), "question": [x]} for x in sample_questions],
                                              key=lambda x: x["id"])},
        "data_sources": {"tables": [{"identifier": f"{n}.{x}"} for x in genie_tables(cfg)]},
        "instructions": {
            "text_instructions": [{"id": _id("main"), "content": [instructions]}],
            "example_question_sqls": sorted([{"id": _id(qq), "question": [qq], "sql": [s.replace("{ns}", n)]}
                                             for qq, s in examples], key=lambda x: x["id"]),
        },
    }
    for qq, s in examples:  # fail early on a broken example
        sql(w, t["warehouse_id"], f"SELECT * FROM ({s.replace('{ns}', n)}) LIMIT 1")
    body = {"warehouse_id": t["warehouse_id"], "serialized_space": json.dumps(space),
            "description": f"Private sales cockpit of {cfg['seller']['name']}: accounts, pipeline, KPIs and signals."}
    cfg.setdefault("genie", {})["sample_questions"] = list(sample_questions)
    sid = t.get("genie_space_id")
    if sid:
        try:
            w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{sid}", body=body)
            log(f"Genie space updated: {sid}")
            return sid
        except Exception as e:  # deleted or no access: create a new one
            log(f"could not update space {sid} ({e}); creating a new one")
    body.update(title=f"Sales cockpit — {cfg['seller']['name']}", parent_path=t["workspace_folder"])
    w.workspace.mkdirs(t["workspace_folder"])
    sid = w.api_client.do("POST", "/api/2.0/genie/spaces", body=body)["space_id"]
    t["genie_space_id"] = sid
    log(f"Genie space created: {sid}")
    return sid


def ask_genie(w, cfg, question, timeout=180):
    """Ask the space one question; returns {"text", "sql", "rows"} (test helper)."""
    sid = cfg["target"]["genie_space_id"]
    r = w.api_client.do("POST", f"/api/2.0/genie/spaces/{sid}/start-conversation", body={"content": question})
    cid, mid = r["conversation_id"], r["message_id"]
    end = time.time() + timeout
    while time.time() < end:
        m = w.api_client.do("GET", f"/api/2.0/genie/spaces/{sid}/conversations/{cid}/messages/{mid}")
        if m["status"] in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            break
        time.sleep(3)
    out = {"status": m["status"], "text": None, "sql": None}
    for a in m.get("attachments") or []:
        if a.get("text"):
            out["text"] = a["text"].get("content")
        if a.get("query"):
            out["sql"] = a["query"].get("query")
            out["description"] = a["query"].get("description")
    return out


# ----------------------------------------------------------------------------- 4. Databricks App
APP_FILES = ["server.py", "labels.py", "requirements.txt", "static/index.html", "static/styles.css", "static/app.js"]
EDITOR_MODELS = ["claude-sonnet", "claude-opus", "gpt-5", "gpt-6", "claude", "gpt", "llama", "qwen"]


def pick_editor_model(w):
    """Best chat endpoint for the "Edit the app" button (pay-per-token foundation models), or None."""
    names = [e.name for e in w.serving_endpoints.list() if e.name]
    for pref in EDITOR_MODELS:
        hits = sorted((n for n in names if pref in n.lower()), reverse=True)  # highest version first
        if hits:
            return hits[0]
    return None


def _app_yaml(resources):
    env = {"sql-warehouse": "DATABRICKS_WAREHOUSE_ID", "genie-space": "GENIE_SPACE_ID", "editor-llm": "EDITOR_ENDPOINT"}
    lines = ['command: ["python", "server.py"]', "env:"]
    for r in resources:
        lines += [f"  - name: {env[r['name']]}", f"    valueFrom: {r['name']}"]
    return ("\n".join(lines) + "\n").encode()


def _grant_sp(w, kind, obj_id, sp, level):
    w.api_client.do("PATCH", f"/api/2.0/permissions/{kind}/{obj_id}",
                    body={"access_control_list": [{"service_principal_name": sp, "permission_level": level}]})


def deploy_app(w, cfg, log=print, wait=True, refresh_code=False):
    """Upload the app + cockpit_config.json to <workspace_folder>/app, create the app if needed (resources: SQL
    warehouse, Genie space, model endpoint of the editor), grant its service principal read access to the cockpit
    schema and edit rights on its own code (for "Edit the app"), deploy.

    The code is uploaded on the first deploy only (or with refresh_code=True): later deploys keep the changes the
    seller made with "Edit the app". The config is always rewritten from cfg."""
    t = cfg["target"]
    name = t.get("app_name") or re.sub(r"[^a-z0-9-]", "-", f"sales-cockpit-{me(w).split('@')[0]}".lower())[:30].strip("-")
    t["app_name"] = name
    t["owner_user"] = me(w)
    src = f"{t['workspace_folder']}/app"
    if "editor_endpoint" not in t:
        t["editor_endpoint"] = pick_editor_model(w)
        log(f"editor model: {t['editor_endpoint'] or 'none found (the Edit button is hidden)'}")
    resources = [{"name": "sql-warehouse", "sql_warehouse": {"id": t["warehouse_id"], "permission": "CAN_USE"}}]
    if t.get("genie_space_id"):
        resources.append({"name": "genie-space", "genie_space": {"name": "cockpit", "space_id": t["genie_space_id"],
                                                                  "permission": "CAN_RUN"}})
    if t.get("editor_endpoint"):
        resources.append({"name": "editor-llm", "serving_endpoint": {"name": t["editor_endpoint"],
                                                                      "permission": "CAN_QUERY"}})
    first = True
    try:
        w.workspace.get_status(f"{src}/server.py")
        first = False
    except Exception:
        pass
    for f in APP_FILES if (first or refresh_code) else []:
        upload(w, f"{src}/{f}", (SKILL_DIR / "assets" / "app" / f).read_bytes())
    log("app code uploaded" if (first or refresh_code) else "app code kept (seller edits preserved)")
    upload(w, f"{src}/app.yaml", _app_yaml(resources))
    public = {k: v for k, v in cfg.items() if k not in ("sources",)}  # the app does not need source mappings
    public["present"] = sorted(present(cfg))
    public["ns"] = ns(cfg)
    upload(w, f"{src}/cockpit_config.json", json.dumps(public, indent=2, ensure_ascii=False).encode())
    try:
        app = w.api_client.do("GET", f"/api/2.0/apps/{name}")
        w.api_client.do("PATCH", f"/api/2.0/apps/{name}", body={"name": name, "resources": resources})
        log(f"app {name} exists: updating")
    except Exception:
        try:
            app = w.api_client.do("POST", "/api/2.0/apps", body={
                "name": name, "description": f"Sales cockpit of {cfg['seller']['name']}", "resources": resources})
        except Exception as e:  # Apps disabled, app quota reached, no permission: the Genie space still works
            log(f"APP NOT CREATED: {str(e).splitlines()[0][:300]}")
            return None
        log(f"app {name} created")
    for _ in range(120):  # compute must be ACTIVE before deploying
        app = w.api_client.do("GET", f"/api/2.0/apps/{name}")
        st = app.get("compute_status", {}).get("state")
        if st == "ACTIVE":
            break
        if st in ("STOPPED",):
            w.api_client.do("POST", f"/api/2.0/apps/{name}/start")
        time.sleep(10)
    sp = app.get("service_principal_client_id")
    cat, sch = t["catalog"], t["schema"]
    for g in (f"GRANT USE CATALOG ON CATALOG {cat} TO `{sp}`", f"GRANT USE SCHEMA ON SCHEMA {cat}.{sch} TO `{sp}`",
              f"GRANT SELECT ON SCHEMA {cat}.{sch} TO `{sp}`"):
        sql(w, t["warehouse_id"], g, rows=False)
    if t.get("editor_endpoint"):  # "Edit the app": write its own code, redeploy itself
        try:
            _grant_sp(w, "directories", w.workspace.get_status(src).object_id, sp, "CAN_MANAGE")
            _grant_sp(w, "apps", name, sp, "CAN_MANAGE")
        except Exception as e:
            log(f"editor permissions not granted ({str(e).splitlines()[0][:200]}): edits will not survive a redeploy")
    full_src = src if src.startswith("/Workspace") else f"/Workspace{src}"
    dep = w.api_client.do("POST", f"/api/2.0/apps/{name}/deployments",
                          body={"source_code_path": full_src, "mode": "SNAPSHOT"})
    log(f"deployment {dep.get('deployment_id')} started")
    if wait:
        for _ in range(90):
            d = w.api_client.do("GET", f"/api/2.0/apps/{name}/deployments/{dep['deployment_id']}")
            st = d.get("status", {}).get("state")
            if st in ("SUCCEEDED", "FAILED", "CANCELLED"):
                log(f"deployment {st}: {d.get('status', {}).get('message', '')}")
                break
            time.sleep(10)
    app = w.api_client.do("GET", f"/api/2.0/apps/{name}")
    t["app_url"] = app.get("url")
    log(f"app url: {app.get('url')}")
    return app.get("url")


# ----------------------------------------------------------------------------- 4b. brand colours (optional)
STANDARD_THEME = {}  # empty = the standard cockpit colours of styles.css
_PALETTE = {"c2": "#0B7FA3", "c3": "#B07A00", "c4": "#6A4CC2", "c5": "#1F9A64"}


def _rgb(hx):
    hx = hx.lstrip("#")
    if len(hx) == 3:
        hx = "".join(c * 2 for c in hx)
    return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _hls(hx):
    import colorsys
    return colorsys.rgb_to_hls(*(c / 255 for c in _rgb(hx)))


def _from_hls(h, l, s):
    import colorsys
    return _hex(tuple(255 * c for c in colorsys.hls_to_rgb(h, max(0, min(1, l)), max(0, min(1, s)))))


def contrast(a, b):
    """WCAG contrast ratio of two hex colours (4.5 = normal text, 3 = large/bold text)."""
    def lum(hx):
        c = [x / 255 for x in _rgb(hx)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _shift(hx, target, against, step):
    """Lighten (step > 0) or darken (step < 0) hx until its contrast against `against` reaches `target`."""
    h, l, s = _hls(hx)
    out = hx
    while contrast(out, against) < target and 0.02 < l < 0.98:
        l += step
        out = _from_hls(h, l, s)
    return out


def brand_colors_from_url(url, max_css=6, timeout=15):
    """Candidate brand colours of a web page (company website or brand guidelines page), most used first.

    Returns {"url", "colors": [{"hex", "score", "hint"}], "darks": [hex], "error"}. Reads the page, its <style>
    blocks, inline styles and up to `max_css` linked stylesheets; theme-color and CSS variables named
    brand/primary/accent weigh more. Fails softly (error set) when the workspace has no internet access."""
    import urllib.request
    from collections import Counter
    from urllib.parse import urljoin
    ua = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
    get = lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=ua), timeout=timeout).read(3_000_000).decode("utf-8", "ignore")
    if not url.startswith("http"):
        url = "https://" + url
    try:
        html = get(url)
    except Exception as e:
        return {"url": url, "colors": [], "darks": [], "error": f"could not read the page: {e}"}
    texts = [html]
    for href in re.findall(r'<link[^>]+rel=["\']?stylesheet[^>]*>', html, re.I)[:max_css]:
        m = re.search(r'href=["\']([^"\']+)', href)
        if m:
            try:
                texts.append(get(urljoin(url, m.group(1))))
            except Exception:
                pass
    score, hints = Counter(), {}

    def add(hx, w, hint=None):
        if len(hx) in (4, 7):
            hx = _hex(_rgb(hx))
            score[hx] += w
            if hint:
                hints.setdefault(hx, hint)
    for m in re.finditer(r'<meta[^>]+(?:theme-color|msapplication-TileColor)[^>]+content=["\'](#[0-9a-fA-F]{3,6})', html, re.I):
        add(m.group(1), 40, "theme-color")
    for t in texts:
        for name, hx in re.findall(r'--([\w-]*(?:brand|primary|accent|main|theme)[\w-]*)\s*:\s*(#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\b', t, re.I):
            add(hx, 15, f"--{name}")
        for hx in re.findall(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b', t):
            add(hx, 1)
        for r, g, b in re.findall(r'rgba?\(\s*(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})', t):
            add(_hex((int(r), int(g), int(b))), 1)
    colors, darks = [], []
    for hx, sc in score.most_common():
        h, l, s_ = _hls(hx)
        if l < 0.22:
            if sc >= 3 and s_ >= 0.2:  # a coloured dark (navy, dark green…), not plain black/grey
                darks.append(hx)
            continue
        if s_ < 0.25 or l > 0.9 or l < 0.15:  # greys, near white/black: not a brand colour
            continue
        if any(sum((a - b) ** 2 for a, b in zip(_rgb(hx), _rgb(c["hex"]))) < 40 ** 2 for c in colors):
            continue  # near-duplicate shade
        colors.append({"hex": hx, "score": sc, "hint": hints.get(hx, "")})
    return {"url": url, "colors": colors[:8], "darks": darks[:3], "error": None if colors else "no clear colour found"}


def make_theme(primary, dark=None):
    """Theme (CSS variable -> value) from the brand's main colour, and optionally a dark brand colour for the top bar
    and hero. Keeps every text readable: white on buttons >= 3:1, accent text >= 4.5:1, hero texts >= 4.5:1.
    Returns (theme, notes) — notes say which colours were adjusted, to tell the seller."""
    primary = _hex(_rgb(primary))
    notes = []
    lava = _shift(primary, 3.0, "#FFFFFF", -0.02)  # white labels on buttons and the active tab
    if lava != primary:
        notes.append(f"buttons use {lava}, a slightly darker {primary}, so white text stays readable")
    ink = _shift(lava, 4.5, "#FFFFFF", -0.02)
    h, l, s_ = _hls(primary)
    if dark:
        hero = _hex(_rgb(dark))
        if contrast(hero, "#F4F7F8") < 7:
            hero = _shift(hero, 7, "#F4F7F8", -0.02)
            notes.append(f"the top bar uses {hero}, a darker {dark}, for readability")
    hero, hero2 = (hero, None) if dark else ("#0B2026", "#1B3139")  # no dark brand colour: standard navy, fits any accent
    if hero2 is None:
        hh, hl, hs = _hls(hero)
        hero2 = _from_hls(hh, min(hl + 0.07, 0.25), hs)
    em = _shift(primary, 4.5, hero2, 0.02)
    eyebrow = _shift(_from_hls(*_hls(em)[:1], min(_hls(em)[1] + 0.08, 0.92), _hls(em)[2]), 4.5, hero, 0.02)
    tint = _hex(tuple(255 - 0.12 * (255 - c) for c in _rgb(primary)))
    r, g, b = _rgb(primary)
    theme = {"lava": lava, "lava-ink": ink, "lava-tint": tint, "hero": hero, "hero2": hero2,
             "hero-glow": f"rgba({r},{g},{b},.30)", "hero-em": em, "eyebrow": eyebrow, "c1": lava}
    for k, v in _PALETTE.items():  # a chart colour too close to the brand colour gets the standard red instead
        dh = abs(_hls(v)[0] - h) * 360
        if min(dh, 360 - dh) < 25:
            theme[k] = "#E8371F"
    return theme, notes


def theme_preview_html(theme, company=""):
    """Small HTML preview (top bar, hero, stat card, buttons, pills) for displayHTML() in the notebook."""
    t = {"lava": "#FF3621", "lava-ink": "#C8260F", "lava-tint": "#FFEAE5", "hero": "#0B2026", "hero2": "#1B3139",
         "hero-glow": "rgba(255,54,33,.30)", "hero-em": "#FF6A52", "eyebrow": "#FF8A73", **(theme or {})}
    return f"""<div style="font-family:DM Sans,Segoe UI,Arial,sans-serif;border-radius:14px;overflow:hidden;max-width:720px;border:1px solid #E4DED4">
<div style="background:{t['hero']};color:#F4F7F8;padding:10px 18px;display:flex;gap:10px;align-items:center;font-size:13px">
<b>🧭 Sales Cockpit</b><span style="color:#A9BDC4">· {company}</span>
<span style="background:{t['lava']};color:#fff;border-radius:999px;padding:4px 11px;font-weight:700;margin-left:12px">Next actions</span>
<span style="color:#A9BDC4;font-weight:700">Targets</span></div>
<div style="background:radial-gradient(500px 220px at 88% -10%, {t['hero-glow']}, transparent 60%),linear-gradient(160deg,{t['hero']},{t['hero2']});color:#F4F7F8;padding:22px 18px">
<div style="font-family:monospace;font-size:11px;letter-spacing:.14em;color:{t['eyebrow']};font-weight:700">JANE DOE · ACCOUNT MANAGER</div>
<div style="font-size:30px;font-weight:800">Sales <span style="color:{t['hero-em']}">Cockpit</span></div></div>
<div style="background:#F9F7F4;padding:16px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
<div style="background:#fff;border:1px solid #E4DED4;border-top:3px solid {t['lava']};border-radius:12px;padding:10px 14px">
<div style="font-size:10px;letter-spacing:.12em;color:#56666D;font-weight:700">BOOKINGS · QUARTER</div><div style="font-size:24px;font-weight:800;color:#1B3139">€218k</div>
<div style="height:8px;width:160px;background:#F2EEE8;border-radius:4px"><div style="height:8px;width:60%;background:{t['lava']};border-radius:4px"></div></div></div>
<span style="background:{t['lava']};color:#fff;border-radius:10px;padding:8px 14px;font-weight:700;font-size:13px">✨ Make the change</span>
<span style="background:{t['lava-tint']};color:{t['lava-ink']};border-radius:999px;padding:2px 10px;font-family:monospace;font-size:11px;font-weight:700">P1</span>
<a style="color:{t['lava-ink']};font-size:13px">a link</a></div></div>"""


# ----------------------------------------------------------------------------- 5. checks and gaps
def check(w, cfg, log=print):
    """Row count of every cockpit object. Returns {object: rows or 'ERROR: ...'}."""
    wh, n = cfg["target"]["warehouse_id"], ns(cfg)
    out = {}
    for obj in genie_tables(cfg):
        try:
            out[obj] = int(sql(w, wh, f"SELECT count(*) AS n FROM {n}.{obj}")[0]["n"])
        except Exception as e:
            out[obj] = f"ERROR: {str(e).splitlines()[0][:200]}"
        log(f"{obj}: {out[obj]}")
    return out


def gaps(cfg):
    """What the seller asked for but has no data for: [{entity, needed_for}] (input of the data request message)."""
    have = present(cfg)
    need = {}
    for k in cfg.get("kpis", []):
        ent = (METRICS.get(k["metric"]) or SNAPSHOT_METRICS.get(k["metric"]) or (None,))[0]
        if ent and ent not in have:
            need.setdefault(ent, []).append(f"KPI '{k['label']}'")
    for m in cfg.get("missing", []):
        need.setdefault(m["entity"], []).append(m.get("needed_for", "requested by the seller"))
    return [{"entity": e, "needed_for": sorted(set(v))} for e, v in need.items()]
