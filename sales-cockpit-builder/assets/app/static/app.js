// Sales cockpit page: plain JavaScript (no build). Shell (top bar, hero, nav), one render function per page in PAGES,
// shared UI helpers (same components and CSS classes as the AE Cockpit design system), Genie bubble, app editor bubble.

// ---------------------------------------------------------------------------- DOM + API helpers
const h = (tag, attrs, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  const add = (c) => { if (c == null || c === false) return; if (Array.isArray(c)) c.forEach(add); else el.append(c instanceof Node ? c : String(c)); };
  kids.forEach(add);
  return el;
};
const svg = (tag, attrs, ...kids) => {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v); else el.setAttribute(k, v);
  }
  kids.flat().forEach((c) => c && el.append(c));
  return el;
};
const api = async (path, body) => {
  const r = await fetch(`/api${path}`, body === undefined ? {} : { method: "POST", body: JSON.stringify(body),
                          headers: { "Content-Type": "application/json", "X-Cockpit": "1" } });
  const t = await r.text();
  if (!r.ok) { let m = t; try { m = JSON.parse(t).detail || t; } catch { /* plain text */ } throw new Error(m); }
  return JSON.parse(t);
};

let META = null, L = {};
const t = (k, vars = {}) => Object.entries(vars).reduce((s, [a, b]) => s.replace(`{${a}}`, b), L[k] ?? k);

// ---------------------------------------------------------------------------- formatting (currency from the config)
const LOC = () => (META?.language === "fr" ? "fr-FR" : META?.language === "de" ? "de-DE" : "en-GB");
const isNum = (x) => x != null && x !== "" && !isNaN(x);
const money = (x) => (!isNum(x) ? "—" : new Intl.NumberFormat(LOC(), { style: "currency", currency: META.currency || "USD", maximumFractionDigits: 0 }).format(x));
const moneyK = (x) => (!isNum(x) ? "—" : new Intl.NumberFormat(LOC(), { style: "currency", currency: META.currency || "USD", notation: "compact", maximumFractionDigits: 1 }).format(x));
const num = (x) => (!isNum(x) ? "—" : new Intl.NumberFormat(LOC(), { maximumFractionDigits: 1 }).format(x));
const pct = (x, d = 0) => (!isNum(x) ? "—" : `${Number(x).toFixed(d)}%`);
const signed = (x) => (!isNum(x) ? "—" : `${x > 0 ? "+" : ""}${Math.round(x)}%`);
const day = (s) => (s ? new Date(s).toLocaleDateString(LOC(), { day: "2-digit", month: "short" }) : "—");
const dayY = (s) => (s ? new Date(s).toLocaleDateString(LOC(), { day: "2-digit", month: "short", year: "numeric" }) : "—");
const MONEY_COL = /amount|arr$|^arr|pipeline|commit|consumed_amount|won_last|usage_last|usage_prev|revenue/;
const autoFmt = (key, v) => {
  if (v == null || v === "") return "—";
  if (/_pct$/.test(key)) return key.includes("trend") ? signed(v) : pct(v);
  if (/date$|^week$|_at$/.test(key)) return dayY(v);
  if (typeof v === "boolean" || v === "true" || v === "false") return String(v) === "true" ? "✓" : "—";
  if (typeof v === "number") return MONEY_COL.test(key) && key !== "employees" ? moneyK(v) : num(v);
  return String(v);
};
const pretty = (k) => L[k] || (k.charAt(0).toUpperCase() + k.slice(1)).replace(/_/g, " ");
const autoCols = (rows, skip = ["account_id"]) => (rows[0] ? Object.keys(rows[0]).filter((k) => !skip.includes(k)
  && rows.some((r) => r[k] != null && r[k] !== "")) : []).map((k) => ({ key: k, label: pretty(k), num: rows.some((r) => typeof r[k] === "number") }));

// ---------------------------------------------------------------------------- shared UI (same as components/ui.jsx)
const Loading = (lines = 3) => h("div", { class: "loading" }, h("div", { class: "small" }, t("loading")),
  Array.from({ length: lines }, (_, i) => h("div", { class: "skel", style: { height: `${i ? 70 : 110}px` } })));
