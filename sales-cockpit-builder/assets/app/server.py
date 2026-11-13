"""Sales cockpit (Databricks App): FastAPI API + the static page in static/ (no build step).

Data: the cockpit views listed in cockpit_config.json ("present" = entities the seller has data for), queried on the
app's SQL warehouse; results cached until "Refresh data". Genie: the seller's private space. Editor: "Edit the app"
sends a plain-words request + the app's code to a model serving endpoint and applies the edits it returns.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import uvicorn
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from labels import labels

HERE = Path(__file__).parent
w = WorkspaceClient()


def cfg():  # read on every call: the editor may change it
    return json.loads((HERE / "cockpit_config.json").read_text())


C = cfg()
NS = C["ns"]
WAREHOUSE = os.getenv("DATABRICKS_WAREHOUSE_ID") or C["target"]["warehouse_id"]
SPACE = os.getenv("GENIE_SPACE_ID") or C["target"].get("genie_space_id")
LLM = os.getenv("EDITOR_ENDPOINT") or C["target"].get("editor_endpoint")
have = lambda e: e in set(C.get("present", []))

app = FastAPI(title="Sales cockpit")


@app.middleware("http")
async def no_cache(request, call_next):  # the editor changes static files in place: never serve a stale copy
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# ----------------------------------------------------------------------------- SQL with cache
_cache, loaded_at = {}, time.strftime("%Y-%m-%dT%H:%M:%S")


def sql(statement):
    if statement in _cache:
        return _cache[statement]
    r = w.api_client.do("POST", "/api/2.0/sql/statements", body={
        "warehouse_id": WAREHOUSE, "statement": statement, "wait_timeout": "50s", "disposition": "INLINE",
        "format": "JSON_ARRAY", "on_wait_timeout": "CONTINUE"})
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(1.5)
        r = w.api_client.do("GET", f"/api/2.0/sql/statements/{r['statement_id']}")
    if r["status"]["state"] != "SUCCEEDED":
        raise HTTPException(500, r["status"].get("error", {}).get("message", r["status"]["state"]))
    cols = r["manifest"]["schema"]["columns"]
    num = {c["name"] for c in cols if c["type_name"] in ("INT", "LONG", "SHORT", "BYTE", "DOUBLE", "FLOAT", "DECIMAL")}
    data = list(r.get("result", {}).get("data_array") or [])
    chunk = r.get("result", {}).get("next_chunk_internal_link")
    while chunk:
        nxt = w.api_client.do("GET", chunk)
        data += nxt.get("data_array") or []
        chunk = nxt.get("next_chunk_internal_link")
    rows = [{c["name"]: (float(v) if c["name"] in num and v is not None else v) for c, v in zip(cols, row)} for row in data]
    _cache[statement] = rows
    return rows


def many(statements):
    """Run several statements at once (cold warehouse queries are slow one by one): {key: rows}."""
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {k: ex.submit(sql, q) for k, q in statements.items()}
        return {k: f.result() for k, f in futures.items()}


def lit(s):
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


# ----------------------------------------------------------------------------- meta
PAGES = [("actions", None), ("overview", None), ("accounts", None), ("pipeline", "opportunities"), ("usage", "usage"),
         ("contracts", "contracts"), ("signals", "signals")]


@app.get("/api/meta")
def meta(req: Request):
    c = cfg()
    order = c.get("pages") or [p for p, _ in PAGES]
    need = dict(PAGES)
    s, co = c.get("seller", {}), c.get("company", {})
    return {"seller": s.get("name"), "role": s.get("role"), "book": s.get("book"), "company": co.get("name"),
            "currency": s.get("currency", "USD"), "language": s.get("language", "en"), "loaded_at": loaded_at,
            "pages": [p for p in order if p in need and (need[p] is None or have(need[p]))], "labels": labels(c),
            "kpis": c.get("kpis", []), "genie": bool(SPACE), "theme": c.get("theme") or {},
            "suggestions": c.get("genie", {}).get("sample_questions", [])[:4],
            "editor": bool(LLM), "can_edit": can_edit(req)}


@app.post("/api/refresh")
def refresh(req: Request):
    global loaded_at
    _cache.clear()
    loaded_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    return meta(req)


# ----------------------------------------------------------------------------- pages
@app.get("/api/page/actions")
def page_actions():
    q = {"acts": f"SELECT priority, account_id, account_name, account_status, rule, reason, detail, action "
                 f"FROM {NS}.next_actions ORDER BY priority, account_name",
         "acc": f"SELECT count(*) AS n, count(CASE WHEN lower(status) LIKE '%customer%' THEN 1 END) AS customers "
                f"FROM {NS}.accounts"}
    if have("opportunities"):
        q["open_pipeline"] = f"SELECT sum(amount) AS v FROM {NS}.opportunities WHERE NOT is_closed"
    if have("usage"):
        q["usage_90d"] = f"SELECT sum(amount) AS v FROM {NS}.usage WHERE usage_date > current_date() - INTERVAL 90 DAYS"
    if have("contracts"):
        q["renewals_120d"] = (f"SELECT count(*) AS v FROM {NS}.contracts "
                              f"WHERE end_date BETWEEN current_date() AND current_date() + INTERVAL 120 DAYS")
    r = many(q)
    acts, acc = r.pop("acts"), r.pop("acc")[0]
    kpi = {"accounts": acc["n"], "customers": acc["customers"], "p1": sum(a["priority"] == 1 for a in acts)}
    kpi.update({k: v[0]["v"] for k, v in r.items()})
    return {"actions": acts, "kpi": kpi}


@app.get("/api/page/overview")
def page_overview():
    if not cfg().get("kpis"):
        return {"kpis": []}
    return {"kpis": sql(f"SELECT * FROM {NS}.kpi_attainment ORDER BY kpi_id, dimension_value")}


@app.get("/api/page/accounts")
def page_accounts():
    return {"accounts": sql(f"SELECT * FROM {NS}.account_overview ORDER BY account_name")}


@app.get("/api/account/{account_id}")
def account(account_id: str):
    a = lit(account_id)
    q = {"account": f"SELECT * FROM {NS}.account_overview WHERE account_id = {a}"}
    for ent, order in (("opportunities", "close_date DESC"), ("contracts", "end_date DESC"),
                       ("activities", "activity_date DESC"), ("contacts", "title"), ("signals", "signal_date DESC")):
        if have(ent):
            q[ent] = f"SELECT * EXCEPT (account_id) FROM {NS}.{ent} WHERE account_id = {a} ORDER BY {order} LIMIT 50"
    if have("usage"):
        q["usage"] = (f"SELECT CAST(date_trunc('WEEK', usage_date) AS DATE) AS week, sum(amount) AS amount "
                      f"FROM {NS}.usage WHERE account_id = {a} AND usage_date >= current_date() - INTERVAL 182 DAYS "
                      f"GROUP BY 1 ORDER BY 1")
    out = many(q)
    out["account"] = (out["account"] or [None])[0]
    return out


@app.get("/api/page/pipeline")
def page_pipeline():
    return {"deals": sql(f"SELECT a.account_name, o.* FROM {NS}.opportunities o JOIN {NS}.accounts a USING (account_id) "
                         f"WHERE NOT o.is_closed ORDER BY o.close_date")}


@app.get("/api/page/usage")
def page_usage():
    weekly = sql(f"SELECT CAST(date_trunc('WEEK', usage_date) AS DATE) AS week, coalesce(product, 'Total') AS product, "
                 f"sum(amount) AS amount FROM {NS}.usage WHERE usage_date >= current_date() - INTERVAL 364 DAYS "
                 f"AND date_trunc('WEEK', usage_date) < date_trunc('WEEK', current_date()) GROUP BY 1, 2 ORDER BY 1")
    movers = sql(f"SELECT account_id, account_name, status, usage_last_90d, usage_prev_90d, usage_trend_pct "
                 f"FROM {NS}.account_overview WHERE coalesce(usage_last_90d, usage_prev_90d) IS NOT NULL "
                 f"ORDER BY abs(coalesce(usage_last_90d, 0) - coalesce(usage_prev_90d, 0)) DESC LIMIT 30")
    return {"weekly": weekly, "movers": movers}


@app.get("/api/page/contracts")
def page_contracts():
    return {"contracts": sql(
        f"SELECT a.account_name, c.*, round(100 * c.consumed_amount / nullif(c.commit_amount, 0), 1) AS consumed_pct, "
        f"round(100 * datediff(current_date(), c.start_date) / greatest(datediff(c.end_date, c.start_date), 1), 1) "
        f"AS elapsed_pct FROM {NS}.contracts c JOIN {NS}.accounts a USING (account_id) "
        f"WHERE c.end_date >= current_date() ORDER BY c.end_date")}


@app.get("/api/page/signals")
def page_signals():
    return {"signals": sql(f"SELECT s.*, a.account_name, a.status FROM {NS}.signals s JOIN {NS}.accounts a "
                           f"USING (account_id) WHERE s.signal_date >= current_date() - INTERVAL 90 DAYS "
                           f"ORDER BY s.signal_date DESC")}


# ----------------------------------------------------------------------------- Genie
class GenieQ(BaseModel):
    question: str
    conv_id: str | None = None


@app.post("/api/genie")
def genie(g: GenieQ):
    if not SPACE:
        raise HTTPException(400, "No Genie space is configured for this cockpit.")
    base = f"/api/2.0/genie/spaces/{SPACE}"
    if g.conv_id:
        r = w.api_client.do("POST", f"{base}/conversations/{g.conv_id}/messages", body={"content": g.question})
        cid, mid = g.conv_id, r.get("message_id") or r.get("id")
    else:
        r = w.api_client.do("POST", f"{base}/start-conversation", body={"content": g.question})
        cid, mid = r["conversation_id"], r["message_id"]
    for _ in range(120):
        m = w.api_client.do("GET", f"{base}/conversations/{cid}/messages/{mid}")
        if m["status"] in ("COMPLETED", "FAILED", "CANCELLED", "QUERY_RESULT_EXPIRED"):
            break
        time.sleep(2)
    out = {"question": g.question, "conv_id": cid}
    for a in m.get("attachments") or []:
        if a.get("text"):
            out["text"] = a["text"].get("content")
        if a.get("query"):
            out["description"], out["sql"] = a["query"].get("description"), a["query"].get("query")
            try:
                out["rows"] = sql(out["sql"])[:200]
            except HTTPException as e:
                out["error"] = e.detail
        if a.get("suggested_questions"):
            out["suggested"] = a["suggested_questions"].get("questions", [])[:3]
    if m["status"] != "COMPLETED" and not out.get("text"):
        out["error"] = (m.get("error") or {}).get("error") or m["status"]
    return out


# ----------------------------------------------------------------------------- app editor
EDITABLE = ["static/app.js", "static/styles.css", "static/index.html", "server.py", "labels.py"]
RULES = """You are editing a seller's sales cockpit, a Databricks App used by a non-technical salesperson.
Files: server.py (FastAPI: one /api/page/<id> endpoint per page, SQL on the cockpit views of schema {ns}),
static/app.js (plain JavaScript, no framework: one render function per page in PAGES, shared helpers at the top),
static/styles.css (design tokens and classes: reuse them, keep the look), labels.py (UI texts per language: a
"labels" entry in the config overrides them, so for texts change app.js or add an override in labels.py's labels()).
Page order and KPI definitions come from the cockpit builder: a new KPI or new data needs Genie Code ("update my sales
cockpit"); say so instead of faking it.
Views available: {views}.
Rules:
- Smallest change that does what is asked, in the style of the surrounding code. No refactoring, no new dependencies.
- Keep the design system (colours, cards, pills, tables). Keep texts in the seller's language ({lang}).
- The colours come from the cockpit's theme (brand or standard), applied over styles.css: to change the brand
  colours, change nothing and tell the seller to ask Genie Code ("change the colours of my sales cockpit").
- Never touch credentials, the editor code (the "app editor" section of server.py and the editor part of app.js).
- If the request is unclear, risky or impossible with the available data, change nothing and explain why.
Answer with ONLY one JSON object: {{"summary": "1-3 plain sentences for the seller, no code", "edits": [{{"file": "...",
"find": "exact text to replace, copied from the file, unique in it", "replace": "new text"}}]}}.
"edits" may be empty. "find" must match the file exactly (whitespace included)."""

job = {"state": "idle"}  # idle | running | done | failed | deploying
_lock = threading.Lock()
HIST = "history"  # in the app's workspace source folder, so it survives redeploys


def can_edit(req: Request):
    owner = cfg()["target"].get("owner_user")
    who = req.headers.get("x-forwarded-email") or req.headers.get("x-forwarded-preferred-username")
    return bool(LLM) and (not who or not owner or who.lower() == owner.lower())  # no header = local run


def _src():  # workspace folder the app is deployed from (None when run locally)
    name = os.getenv("DATABRICKS_APP_NAME")
    if not name:
        return None
    a = w.api_client.do("GET", f"/api/2.0/apps/{name}")
    return a.get("default_source_code_path") or (a.get("active_deployment") or {}).get("source_code_path")


def _persist(rel, text):
    src = _src()
    if src:
        import io
        from databricks.sdk.service.workspace import ImportFormat
        path = src.replace("/Workspace", "", 1) if src.startswith("/Workspace/") else src
        w.workspace.mkdirs(f"{path}/{rel}".rsplit("/", 1)[0])
        w.workspace.upload(f"{path}/{rel}", io.BytesIO(text.encode()), format=ImportFormat.AUTO, overwrite=True)


def _history():
    p = HERE / HIST / "changes.json"
    return json.loads(p.read_text()) if p.exists() else []


def _save_history(h):
    (HERE / HIST).mkdir(exist_ok=True)
    text = json.dumps(h[-15:], ensure_ascii=False)
    (HERE / HIST / "changes.json").write_text(text)
    _persist(f"{HIST}/changes.json", text)


def _write(files):
    for rel, text in files.items():
        (HERE / rel).write_text(text)
        _persist(rel, text)


def _redeploy():
    name, src = os.getenv("DATABRICKS_APP_NAME"), _src()
    if name and src:
        w.api_client.do("POST", f"/api/2.0/apps/{name}/deployments", body={"source_code_path": src, "mode": "SNAPSHOT"})


def _ask_llm(request, page):
    c = cfg()
    views = ", ".join(sorted(set(c.get("present", [])) | {"targets", "kpi_attainment", "account_overview", "next_actions"}))
    files = "\n\n".join(f"=== {rel} ===\n{(HERE / rel).read_text()}" for rel in EDITABLE if (HERE / rel).exists())
    msg = (f"{RULES.format(ns=NS, views=views, lang=c.get('seller', {}).get('language', 'en'))}\n\n{files}\n\n"
           f"The seller is on the '{page}' page. Their request:\n{request}")
    r = w.api_client.do("POST", f"/serving-endpoints/{LLM}/invocations",
                        body={"messages": [{"role": "user", "content": msg}], "max_tokens": 8000})
    content = r["choices"][0]["message"]["content"]
    if isinstance(content, list):  # some models return [reasoning, text] blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError("The model did not return a change.")
    return json.loads(m.group(0))


def _run(request, page):
    try:
        out = _ask_llm(request, page)
        before, after = {}, {}
        for e in out.get("edits") or []:
            rel = e.get("file")
            if rel not in EDITABLE:
                raise ValueError(f"Refused: {rel} is not editable.")
            cur = after.get(rel) or (HERE / rel).read_text()
            if cur.count(e["find"]) != 1:
                raise ValueError(f"Could not apply the change to {rel} (text not found exactly once).")
            before.setdefault(rel, (HERE / rel).read_text())
            after[rel] = cur.replace(e["find"], e["replace"], 1)
        for rel, text in after.items():  # never save something that cannot load
            if rel.endswith(".py"):
                compile(text, rel, "exec")
            if rel.endswith(".json"):
                json.loads(text)
        job["summary"] = out.get("summary", "")
        if not after:
            job.update(state="done", files=[])
            return
        _write(after)
        server = any(r.endswith(".py") for r in after)
        _save_history(_history() + [{"at": time.strftime("%Y-%m-%d %H:%M"), "request": request,
                                     "summary": job["summary"], "before": before}])
        job.update(state="deploying" if server else "done", files=sorted(after), restart=server)
        if server:
            _redeploy()
    except Exception as e:
        job.update(state="failed", error=str(e)[:500])


class Change(BaseModel):
    request: str
    page: str = ""


def _guard(req: Request):
    if req.headers.get("x-cockpit") != "1" or not can_edit(req):
        raise HTTPException(403, "Only the owner of this cockpit can edit it.")


@app.post("/api/editor/run")
def editor_run(c: Change, req: Request):
    _guard(req)
    if not c.request.strip():
        raise HTTPException(400, "Describe the change you want.")
    with _lock:
        if job["state"] == "running":
            raise HTTPException(409, "A change is already in progress.")
        job.clear()
        job.update(state="running", request=c.request.strip(), started=time.time())
    threading.Thread(target=_run, args=(c.request.strip(), c.page), daemon=True).start()
    return editor_status()


@app.get("/api/editor/status")
def editor_status():
    return {**job, "history": [{k: x[k] for k in ("at", "request", "summary")} for x in reversed(_history())]}


@app.post("/api/editor/undo")
def editor_undo(req: Request):
    _guard(req)
    with _lock:
        h = _history()
        if not h:
            raise HTTPException(400, "Nothing to undo.")
        last = h.pop()
        _write(last["before"])
        _save_history(h)
        server = any(r.endswith(".py") for r in last["before"])
        job.clear()
        job.update(state="deploying" if server else "done", summary=f"Undid: {last['request']}",
                   files=sorted(last["before"]), restart=server)
    if server:
        _redeploy()
    return editor_status()


# ----------------------------------------------------------------------------- static page
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-store"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8000")))