const Err = (m) => h("div", { class: "err" }, `${t("error")}: ${m}`);
const Section = ({ kicker, title, sub, right }) => h("div", { class: "sechead" },
  kicker && h("div", { class: "kicker" }, kicker), h("div", { class: "row" }, h("h2", {}, title), h("div", { class: "spacer" }), right),
  sub && h("p", {}, sub));
const Card = ({ kicker, title, cls = "", style }, ...kids) => h("div", { class: `card ${cls}`, style },
  kicker && h("div", { class: "kicker" }, kicker), title && h("h3", {}, title), kids);
const Stat = ({ label, value, sub, tone = "", onClick }, ...kids) => h("div", { class: `card stat ${tone} ${onClick ? "link" : ""}`, onClick },
  h("div", { class: "k-label" }, label), h("div", { class: "k-num" }, value), sub && h("div", { class: "k-sub" }, sub), kids);
const Pill = (tone, text) => h("span", { class: `pill ${tone || ""}` }, text);
const Seg = (options, value, onChange) => h("div", { class: "seg" },
  options.map((o) => h("button", { class: o === value ? "on" : "", onClick: () => onChange(o) }, o)));
const Select = (options, value, onChange) => h("select", { onChange: (e) => onChange(e.target.value) },
  options.map((o) => h("option", { selected: o === value || null }, o)));

const TIP = h("div", { class: "tip", style: { display: "none" } });
const tipShow = (e, text) => Object.assign(TIP.style, { display: "block", left: `${e.clientX + 12}px`, top: `${e.clientY + 12}px` }) && (TIP.textContent = text);
const tipHide = () => { TIP.style.display = "none"; };

function Table(rows, cols, { max = 460, onRow } = {}) {
  let sort = null;
  const wrap = h("div", { class: "tblwrap", style: { maxHeight: `${max}px` } });
  const draw = () => {
    const sorted = !sort ? rows : [...rows].sort((a, b) => ((a[sort.key] ?? "") > (b[sort.key] ?? "") ? sort.dir : (a[sort.key] ?? "") < (b[sort.key] ?? "") ? -sort.dir : 0));
    wrap.replaceChildren(h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : "",
        onClick: () => { sort = { key: c.key, dir: sort?.key === c.key ? -sort.dir : -1 }; draw(); } },
        c.label, sort?.key === c.key ? (sort.dir > 0 ? " ↑" : " ↓") : "")))),
      h("tbody", {}, sorted.map((r) => h("tr", { onClick: onRow && (() => onRow(r)), style: onRow ? { cursor: "pointer" } : null },
        cols.map((c) => h("td", { class: c.num ? "num" : "" }, c.fmt ? c.fmt(r[c.key], r) : autoFmt(c.key, r[c.key]))))))));
  };
  if (!rows.length) return h("div", { class: "small" }, t("empty"));
  draw();
  return wrap;
}

function Bars(rows, label, value, fmt = num, color = "var(--c2)") {
  const m = Math.max(1, ...rows.map((r) => r[value] || 0));
  return h("div", { style: { display: "grid", gap: "9px" } }, rows.map((r) => h("div", { class: "bar-row",
    onMousemove: (e) => tipShow(e, `${r[label]}: ${fmt(r[value])}`), onMouseleave: tipHide },
    h("span", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, r[label]),
    h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(100 * (r[value] || 0)) / m}%`, background: color } })),
    h("span", { class: "mono small" }, fmt(r[value])))));
}

const PALETTE = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)"];
function Columns(rows, x, series, { height = 220, fmt = num } = {}) {
  const totals = rows.map((r) => series.reduce((s, k) => s + (r[k.key] || 0), 0));
  const m = Math.max(1, ...totals), w = 100 / Math.max(rows.length, 1), H = height / 3;
  const bars = rows.flatMap((r, i) => {
    let y = H;
    return series.map((s) => {
      const hh = ((r[s.key] || 0) / m) * (H - 2); y -= hh;
      return svg("rect", { x: i * w + w * 0.15, y, width: w * 0.7, height: Math.max(hh - 0.3, 0), rx: 0.8, fill: s.color,
        onMousemove: (e) => tipShow(e, `${r[x]} · ${s.label}: ${fmt(r[s.key] || 0)}`), onMouseleave: tipHide });
    });
  });
  return h("div", {},
    series.length > 1 && h("div", { class: "row small", style: { marginBottom: "8px" } }, series.map((s) => h("span", { class: "row", style: { gap: "5px" } },
      h("i", { style: { width: "10px", height: "10px", borderRadius: "3px", background: s.color, display: "inline-block" } }), s.label))),
    svg("svg", { viewBox: `0 0 100 ${H}`, preserveAspectRatio: "none", class: "cols-chart", style: `width:100%;height:${height}px` }, bars),
    h("div", { class: "row small mono", style: { justifyContent: "space-between", gap: "4px" } }, h("span", {}, rows[0]?.[x]), h("span", {}, rows[rows.length - 1]?.[x])));
}

// actual vs target gauge: scale = 120% of target, black tick = target, grey tick = period elapsed
function Gauge(actual, target, elapsed) {
  const wd = (v) => `${Math.min(100, (100 * (v || 0)) / (1.2 * target))}%`;
  return h("div", { class: "gauge" }, h("div", { class: "gauge-a", style: { width: wd(actual) } }),
    h("div", { class: "gauge-tick", style: { left: `${100 / 1.2}%` }, title: t("target") }),
    isNum(elapsed) && h("div", { class: "gauge-tick el", style: { left: `${elapsed / 1.2}%` } }));
}

// tiny markdown: paragraphs, **bold**, `code`, - lists, ### titles (Genie answers)
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
const Md = (text) => {
  let html = "", list = false;
  for (const line of (text || "").split("\n")) {
    const li = line.match(/^\s*[-*] (.*)/);
    if (li) { html += (list ? "" : "<ul>") + `<li>${inline(li[1])}</li>`; list = true; continue; }
    if (list) { html += "</ul>"; list = false; }
    const hd = line.match(/^#{1,4} (.*)/);
    html += hd ? `<h3>${inline(hd[1])}</h3>` : line.trim() ? `<p>${inline(line)}</p>` : "";
  }
  return h("div", { class: "md", html: html + (list ? "</ul>" : "") });
};

function Drawer(content) {
  const close = () => { bg.remove(); box.remove(); document.removeEventListener("keydown", key); };
  const key = (e) => e.key === "Escape" && close();
  const bg = h("div", { class: "drawer-bg", onClick: close });
  const box = h("aside", { class: "drawer" }, h("button", { class: "close", onClick: close, "aria-label": "Close" }, "×"), content);
  document.addEventListener("keydown", key);
  document.body.append(bg, box);
  return box;
}

const go = (id) => { window.location.hash = `#/${id}`; };
const uniq = (rows, k) => [...new Set(rows.map((r) => r[k]).filter((v) => v != null && v !== ""))].sort();

// ---------------------------------------------------------------------------- account drawer (from any page)
async function openAccount(id, name) {
  const box = Drawer([h("div", { class: "kicker" }, t("accounts")), h("h2", {}, name || ""), Loading(2)]);
  try {
    const d = await api(`/account/${encodeURIComponent(id)}`);
    const a = d.account || {};
    const facts = Object.entries(a).filter(([k, v]) => !["account_id", "account_name"].includes(k) && v != null && v !== "");
    const parts = [h("div", { class: "kicker" }, a.status || t("accounts")), h("h2", {}, a.account_name || name),
      h("div", { class: "grid g2" }, facts.slice(0, 12).map(([k, v]) => h("div", {}, h("div", { class: "small" }, pretty(k)), h("b", {}, autoFmt(k, v)))))];
    if (d.usage?.length) parts.push(Card({ title: t("usage") }, Columns(d.usage.map((r) => ({ ...r, week: day(r.week) })), "week",
      [{ key: "amount", label: t("usage"), color: "var(--c2)" }], { height: 120, fmt: moneyK })));
    for (const ent of ["opportunities", "contracts", "activities", "contacts", "signals"]) {
      if (d[ent]?.length) parts.push(h("div", { class: "kicker", style: { marginTop: "8px" } }, t(ent)), Table(d[ent], autoCols(d[ent]), { max: 260 }));
    }
    const close = box.querySelector(".close");
    box.replaceChildren(close, h("div", { class: "grid", style: { gap: "14px" } }, parts));  // one item: tables keep their height
  } catch (e) { box.append(Err(e.message)); }
}

// ---------------------------------------------------------------------------- pages
const PAGES = {
  actions(d, redraw, st) {
    st.reason ??= t("all_reasons"); st.seg ??= t("all"); st.p1 ??= false;
    const statuses = uniq(d.actions, "account_status");
    const view = d.actions.filter((a) => (st.reason === t("all_reasons") || a.reason === st.reason)
      && (st.seg === t("all") || a.account_status === st.seg) && (!st.p1 || a.priority === 1));
    const k = d.kpi;
    const stats = [Stat({ tone: "lava", label: t("kpi_p1"), value: num(k.p1), onClick: () => { st.p1 = true; redraw(); } })];
    if (isNum(k.open_pipeline)) stats.push(Stat({ tone: "blue", label: t("kpi_pipeline"), value: moneyK(k.open_pipeline), onClick: () => go("pipeline") }));
    if (isNum(k.usage_90d)) stats.push(Stat({ tone: "ok", label: t("kpi_usage"), value: moneyK(k.usage_90d), onClick: () => go("usage") }));
    if (isNum(k.renewals_120d)) stats.push(Stat({ tone: "warn", label: t("kpi_renewals"), value: num(k.renewals_120d), onClick: () => go("contracts") }));
    stats.push(Stat({ label: t("kpi_accounts"), value: num(k.accounts), sub: `${num(k.customers)} ${t("kpi_customers").toLowerCase()}`, onClick: () => go("accounts") }));
    return [
      h("div", { class: `grid g${Math.min(stats.length, 4)}` }, stats.slice(0, 4)),
      Section({ kicker: t("today"), title: t("actions_title"), sub: t("actions_sub") }),
      h("div", { class: "row", style: { marginBottom: "14px" } },
        Select([t("all_reasons"), ...uniq(d.actions, "reason")], st.reason, (v) => { st.reason = v; redraw(); }),
        statuses.length > 1 && Seg([t("all"), ...statuses], st.seg, (v) => { st.seg = v; redraw(); }),
        st.p1 && h("button", { class: "btn", onClick: () => { st.p1 = false; redraw(); } }, `${t("p1_only")} ✕`),
        h("div", { class: "spacer" }), h("span", { class: "small" }, t("n_actions", { n: view.length }))),
      view.length ? view.slice(0, 60).map((a) => h("div", { class: "item" }, Pill(`p${a.priority}`, `P${a.priority}`),
        h("div", { style: { minWidth: 0 } }, h("div", {}, h("b", {}, a.account_name), ` · ${a.reason}`),
          h("div", { class: "small" }, `${a.detail || ""} → `, h("b", { style: { color: "var(--ink)" } }, a.action))),
        h("button", { class: "btn", onClick: () => openAccount(a.account_id, a.account_name) }, "→")))
        : h("div", { class: "small" }, t("empty")),
    ];
  },

  overview(d) {
    const units = Object.fromEntries((META.kpis || []).map((k) => [k.id, k.unit || "money"]));
    const f = (id, v) => (units[id] === "pct" ? pct(v, 1) : units[id] === "count" ? num(v) : moneyK(v));
    const tot = d.kpis.filter((k) => k.dimension_value === "All");
    const tone = (k) => (!isNum(k.attainment_pct) ? "blue" : k.attainment_pct >= (k.period_elapsed_pct ?? 100) ? "ok" : "lava");
    const out = [Section({ kicker: t("targets_kicker"), title: t("targets_title"), sub: t("targets_sub") }),
      h("div", { class: `grid g${Math.min(Math.max(tot.length, 1), 3)}` }, tot.map((k) => Stat({ tone: tone(k), label: `${k.kpi_label} · ${k.period}`,
        value: f(k.kpi_id, k.actual),
        sub: isNum(k.target_value) ? `${t("of_target", { p: Math.round(k.attainment_pct) })} · ${t("target")} ${f(k.kpi_id, k.target_value)}` : t("no_target") },
        isNum(k.target_value) && Gauge(k.actual, k.target_value, k.period_elapsed_pct),
        isNum(k.period_elapsed_pct) && h("div", { class: "small" }, t("elapsed", { p: Math.round(k.period_elapsed_pct) })))))];
    const by = {};
    d.kpis.filter((k) => k.dimension_value !== "All").forEach((k) => (by[k.kpi_id] ??= []).push(k));
    const cards = Object.values(by).map((rows) => Card({ kicker: t("breakdown"), title: rows[0].kpi_label },
      Bars([...rows].sort((a, b) => (b.actual || 0) - (a.actual || 0)), "dimension_value", "actual", (v) => f(rows[0].kpi_id, v), "var(--c1)")));
    if (cards.length) out.push(h("div", { class: "grid g2", style: { marginTop: "16px" } }, cards));
    if (!d.kpis.length) out.push(h("div", { class: "small" }, t("empty")));
    return out;
  },

  accounts(d, redraw, st) {
    st.q ??= ""; st.seg ??= t("all");
    const statuses = uniq(d.accounts, "status");
    const rows = d.accounts.filter((a) => (!st.q || (a.account_name || "").toLowerCase().includes(st.q.toLowerCase()))
      && (st.seg === t("all") || a.status === st.seg));
    const input = h("input", { type: "text", placeholder: t("search"), value: st.q });
    input.addEventListener("input", (e) => { st.q = e.target.value; st.focus = true; redraw(); });
    if (st.focus) setTimeout(() => { input.focus(); input.setSelectionRange(st.q.length, st.q.length); });
    return [Section({ title: t("accounts_title"), sub: t("accounts_sub"),
      right: h("div", { class: "row" }, input, statuses.length > 1 && Seg([t("all"), ...statuses], st.seg, (v) => { st.seg = v; st.focus = false; redraw(); })) }),
      Table(rows, autoCols(d.accounts), { max: 640, onRow: (r) => openAccount(r.account_id, r.account_name) })];
  },

  pipeline(d) {
    const deals = d.deals, today = new Date().toISOString().slice(0, 10);
    const in30 = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
    const sum = (rows) => rows.reduce((s, r) => s + (r.amount || 0), 0);
    const byStage = Object.entries(deals.reduce((m, r) => ((m[r.stage || "—"] = (m[r.stage || "—"] || 0) + (r.amount || 0)), m), {}))
      .map(([stage, amount]) => ({ stage, amount })).sort((a, b) => b.amount - a.amount);
    const months = {};
    deals.forEach((r) => { const k = (r.close_date || "").slice(0, 7); months[k] = (months[k] || 0) + (r.amount || 0); });
    const byMonth = Object.keys(months).sort().map((k) => ({ month: k, amount: months[k] }));
    const overdue = deals.filter((r) => r.close_date < today), soon = deals.filter((r) => r.close_date >= today && r.close_date <= in30);
    return [h("div", { class: "grid g3" },
      Stat({ tone: "lava", label: t("kpi_pipeline"), value: moneyK(sum(deals)), sub: `${deals.length} ${t("open_deals").toLowerCase()}` }),
      Stat({ tone: "warn", label: t("closing_30"), value: moneyK(sum(soon)), sub: `${soon.length} ${t("open_deals").toLowerCase()}` }),
      Stat({ tone: overdue.length ? "lava" : "ok", label: t("overdue"), value: num(overdue.length), sub: moneyK(sum(overdue)) })),
    Section({ title: t("pipeline_title"), sub: t("pipeline_sub") }),
    h("div", { class: "grid g2" }, Card({ title: t("by_stage") }, Bars(byStage, "stage", "amount", moneyK, "var(--lava)")),
      Card({ title: t("by_month") }, Columns(byMonth, "month", [{ key: "amount", label: t("kpi_pipeline"), color: "var(--c2)" }], { fmt: moneyK }))),
    h("div", { style: { marginTop: "16px" } }, Table(deals, autoCols(deals, ["account_id", "is_closed", "is_won"]),
      { onRow: (r) => openAccount(r.account_id, r.account_name) }))];
  },

  usage(d) {
    const products = uniq(d.weekly, "product");
    const weeks = {};
    d.weekly.forEach((r) => { (weeks[r.week] ??= { week: day(r.week) })[r.product] = r.amount; });
    const rows = Object.keys(weeks).sort().map((k) => weeks[k]);
    const series = products.map((p, i) => ({ key: p, label: p, color: PALETTE[i % PALETTE.length] }));
    return [Section({ title: t("usage_title"), sub: t("usage_sub") }),
      Card({}, Columns(rows, "week", series, { height: 240, fmt: moneyK })),
      Section({ title: t("movers") }),
      Table(d.movers, autoCols(d.movers), { onRow: (r) => openAccount(r.account_id, r.account_name) })];
  },

  contracts(d) {
    const c = d.contracts, in180 = new Date(Date.now() + 180 * 864e5).toISOString().slice(0, 10);
    const ending = c.filter((r) => r.end_date <= in180);
    const burn = c.filter((r) => isNum(r.consumed_pct));
    return [Section({ title: t("contracts_title"), sub: t("contracts_sub") }),
      burn.length > 0 && h("div", { class: "grid g3" }, burn.slice(0, 9).map((r) => Stat({
        tone: r.consumed_pct + 15 < r.elapsed_pct ? "lava" : r.consumed_pct > r.elapsed_pct + 15 ? "warn" : "ok",
        label: r.account_name, value: pct(r.consumed_pct), sub: `${t("consumed")} · ${t("elapsed", { p: Math.round(r.elapsed_pct) })} · ${dayY(r.end_date)}`,
        onClick: () => openAccount(r.account_id, r.account_name) }, Gauge(r.consumed_pct, 100, r.elapsed_pct)))),
      Section({ title: t("ending") }), Table(ending, autoCols(ending), { onRow: (r) => openAccount(r.account_id, r.account_name) }),
      Section({ title: t("contracts") }), Table(c, autoCols(c), { onRow: (r) => openAccount(r.account_id, r.account_name) })];
  },

  signals(d, redraw, st) {
    st.src ??= t("all_sources");
    const rows = d.signals.filter((s) => st.src === t("all_sources") || s.source === st.src);
    return [Section({ title: t("signals_title"), sub: t("signals_sub"),
      right: Select([t("all_sources"), ...uniq(d.signals, "source")], st.src, (v) => { st.src = v; redraw(); }) }),
      Card({}, rows.length ? rows.slice(0, 80).map((s) => h("div", { class: "row frow", style: { flexWrap: "nowrap" } },
        h("span", { class: "mono small", style: { width: "56px", flex: "none" } }, day(s.signal_date)), Pill(s.source ? "blue" : "", s.source || s.signal_type),
        h("div", { style: { minWidth: 0, flex: 1 } }, h("b", { class: "ad-link", style: { cursor: "pointer" }, onClick: () => openAccount(s.account_id, s.account_name) }, s.account_name),
          ` · ${s.signal_type}`, h("div", { class: "small" }, s.detail || "")),
        isNum(s.score) && Pill("warn", num(s.score)))) : h("div", { class: "small" }, t("empty")))];
  },
};

// ---------------------------------------------------------------------------- Genie bubble (bottom right)
const genie = { open: false, hist: [], busy: false };
function GenieBubble() {
  const box = h("div");
  const draw = () => {
    const fab = h("button", { class: "genie-fab", onClick: () => { genie.open = !genie.open; draw(); }, title: t("ask_genie") },
      genie.open ? "×" : "💬", h("span", {}, genie.open ? "" : t("genie")));
    if (!genie.open) return box.replaceChildren(fab);
    const ask = async (q) => {
      if (!q) return;
      genie.busy = true; draw();
      const a = await api("/genie", { question: q, conv_id: genie.hist[genie.hist.length - 1]?.conv_id || null }).catch((e) => ({ question: q, error: e.message }));
      genie.hist.push(a); genie.busy = false; draw();
    };
    const input = h("input", { type: "text", style: { flex: 1 }, placeholder: t("ask_placeholder") });
    const hist = h("div", { class: "genie-hist" },
      !genie.hist.length && h("div", { class: "row", style: { gap: "6px" } }, (META.suggestions || []).map((s) =>
        h("button", { class: "btn", style: { whiteSpace: "normal", textAlign: "left" }, onClick: () => ask(s), disabled: genie.busy }, s))),
      genie.hist.map((a, i) => h("div", { class: "card", style: { boxShadow: "none", padding: "14px" } },
        h("div", { class: "small" }, `🙋 ${a.question}`), a.description && h("b", {}, a.description), a.text && Md(a.text),
        a.rows?.length > 0 && Table(a.rows, autoCols(a.rows, []), { max: 260 }),
        a.sql && h("details", {}, h("summary", { class: "small" }, t("genie_sql")), h("pre", { class: "mono small", style: { whiteSpace: "pre-wrap" } }, a.sql)),
        a.error && h("div", { class: "err" }, a.error),
        a.suggested?.length > 0 && i === genie.hist.length - 1 && h("div", { class: "row", style: { gap: "6px" } },
          a.suggested.map((s) => h("button", { class: "chip", style: { border: 0, cursor: "pointer" }, onClick: () => ask(s) }, s))))),
      genie.busy && h("div", { class: "skel", style: { height: "60px" } }));
    const form = h("form", { class: "row", onSubmit: (e) => { e.preventDefault(); ask(input.value.trim()); } }, input,
      h("button", { class: "btn primary", disabled: genie.busy }, genie.busy ? "…" : t("ask")));
    box.replaceChildren(fab, h("div", { class: "genie-pop card" },
      h("div", { class: "row" }, h("h3", {}, t("ask_genie")), h("div", { class: "spacer" }), h("span", { class: "small" }, t("genie_sub"))), hist, form));
    hist.scrollTop = hist.scrollHeight;
    if (!genie.busy) input.focus();
  };
  draw();
  return box;
}

// ---------------------------------------------------------------------------- app editor bubble (bottom left)
const ed = { open: false, st: null, err: null, text: "", timer: null };
function EditorBubble() {
  const box = h("div");
  const busy = () => ["running", "deploying"].includes(ed.st?.state);
  const reloadWhenUp = async (restart) => {
    if (!restart) return window.location.reload();
    const before = META.loaded_at;
    await new Promise((r) => setTimeout(r, 20000));
    for (let i = 0; i < 90; i++) {  // the app restarts on a new deployment: wait for the new server
      try { const m = await api("/meta"); if (m.loaded_at !== before) return window.location.reload(); } catch { /* restarting */ }
      await new Promise((r) => setTimeout(r, 4000));
    }
  };
  const poll = () => {
    clearInterval(ed.timer);
    ed.timer = setInterval(async () => {
      const s = await api("/editor/status").catch(() => null);
      if (!s) return;
      ed.st = s; draw();
      if (s.state === "done" || s.state === "failed") clearInterval(ed.timer);
      if (s.files?.length && (s.state === "done" || s.state === "deploying")) { clearInterval(ed.timer); reloadWhenUp(s.restart); }
    }, 2000);
  };
  const act = async (path, body) => {
    ed.err = null;
    try { ed.st = await api(`/editor/${path}`, body ?? {}); if (busy() || ed.st.files?.length) poll(); } catch (e) { ed.err = e.message; }
    draw();
  };
  const draw = () => {
    const fab = h("button", { class: "editor-fab", onClick: async () => { ed.open = !ed.open; if (ed.open) ed.st = await api("/editor/status").catch(() => null); draw(); },
      title: t("edit") }, "✏️ ", h("span", {}, t("edit")));
    if (!ed.open) return box.replaceChildren(fab);
    const st = ed.st, secs = st?.started ? Math.round(Date.now() / 1000 - st.started) : 0;
    const area = h("textarea", { rows: 3, placeholder: t("edit_placeholder"), disabled: busy() || !META.can_edit || null });
    area.value = ed.text;
    area.addEventListener("input", (e) => { ed.text = e.target.value; });
    box.replaceChildren(fab, h("div", { class: "card editor-pop" },
      h("div", { class: "row" }, h("b", {}, `✏️ ${t("edit")}`), h("div", { class: "spacer" }),
        h("button", { class: "pp-x", onClick: () => { ed.open = false; draw(); }, "aria-label": "Close" }, "×")),
      h("div", { class: "small" }, META.can_edit ? t("edit_help") : t("edit_owner_only")),
      area,
      h("div", { class: "row" },
        !busy() && h("button", { class: "btn primary", disabled: !META.can_edit || null,
          onClick: () => ed.text.trim() && act("run", { request: ed.text, page: location.hash.replace(/^#\/?/, "") }) }, t("make_change")),
        h("div", { class: "spacer" }),
        !busy() && st?.history?.length > 0 && META.can_edit && h("button", { class: "btn", onClick: () => act("undo") }, t("undo"))),
      ed.err && h("div", { class: "err" }, ed.err),
      st && st.state !== "idle" && h("div", { class: "editor-log" },
        st.request && h("div", { class: "small" }, h("b", { style: { color: "var(--ink)" } }, st.request)),
        st.state === "running" && h("div", { class: "small" }, t("working", { s: secs })),
        st.state === "deploying" && h("div", { class: "small" }, t("deploying")),
        st.state === "done" && h("div", { class: "note", style: { background: "var(--ok-tint)", borderColor: "var(--ok)" } },
          st.summary || t("done"), st.files?.length ? t("reloading") : ` ${t("nothing_changed")}`),
        st.state === "failed" && h("div", { class: "err" }, st.error, st.summary ? ` ${st.summary}` : "")),
      st?.history?.length > 0 && h("details", { class: "small" }, h("summary", {}, t("recent_changes", { n: st.history.length })),
        st.history.slice(0, 8).map((x) => h("div", { class: "frow" }, h("b", {}, x.at.slice(5)), ` · ${x.request}`)))));
  };
  draw();
  return box;
}

// ---------------------------------------------------------------------------- shell
const route = () => window.location.hash.replace(/^#\/?/, "") || META.pages[0];
const cache = {}, state = {};
const main = h("div", { class: "wrap" });

async function showPage() {
  const id = META.pages.includes(route()) ? route() : META.pages[0];
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("on", a.dataset.id === id));
  state[id] ??= {};
  const redraw = () => main.replaceChildren(...[PAGES[id](cache[id], redraw, state[id])].flat(4).filter(Boolean));
  if (cache[id]) return redraw();
  main.replaceChildren(Loading(4));
  try { cache[id] = await api(`/page/${id}`); if (route() === id || !META.pages.includes(route())) redraw(); }
  catch (e) { main.replaceChildren(Err(e.message)); }
}

async function start() {
  const root = document.getElementById("root");
  try { META = await api("/meta"); } catch (e) { root.replaceChildren(h("main", {}, h("div", { class: "wrap" }, Err(e.message)))); return; }
  L = META.labels;
  // brand colours chosen with the seller (cockpit_config.json "theme": CSS variable -> value); none = standard colours
  Object.entries(META.theme || {}).forEach(([k, v]) => document.documentElement.style.setProperty(`--${k}`, v));
  document.documentElement.lang = META.language || "en";
  document.title = `${t("title")} ${t("title_em")}`;
  const when = h("span");
  const setWhen = () => { when.textContent = t("loaded", { d: dayY(META.loaded_at), t: META.loaded_at.slice(11, 16) }); };
  setWhen();
  const btn = h("button", { class: "btn ghost-dark", onClick: async () => {
    btn.disabled = true; btn.textContent = t("refreshing");
    META = await api("/refresh", {}); L = META.labels; Object.keys(cache).forEach((k) => delete cache[k]);
    setWhen(); btn.disabled = false; btn.textContent = t("refresh"); showPage();
  } }, t("refresh"));
  const label = [META.role && META.role[0].toUpperCase() + META.role.slice(1), META.book].filter(Boolean).join(" · ");
  root.replaceChildren(
    h("div", { class: "topbar" }, h("div", { class: "wrap" },
      h("div", { class: "logo" }, `🧭 ${t("title")} ${t("title_em")} `, META.company && h("span", {}, `· ${META.company}`)),
      h("nav", { class: "nav" }, META.pages.map((p) => h("a", { href: `#/${p}`, "data-id": p }, t(p)))),
      h("div", { class: "refresh" }, when, btn))),
    h("header", { class: "hero" }, h("div", { class: "wrap" },
      h("div", { class: "eyebrow" }, [META.seller, label].filter(Boolean).join(" · ")),
      h("h1", {}, `${t("title")} `, h("em", {}, t("title_em"))),
      h("div", { class: "sub", html: t("powered") }))),
    h("main", {}, main),
    META.editor && EditorBubble(),
    META.genie && GenieBubble(),
    TIP);
  window.addEventListener("hashchange", showPage);
  showPage();
}
start();
