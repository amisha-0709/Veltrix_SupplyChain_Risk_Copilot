/* Veltrix Risk Co-Pilot UI: plain JS, no build step. All text is escaped before it reaches the DOM. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/* Per-tab session token: signals you try are visible only to you (never in other people's inbox). */
const SESSION = (() => {
  let s = null; try { s = sessionStorage.getItem("copilot-session"); } catch (e) {}
  if (!s) { s = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9-]/g, "");
    try { sessionStorage.setItem("copilot-session", s); } catch (e) {} }
  return s;
})();
const api = async (p, opt = {}) => {
  const r = await fetch(p, { ...opt, headers: { ...(opt.headers || {}), "X-Copilot-Session": SESSION } });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`); return r.json();
};
const cache = {};
const get = (p) => (cache[p] ??= api(p));
const inr = (v) => { if (v == null) return "—"; const a = Math.abs(v); if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} cr`; if (a >= 1e5) return `₹${(v / 1e5).toFixed(1)} lakh`; return `₹${Math.round(v).toLocaleString("en-IN")}`; };
const date = (s) => s ? new Date(s).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const pcls = (p) => p >= 20 ? "p-crit" : p >= 12 ? "p-high" : p >= 6 ? "p-med" : "p-low";
const pill = (p, L, I) => `<span class="pill ${pcls(p)}" title="Priority = likelihood × impact">P${p}${L ? ` <small style="font-weight:400">${L}×${I}</small>` : ""}</span>`;
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), 2600); };
const node = (n) => { const [t, name] = n.split(":"); return `<span class="tag" title="${esc(t)}">${esc(name)}</span>`; };

/* page heading: a mono kicker over a serif headline (one italic phrase in the pigment; static text only) */
const hed = (k, h) => `<p class="kicker">${esc(k)}</p><h1>${h}</h1>`;
/* role ("View as"): remembered in this browser; no sign-in */
const ROLE_NAMES = { category: "Category manager", hosc: "Head of Supply Chain", coo: "COO", sales: "Sales / key-account manager" };
const role = () => { let r = ""; try { r = localStorage.getItem("persona") || ""; } catch (e) {} return ROLE_NAMES[r] ? r : ""; };
const setRole = (r) => { try { localStorage.setItem("persona", r); } catch (e) {} };
const roleNote = () => role() ? `<p class="kicker" style="margin-top:-6px">Viewing as ${esc(ROLE_NAMES[role()])}</p>` : "";

/* ---------------- views ---------------- */
async function viewInbox(tab = "inbox") {
  const [meta, alerts, review] = await Promise.all([get("/api/meta"), api("/api/alerts"), api("/api/needs-review").catch(() => [])]);
  const inbox = alerts.filter((a) => a.inbox), watch = alerts.filter((a) => !a.inbox);
  const bt = meta.backtest;
  const reviewRows = review.map((r) => `<tr><td>${date(r.published)}</td><td>${esc(r.source)}</td><td>${esc(r.text)}${r.simulated ? ' <span class="tag">simulated</span>' : ""}</td>
      <td class="muted">${esc(r.reason || "")}</td></tr>`).join("");
  const r0 = role(), myCat = r0 === "category" && pget("persona-cat", "") !== "__all" ? (pget("persona-cat", "") || "") : "";
  const isMine = (a) => !!myCat && a.owner.endsWith(myCat);
  const list0 = tab === "inbox" ? inbox : watch;
  const list = r0 === "coo" ? list0.slice().sort((x, y) => (y.revenue_at_risk || 0) - (x.revenue_at_risk || 0))
    : myCat ? list0.slice().sort((x, y) => isMine(y) - isMine(x)) : list0;
  const nMine = myCat ? inbox.filter(isMine).length : 0;
  const rows = list.map((a) => `
    <tr class="click${isMine(a) ? " mine" : ""}" data-id="${esc(a.alert_id)}">
      <td>${pill(a.priority, a.likelihood, a.impact)}</td>
      <td><b>${esc(a.title)}</b>${a.simulated ? ' <span class="tag">simulated</span>' : ""}<div class="muted">${esc(a.kind)} · ${a.links.slice(0, 4).map(node).join("")}</div></td>
      <td>${date(a.first_seen)}</td>
      <td class="num">${esc(a.revenue_at_risk_fmt)}${a.mode === "precautionary" ? `<div class="muted">stress ${esc(a.stress_revenue_at_risk_fmt)}</div>` : ""}</td>
      <td>${esc(a.owner.replace("Category manager: ", ""))}</td>
      <td class="num">${a.n_sources}<span class="muted"> / ${a.n_signals}</span></td>
      <td class="num">${Math.round(a.confidence * 100)}%</td>
      <td>${esc(a.response.split(";")[0])}</td>
    </tr>`).join("");
  $("#app").innerHTML = `
    ${hed("Alerts · shared", "Every signal, <em>one alert</em> per event.")}${roleNote()}
    ${myCat ? `<p class="sub"><b>${nMine}</b> of ${inbox.length} inbox alerts are yours (${esc(myCat)}): listed first and marked.</p>` : ""}
    ${r0 === "coo" ? `<p class="sub">Sorted by revenue at risk, largest first.</p>` : ""}
    <p class="sub">Every external signal that touches Veltrix's suppliers, ports, lanes or commodities becomes one alert per event, quantified with
    the playbook method. Priority ≥ 6 goes to the inbox; the rest is the watch log. Stock position: ${esc(meta.snapshot_date)}.</p>
    <div class="tiles">
      <div class="tile"><b>${inbox.length}</b><span>alerts needing an owner (priority ≥ 6)</span></div>
      <div class="tile"><b>${(bt.signals.test.recall * 100).toFixed(1)}%</b><span>recall on the test period (target ≥ 80%)</span></div>
      <div class="tile"><b>${Math.round(bt.alerts.test.precision * 100)}%</b><span>alert precision on test (target ≥ 60%)</span></div>
      <div class="tile"><b>${bt.lead.test.median_lead_days.toFixed(1)} d</b><span>median warning before impact (team today: ${bt.lead_all.median_team_lead_days > 0 ? "" : "+"}${-bt.lead_all.median_team_lead_days} d after)</span></div>
    </div>
    <div class="tabs"><button data-t="inbox" class="${tab === "inbox" ? "on" : ""}">Inbox (${inbox.length})</button>
      <button data-t="watch" class="${tab === "watch" ? "on" : ""}">Watch log (${watch.length})</button>
      <button data-t="review" class="${tab === "review" ? "on" : ""}">Needs review (${review.length})</button></div>
    ${tab === "review" ? `<div class="card"><p class="muted" style="margin-top:0">Strong disruption wording, but nothing in the signal names a supplier, port, lane or
      commodity of ours. A person decides; the co-pilot never guesses a link.</p><table><thead><tr><th>Date</th><th>Source</th><th>Signal</th><th>Why it's here</th></tr></thead>
      <tbody>${reviewRows || '<tr><td colspan="4" class="muted">Nothing waiting for review.</td></tr>'}</tbody></table></div>` :
    `<div class="card"><table><thead><tr><th>Priority</th><th>Alert</th><th>First seen</th><th class="num">Revenue at risk</th>
      <th>Owner</th><th class="num">Sources / signals</th><th class="num">Confidence</th><th>Response</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="8" class="muted">Nothing here.</td></tr>'}</tbody></table></div>`}
    <p class="muted">Alerts are replayed from two years of signals (Oct 2024 – Sep 2026) and quantified on today's stock. Open an alert for its one-page briefing.</p>`;
  document.querySelectorAll("tr[data-id]").forEach((r) => (r.onclick = () => (location.hash = `#/alert/${r.dataset.id}`)));
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => viewInbox(b.dataset.t)));
}

let BRIEF_CSS = null;
async function briefFrame(a) {
  BRIEF_CSS ??= await (await fetch("/api/brief.css")).text();
  const ed = ":root{--ink:#141414;--ink2:#444343;--muted:#7A7A7A;--line:#C7C7C7;--surface:#E3E2DE;--page:#E3E2DE;--crit:#1351AA;--serious:#1351AA;--warn:#7A7A7A;--accent:#1351AA}" +
    "*{border-radius:0!important;box-shadow:none!important}body{font-family:'General Sans','Aileron',Arial,sans-serif;font-size:13px}" +
    "h1{font-weight:700;letter-spacing:-.03em;font-size:30px;line-height:1}.top{border-bottom-width:1px}h2{font-size:11px;letter-spacing:.2em;color:#7A7A7A}" +
    ".badge{background:#1351AA!important;color:#E3E2DE!important;font-size:11px;letter-spacing:.14em;text-transform:uppercase}" +
    ".ask{background:#D6D5D0;border-left:4px solid #1351AA;font-weight:600}.kv div{border-color:#C7C7C7}.kv b{font-size:20px;letter-spacing:-.02em}";
  return `<!doctype html><html><head><meta charset=utf-8><link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap"><style>${BRIEF_CSS}${ed}.sheet{margin:0;max-width:none;border:0}body{background:var(--surface)}</style></head><body>${a.brief_html}</body></html>`;
}

async function viewAlert(id, tab = "options") {
  const a = await api(`/api/alerts/${encodeURIComponent(id)}`);
  const dec = await api(`/api/decisions?alert_id=${encodeURIComponent(id)}`).catch(() => []);
  const opts = a.options || [];
  const good = goodOpts(a), rec = good.slice(0, 3), rest = opts.filter((o) => !rec.includes(o) && o.part_id);
  const noAct = opts.find((o) => !o.part_id);
  const optRow = (o, i, top) => `<tr class="${top && i === 0 ? "optrec" : ""}"><td class="num">${i + 1}</td>
    <td title="${esc(o.note || "")}">${top && i === 0 ? '<span class="badge">Recommended</span><br>' : ""}${niceOpt(o)}${o.note ? ' <span class="muted" aria-hidden="true">ⓘ</span>' : ""}</td>
    <td class="num">${o.time_to_effect_days ?? "—"} d</td><td>${o.on_time === false ? "late" : "in time"}</td>
    <td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td><td class="num">${o.roi == null ? "—" : o.roi.toFixed(1) + "×"}</td>
    <td>${esc(o.approver)}</td></tr>`;
  const optHead = `<thead><tr><th class="num">#</th><th>Option</th><th class="num">Effect</th><th>Timing</th><th class="num">Cost</th>
      <th class="num">Net value</th><th class="num">ROI</th><th>Approver</th></tr></thead>`;
  const parts = (a.parts || []).map((p) => `<tr><td>${esc(p.part_id)}</td><td>${esc(p.description)}</td><td>${p.single_source ? "single" : "dual"}</td>
    <td class="num">${p.days_of_cover}</td><td class="num">${p.effective_delay_days}</td><td class="num">${p.shortage_days}</td>
    <td><div class="cov" title="cover vs delay"><i style="width:${Math.min(100, (p.days_of_cover / 70) * 100)}%"></i><b style="left:${Math.min(100, (p.effective_delay_days / 70) * 100)}%"></b></div></td></tr>`).join("");
  const skus = (a.skus || []).filter((s) => s.units_short > 0).map((s) => `<tr><td>${esc(s.sku_id)}</td><td>${esc(s.customer)}</td><td>${esc(s.binding_part)}</td>
    <td class="num">${s.shortage_days}</td><td class="num">${(s.units_short || 0).toLocaleString("en-IN")}</td><td class="num">${inr(s.revenue_at_risk_inr)}</td>
    <td class="num">${inr(s.margin_at_risk_inr)}</td><td class="num">${inr(s.penalty_inr)}</td></tr>`).join("");
  const r0 = role();
  const canDecide = r0 === "sales" ? [] : r0 === "category" ? ["proposed", "watching"] : ["proposed", "approved", "escalated", "rejected", "watching", "dismissed"];
  const myBy = r0 ? ROLE_NAMES[r0] : a.owner;
  const otif = {}; (a.otif || []).forEach((o) => ((otif[o.customer] ??= []).push(o)));
  const otifRows = Object.entries(otif).map(([c, ws]) => `<tr><td>${esc(c)}</td>${ws.slice(0, 10).map((w) =>
    `<td class="num" style="${w.below_target ? "color:var(--crit);font-weight:600" : ""}" title="week of ${esc(w.week_start)}">${Math.round(w.otif * 100)}%</td>`).join("")}</tr>`).join("");
  const srcs = (a.brief.sources || []).map((s) => `<tr><td>${esc(s.date)}</td><td>${esc(s.source)}</td><td>${esc(s.text)}</td><td class="muted">${esc(s.id)}</td></tr>`).join("");
  const decRows = dec.map((d) => `<tr><td>${esc(d.at)}</td><td>${esc(d.by)}</td><td><b>${esc(d.decision)}</b></td><td>${esc(d.option)}</td><td>${esc(d.note)}</td></tr>`).join("");
  const T = {
    options: `${rec.length ? `<table>${optHead}<tbody>${rec.map((o, i) => optRow(o, i, true)).join("")}</tbody></table>`
        : `<div class="result" style="border-color:var(--good)"><b>No action recommended.</b><p>${esc(noAct ? noAct.option : "Stock lasts longer than the expected delay.")}</p></div>`}
      ${rest.length ? `<details><summary>${rest.length} other option${rest.length === 1 ? "" : "s"} ranked lower (cost more than they save, or land too late)</summary>
        <table>${optHead}<tbody>${rest.map((o, i) => optRow(o, rec.length + i, false)).join("")}</tbody></table></details>` : ""}
      ${(a.brief?.no_action || []).length ? `<h3 style="margin-top:16px">Short parts with no action, and why</h3><ul>${a.brief.no_action.map((x) => `<li><b>${esc(x.part)}</b> (short ${x.shortage_days.toFixed(1)} d): ${esc(nameIds(x.why))}</li>`).join("")}</ul>` : ""}
      <p class="muted">Net value = margin avoided × P(works in time) − cost − penalties anyway (playbook §5). Options are shown for approval, never as approved.</p>`,
    working: `<ol class="steps">${(a.working || []).map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol>
      <h3 style="margin-top:14px">Parts</h3><table><thead><tr><th>Part</th><th>Description</th><th>Sourcing</th><th class="num">Cover (d)</th><th class="num">Delay (d)</th>
      <th class="num">Short (d)</th><th>Cover vs delay</th></tr></thead><tbody>${parts}</tbody></table>
      ${skus ? `<h3 style="margin-top:14px">Products that stop</h3><table><thead><tr><th>SKU</th><th>Customer</th><th>Binding part</th><th class="num">Short (d)</th>
      <th class="num">Units</th><th class="num">Revenue at risk</th><th class="num">Margin</th><th class="num">Penalties</th></tr></thead><tbody>${skus}</tbody></table>` : ""}
      ${otifRows ? `<h3 style="margin-top:14px">Weekly OTIF by customer</h3><table><tbody>${otifRows}</tbody></table>` : ""}
      ${(a.inbound_shipments || []).length ? `<h3 style="margin-top:14px">Inbound shipments in transit (${a.inbound_shipments.length})</h3>
        <table><thead><tr><th>Shipment</th><th>Part</th><th>From</th><th>To</th><th>Planned arrival</th><th class="num">Units</th>
        <th class="num">Value</th><th class="num">Cover (d)</th><th class="num">Held up (d)</th><th>Verdict</th></tr></thead><tbody>
        ${a.inbound_shipments.map((s) => `<tr><td>${esc(s.shipment_id)}</td><td>${esc(s.part_id)}</td><td>${esc(s.origin_port)}</td><td>${esc(s.destination)}</td>
          <td>${date(s.planned_arrival)}${s.due_in_days < 0 ? ' <span class="muted">(overdue)</span>' : ""}</td><td class="num">${s.units.toLocaleString("en-IN")}</td>
          <td class="num">${inr(s.value_inr)}</td><td class="num">${s.cover_days ?? "—"}</td><td class="num">${s.held_up_days ?? "—"}</td><td>${esc(s.verdict || "")}</td></tr>`).join("")}
        </tbody></table><p class="muted">Already shipped, so caught by an event at the destination port or on the route: cover counts on-hand stock only.</p>` : ""}`,
    sources: `<table><thead><tr><th>Date</th><th>Source</th><th>Headline</th><th>ID</th></tr></thead><tbody>${srcs}</tbody></table>`,
    decide: !canDecide.length ? `<p class="sub">Viewing as ${esc(ROLE_NAMES[r0])}: sales can't record a decision on an alert. Share the briefing with the owner, ${esc(a.owner)}.</p>` : `<form class="stack" id="dec">
      <label>Option<select name="option">${opts.map((o) => `<option>${esc((o.part_id ? partName(o.part_id) + " (" + o.part_id + ") · " : "") + optText(o))}</option>`).join("")}</select></label>
      <label>Decision<select name="decision">${canDecide.map((d) => `<option>${d}</option>`).join("")}</select></label>
      ${r0 === "category" ? `<p class="muted" style="margin:0">A category manager proposes; the approver on the option decides.</p>` : ""}
      <label>Decided by (role)<select name="by">${[myBy, a.owner, ...["Category manager", "Head of Supply Chain", "Head of Supply Chain + Quality", "Head of Supply Chain + CFO", "Head of Sales + Supply Chain", "COO", "COO + CFO", "CEO", "Risk analyst"]].filter((v, i, x) => x.indexOf(v) === i)
        .map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>
      <label>Note<textarea name="note" placeholder="Why, and any conditions"></textarea></label>
      <div class="btns"><button class="btn" type="submit">Record decision</button></div>
      <p class="muted">This only records what a person decided (playbook §8). Nothing is ordered, booked or sent. On this demo the role is
      self-declared and the log is temporary; a pilot needs sign-in and a database.</p></form>
      ${decRows ? `<h3 style="margin-top:14px">Decision log</h3><table><thead><tr><th>When</th><th>Who</th><th>Decision</th><th>Option</th><th>Note</th></tr></thead><tbody>${decRows}</tbody></table>` : ""}`,
  };
  $("#app").innerHTML = `
    <p class="kicker"><a href="#/inbox">Alerts</a> · ${esc(a.alert_id)} · ${pill(a.priority, a.likelihood, a.impact)}</p>
    <div class="btns" style="justify-content:space-between;align-items:flex-end">
      <h1 style="margin:0">${esc(a.title)}</h1>
      <div class="btns"><a class="btn secondary" href="/api/alerts/${encodeURIComponent(a.alert_id)}/briefing" target="_blank" rel="noopener">Printable briefing</a>
      <button class="btn secondary" id="copy">Copy as email</button></div></div>
    <p class="muted">${esc(a.kind)} · first seen ${date(a.first_seen)} · ${a.n_signals} signals from ${a.n_sources} sources
      · impact on stock as of 30 Sep 2026 · quantified in ${a.seconds_to_quantify}s${a.actual_disruptions?.length ? ` · history: ${esc(a.actual_disruptions.join(", "))}` : ""}</p>
    ${alertVisual(a)}
    <div class="row">
      <div class="card" style="padding:0;border:0"><iframe class="brief" id="brief" title="One-page briefing"></iframe></div>
      <div><div class="tabs">${["options", "working", "sources", "decide"].map((t) =>
        `<button data-t="${t}" class="${t === tab ? "on" : ""}">${{ options: "Options", working: "Working", sources: "Sources", decide: "Decide" }[t]}</button>`).join("")}</div>
      <div class="card" id="tab">${T[tab]}</div></div>
    </div>`;
  const f = $("#brief"); f.srcdoc = await briefFrame(a);
  f.onload = () => { try { f.style.height = f.contentDocument.body.scrollHeight + 20 + "px"; } catch (e) {} };
  $("#copy").onclick = async () => { try { await navigator.clipboard.writeText(a.brief_text); toast("Briefing copied"); } catch (e) { toast("Copy blocked by the browser"); } };
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => viewAlert(id, b.dataset.t)));
  const form = $("#dec");
  if (form) form.onsubmit = async (ev) => {
    ev.preventDefault(); const d = Object.fromEntries(new FormData(form)); d.alert_id = a.alert_id;
    try { await api("/api/decisions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(d) });
      toast("Decision recorded"); viewAlert(id, "decide"); } catch (e) { toast("Could not record: " + e.message.slice(0, 80)); }
  };
}

async function viewRegister() {
  const rows = await api("/api/register");
  const grid = {}; rows.forEach((r) => { const k = `${r.likelihood}-${r.impact}`; grid[k] = (grid[k] || 0) + 1; });
  let m = '<div class="matrix"><div class="ax"></div>' + [1, 2, 3, 4, 5].map((i) => `<div class="ax">I${i}</div>`).join("");
  for (let L = 5; L >= 1; L--) {
    m += `<div class="ax">L${L}</div>`;
    for (let I = 1; I <= 5; I++) { const p = L * I, n = grid[`${L}-${I}`] || 0;
      m += `<div class="${pcls(p)}" style="opacity:${n ? 1 : 0.25}" title="L${L} × I${I} = ${p}">${n || ""}</div>`; }
  }
  m += "</div>";
  $("#app").innerHTML = `${hed("Risk register · shared", "Open risks, <em>owned</em> and scored.")}
    <p class="sub">Open risks scored likelihood × impact (playbook §2), with owner, response time and status. Status shows the latest human decision.</p>
    <div class="row"><div class="card"><table><thead><tr><th>Priority</th><th>Risk</th><th>Owner</th><th>Response</th><th class="num">At risk</th><th>Status</th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="click" data-id="${esc(r.alert_id)}"><td>${pill(r.priority, r.likelihood, r.impact)}</td><td><b>${esc(r.title)}</b>
      <div class="muted">${esc(r.kind)} · ${date(r.first_seen)}</div></td><td>${esc(r.owner.replace("Category manager: ", "CM: "))}</td>
      <td>${esc(r.response.split(";")[0])}</td><td class="num">${esc(r.revenue_at_risk_fmt)}</td><td>${esc(r.status)}</td></tr>`).join("")}
    </tbody></table></div><div class="card"><h3>Likelihood × impact</h3>${m}<p class="muted">Count of risks per cell. 20–25 war-room · 12–19 decide in 48 h · 6–11 owner assigned · 1–5 watch.</p></div></div>`;
  document.querySelectorAll("tr[data-id]").forEach((r) => (r.onclick = () => (location.hash = `#/alert/${r.dataset.id}`)));
}

function bars(rows, label, value, fmt) {
  const d = rows.filter((r) => r[value] > 0).slice(0, 10); const mx = Math.max(...d.map((r) => r[value]), 1);
  return `<div class="bars">${d.map((r) => `<div class="bar-row" title="${esc(`${r.parts} parts, ${r.single_source_parts} single-source, ${r.skus} SKUs`)}">
    <span>${esc(r[label])}</span><span class="track"><span class="fill" style="width:${(100 * r[value]) / mx}%"></span></span>
    <span class="bar-val">${fmt(r[value])}</span></div>`).join("")}</div>`;
}

async function viewExposure() {
  const [ex, meta] = await Promise.all([get("/api/exposure"), get("/api/meta")]);
  const h = meta.headline; const cr = (v) => `₹${Math.round(v).toLocaleString("en-IN")} cr`;
  const ss = ex.parts.filter((p) => p.single_source);
  $("#app").innerHTML = `${hed("Exposure · shared", "Where one event <em>stops the line</em>.")}
    <p class="sub">Where one event stops the line. Revenue behind a node = annual revenue of every product that needs a single-source part
    shipped from or through it (a product stops when any one part runs out).</p>
    <div class="tiles"><div class="tile"><b>${h.single_source_cover_below_lead} of ${h.single_source_parts}</b><span>single-source parts with cover below lead time</span></div>
      <div class="tile"><b>${h.east_asia_spend_pct}%</b><span>of ₹${Math.round(h.material_spend_inr_cr)} cr material spend ships from East Asia</span></div>
      <div class="tile"><b>${h.lost_revenue_via_single_source_pct}%</b><span>of past lost revenue came through single-source parts</span></div>
      <div class="tile"><b>${h.single_source_median_cover} vs ${h.single_source_median_lead} d</b><span>median cover vs lead time, single-source parts</span></div></div>
    <div class="row"><div class="card"><h3>By port of loading</h3>${bars(ex.ports, "node", "revenue_behind_single_source_inr_cr", cr)}</div>
      <div class="card"><h3>By commodity</h3>${bars(ex.categories, "node", "revenue_behind_single_source_inr_cr", cr)}</div></div>
    <div class="card"><h3>Single-source parts, most fragile first</h3>
      <div class="legend"><span><span class="sw hatch"></span>days of cover</span><span><span class="sw rule"></span>supplier lead time</span></div>
      <table><thead><tr><th>Part</th><th>Supplier · port</th><th class="num">Cover</th><th class="num">Lead</th><th>Cover vs lead</th><th class="num">SKUs</th>
      <th class="num">Revenue dep. (₹ cr/yr)</th><th>Fallback</th></tr></thead><tbody>
      ${ss.map((p) => `<tr><td><b>${esc(p.part_id)}</b> ${esc(p.description)}</td><td>${esc(p.supplier_name)}<div class="muted">${esc(p.port_of_loading)} · ${esc(p.country)}</div></td>
        <td class="num">${p.days_of_cover}</td><td class="num">${p.lead_time_days}</td>
        <td><div class="cov"><i style="width:${Math.min(100, (p.days_of_cover / 65) * 100)}%"></i><b style="left:${Math.min(100, (p.lead_time_days / 65) * 100)}%"></b></div></td>
        <td class="num">${p.n_skus}</td><td class="num">${Math.round(p.revenue_dependent_inr_cr)}</td>
        <td>${p.unqualified_alternate_supplier_id ? `unqualified ${esc(p.unqualified_alternate_supplier_id)} (${p.qualification_weeks_if_unqualified} wk)` : '<b style="color:var(--crit)">none</b>'}</td></tr>`).join("")}
      </tbody></table></div>`;
}

const EXAMPLES = [
  ["T1 Typhoon, southern Taiwan", "Typhoon forecast to hit southern Taiwan in five days", "Ports in the south may suspend operations; carriers warn of schedule disruption."],
  ["T2 Naval exercise", "Naval exercises announced near Taiwan Strait", "Shipping advisories issued for the exercise zone only."],
  ["T3 Red Sea", "Attacks on merchant vessels in the Red Sea escalate", "Major carriers divert via the Cape of Good Hope."],
  ["T4 Magnet licensing", "China announces export licensing on rare-earth magnets", "Exporters of NdFeB magnets must apply for licences; processing times not specified."],
  ["T5 PCB supplier health", "Shenzhen PCB maker delays supplier payments", "Local suppliers report invoices outstanding for over 90 days."],
  ["T7 Mumbai rain + JNPT", "Heavy rain alert for Mumbai; JNPT congestion rising", "Container movement slows as rains flood access roads to Nhava Sheva."],
  ["T8 Ransomware, Japan", "Japanese electronic components maker hit by ransomware", "Production and shipping halted while systems are restored."],
  ["Unlinked cyber story", "Components maker extends shutdown after cyber attack", "Customers advised that order processing is suspended."],
];

async function viewSimulate() {
  $("#app").innerHTML = `${hed("Ask · shared", "Check a <em>headline</em>.")}<nav class="seg" aria-label="Ask mode"><a href="#/ask" class="">Ask a question</a><a href="#/simulate" class="on">Check a headline</a></nav>
    <p class="sub">For a news item, not a question (for questions use <a href="#/ask">Ask a question</a>). Paste a headline and the co-pilot runs the full pipeline live: triage → link to the network → impact on today's stock → ranked options → briefing.
    Signals you try here are visible only to you, in this browser tab: they never reach anyone else's inbox. Nothing is ordered or sent.</p>
    <div class="examples">${EXAMPLES.map((e, i) => `<button data-i="${i}">${esc(e[0])}</button>`).join("")}</div>
    <div class="card"><form class="stack" id="sim">
      <label>Headline<input name="headline" required minlength="5" maxlength="300"></label>
      <label>Snippet (optional)<textarea name="snippet" maxlength="600"></textarea></label>
      <label>Expected duration in days (optional)<input name="duration_days" type="number" min="0" max="365" step="1"></label>
      <div class="btns"><button class="btn" type="submit">Run the co-pilot</button></div></form></div>
    <div id="out"></div>`;
  const pend = takePending("h");
  document.querySelectorAll(".examples button").forEach((b) => (b.onclick = () => {
    const e = EXAMPLES[+b.dataset.i]; const f = $("#sim"); f.headline.value = e[1]; f.snippet.value = e[2]; f.duration_days.value = ""; f.requestSubmit();
  }));
  $("#sim").onsubmit = async (ev) => {
    ev.preventDefault(); const d = Object.fromEntries(new FormData(ev.target));
    if (!d.duration_days) delete d.duration_days; else d.duration_days = +d.duration_days;
    $("#out").innerHTML = '<p class="muted">Running…</p>';
    try {
      const r = await api("/api/simulate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(d) });
      const t = r.triage;
      const head = { ignored: "Ignored: logged only", needs_review: "Needs review: not linked to our network", watch: "Watch log", inbox: "Alert: inbox" }[r.decision];
      let html = `<div class="result ${esc(r.decision)}"><b>${esc(head)}</b>${r.message ? `<p>${esc(r.message)}</p>` : ""}
        <p class="muted">Score ${t.score} (threshold ${r.threshold}) · ${esc(t.reason)}${t.event_type ? ` · class ${esc(t.event_type)}` : ""}</p>
        ${t.links.length ? `<div>${t.links.map(node).join("")}</div>` : ""}</div>`;
      const x = r.extraction;
      if (x) {
        const e = x.entities, list = (k, lab) => e[k]?.length ? `<li><b>${lab}:</b> ${e[k].map(esc).join(", ")}</li>` : "";
        html += `<div class="card"><h3 style="margin-top:0">What Veltrix Co-Pilot extracted</h3>
          <p class="muted" style="margin-top:0">Status <b>${esc(x.status.replace(/_/g, " "))}</b> · ${esc(x.event_type.replace(/_/g, " "))} · severity ${x.severity}/5${x.duration_days ? ` · ${x.duration_days} days` : ""}
          · ${x.relevant ? "supply risk that touches our network" : "not a live risk to our network"} (confidence ${Math.round(x.confidence * 100)}%)</p>
          <ul>${list("locations", "Locations")}${list("ports", "Ports")}${list("routes", "Routes")}${list("companies", "Companies")}${list("commodities", "Commodities")}</ul>
          ${(x.geo_links.length || x.cat_links.length) ? `<div>Linked by the network gazetteer: ${[...x.geo_links, ...x.cat_links].map(node).join("")}</div>` : `<p class="muted">None of these names is in Veltrix's network.</p>`}
          <p class="muted">${esc(x.reason)} · Decision rule chosen on train data: <b>${esc(r.triage_rule)}</b>${r.claude_promoted ? " · Veltrix Co-Pilot flagged a signal the word list missed" : ""}.</p></div>`;
      }
      if (r.alert) {
        const a = r.alert;
        html += `${alertVisual(a)}<div class="btns" style="margin:8px 0"><a class="btn" href="#/alert/${encodeURIComponent(a.alert_id)}">Open full alert</a></div>
          <div class="card" style="padding:0;border:0"><iframe class="brief" id="sbrief" title="Briefing"></iframe></div>`;
      }
      $("#out").innerHTML = html;
      $("#out").scrollIntoView({ behavior: "smooth", block: "start" });
      if (r.alert) { const f = $("#sbrief"); f.srcdoc = await briefFrame(r.alert); f.onload = () => { try { f.style.height = f.contentDocument.body.scrollHeight + 20 + "px"; } catch (e) {} }; }
    } catch (e) { $("#out").innerHTML = `<div class="result needs_review">Error: ${esc(e.message.slice(0, 300))}</div>`; }
  };
  if (pend) { const f = $("#sim"); f.headline.value = pend; f.snippet.value = PENDING_SNIPPET; f.requestSubmit(); }
}

async function viewBacktest() {
  const [b, bc] = await Promise.all([get("/api/backtest"), get("/api/business-case").catch(() => null)]);
  const s = b.signals.test, a = b.alerts.test, l = b.lead.test;
  const m2 = b.m2?.summary;
  $("#app").innerHTML = `${hed("Evidence · shared", "Tested on months it <em>never saw</em>.")}
    <p class="sub">Every signal from Oct 2024 to Sep 2026 was replayed through the co-pilot. Rules were tuned on the train period; results below are the test period
    (from 1 Feb 2026, disruptions D14–D18), scored against the ground-truth labels.</p>
    <div class="tiles"><div class="tile"><b>${(s.recall * 100).toFixed(1)}%</b><span>recall: ${s.tp}/${s.relevant} relevant signals caught (target ≥ 80%)</span></div>
      <div class="tile"><b>${Math.round(a.precision * 100)}%</b><span>alert precision: ${a.relevant_alerts}/${a.alerts} alerts relevant; ${s.fp} false-alarm signals (target ≥ 60%)</span></div>
      <div class="tile"><b>${l.median_lead_days.toFixed(1)} d</b><span>median warning before impact; ${l.detected}/${l.disruptions_with_warning} warned disruptions caught (target ≥ 7 d)</span></div>
      ${m2 ? `<div class="tile"><b>${m2.A.median_abs_err_pct.toFixed(1)}%</b><span>impact engine median error replaying D01–D18 (${esc(m2.A.within_25pct)} within ±25%)</span></div>` : ""}</div>
    <div class="card"><h3>Lead time per disruption</h3><table><thead><tr><th>ID</th><th>Disruption</th><th>Split</th><th>Warning?</th><th>Co-pilot alert</th>
      <th class="num">Lead (d)</th><th class="num">Team (d)</th><th class="num">Days gained</th></tr></thead><tbody>
      ${b.lead_table.map((r) => `<tr><td>${esc(r.disruption_id)}</td><td>${esc(r.title)}</td><td>${esc(r.split)}</td><td>${r.had_warning ? "yes" : "sudden"}</td>
        <td>${date(r.first_alert)}</td><td class="num">${r.lead_days ?? "—"}</td><td class="num">${r.team_lead_days}</td><td class="num">${r.days_gained_vs_team ?? "—"}</td></tr>`).join("")}
      </tbody></table><p class="muted">Lead = disruption start − co-pilot's first alert. Team = start − team's first internal alert (negative = noticed after impact).</p></div>
    <div class="card"><h3>Test-period misses (${b.misses.length}) and false alarms (${b.false_alarms.length})</h3>
      <table><tbody>${b.misses.map((m) => `<tr><td>miss</td><td>${esc(m.linked_disruption_id)}</td><td>${esc(m.text)}</td><td class="num">score ${m.score}</td></tr>`).join("")}
      ${b.false_alarms.map((m) => `<tr><td>false alarm</td><td></td><td>${esc(m.text)}</td><td class="num">score ${m.score}</td></tr>`).join("")}</tbody></table>
      <p class="muted">The acceptance tests T1–T10 can be run live from <a href="#/simulate">Check a headline</a>, <a href="#/ask">Ask</a> and <a href="#/replay/D05">Replay D05</a>.</p></div>
    <h2>Beyond the data pack: <em>harder</em> news</h2>
    <p class="sub">Rules were changed on train data only, then each test set was scored once. Real news: 416 archived headlines from 2023–24
      (Red Sea, Taiwan quake, Baltimore bridge, gallium controls and three quiet periods), tuned on 2023 and scored on 2024.</p>
    <div class="card"><table><thead><tr><th>Measure</th><th class="num">Brief's target</th><th class="num">Two-year forecast test</th><th class="num">Real news, 2024</th></tr></thead><tbody>
      <tr><td>Alert precision: alerts that were real risks</td><td class="num">≥ 60%</td><td class="num">100%</td><td class="num">86% <span class="muted">(6 of 7)</span></td></tr>
      <tr><td>Relevant signals surfaced in an alert</td><td class="num">≥ 80%</td><td class="num">94.9%</td><td class="num">68% <span class="muted">(19 of 28)</span></td></tr>
      <tr><td>Real events that raised an alert</td><td class="num">—</td><td class="num">—</td><td class="num">6 of 6</td></tr>
      <tr><td>False alerts per week</td><td class="num">—</td><td class="num">—</td><td class="num">0.12</td></tr>
      <tr><td>Median warning before impact</td><td class="num">≥ 7 d</td><td class="num">13.3 d</td><td class="num">—</td></tr></tbody></table>
      <p class="muted">Most real-news misses are follow-up stories about a crisis that already has an open alert. Method and caveats:
      <a href="https://github.com/amisha-0709/Veltrix_SupplyChain_Risk_Copilot/blob/main/docs/EVALUATION.md" target="_blank" rel="noopener">EVALUATION.md</a>.</p></div>
    ${bc ? `<h2>False alarms: <em>what each safeguard prevents</em></h2>
    <p class="sub">The brief asks for a false-alarm analysis and the changes made to reduce it. Each safeguard is switched off in turn and the test months re-scored.</p>
    <div class="card"><table><thead><tr><th>Safeguard switched off</th><th class="num">False-alarm signals (test)</th><th class="num">False alerts (test)</th><th class="num">Alert precision (test)</th></tr></thead>
      <tbody>${bc.ablations.map((r) => `<tr><td>${esc(r["guard removed"])}</td><td class="num">${r.false_alarm_signals_test}</td><td class="num">${r.false_alerts_test}</td><td class="num">${r.precision_test == null ? "—" : Math.round(r.precision_test * 100) + "%"}</td></tr>`).join("")}</tbody></table>
      <p class="muted">Alert load as built: ${bc.load.alerts_per_week} alerts a week and ${bc.load.inbox_per_month} inbox alerts a month, from ${bc.load.signals_per_week} signals a week read.</p></div>` : ""}`;
}

/* ---------------- ask (chat) ---------------- */
const ASK_EXAMPLES = [
  "Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?",
  "Which products stop first if Kaohsiung closes for ten days?",
  "Which products stop first if Kaohsiung closes for forty days?",
  "How exposed are we to Shanghai?",
  "What if the Red Sea closes?",
  "What's in the inbox right now?",
];
const chat = [];
const tableHtml = (t) => `<h3 style="margin-top:12px">${esc(t.title)}</h3><div style="overflow-x:auto"><table><thead><tr>${t.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
  <tbody>${t.rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v === true ? "yes" : v === false ? "no" : v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
/* "what_if(places=Kaohsiung, Taiwan; event_type=port_closure; include_options=True)" -> "What if: Kaohsiung, Taiwan · port closure" */
const QNAMES = { what_if: "What if", which_customers: "Customers hit", exposure: "Exposure", inbox: "Open alerts", compare: "Compare", options: "Options",
  dual_sourcing: "Dual-sourcing moves", business_case: "Business case", history: "Disruption history" };
const readable = (t) => String(t).replace(/^(\w+)\((.*)\)$/, (m, fn, args) => {
  const parts = args.split(/;\s*/).filter((x) => x && !/^include_options=/.test(x)).map((x) => {
    const [k, v] = x.split("="); if (v == null) return x;
    return (k === "duration_days" ? `${v} days` : v.replace(/_/g, " "));
  });
  return `${QNAMES[fn] || fn.replace(/_/g, " ")}${parts.length ? ": " + parts.join(" · ") : ""}`;
});
const engineBadge = (r) => r.engine === "claude"
  ? (r.tool_calls ? `<p class="kicker" style="margin:0 0 8px">Understood as · ${(r.interpretation || []).map((t) => esc(readable(t))).join(" + ")}</p>`
      : `<p class="muted" style="margin-top:0">Veltrix Co-Pilot: no engine query fits this question.</p>`)
  : r.engine === "rules" ? `<p class="muted" style="margin-top:0">Rule-based answer${r.engine_note ? ": " + esc(r.engine_note) : ""}</p>` : "";
/* first sentence as the verdict, the rest as the explanation */
const verdict = (t) => { const s = String(t || ""); const i = s.search(/[.!?](\s|$)/);
  const head = i > 0 ? s.slice(0, i + 1) : s, rest = i > 0 ? s.slice(i + 1).trim() : "";
  return `<p style="font:700 26px/1.1 var(--sans);letter-spacing:-.03em;margin:4px 0 8px">${esc(head)}</p>${rest ? `<p style="white-space:pre-line;margin-top:0">${esc(rest)}</p>` : ""}`; };
function renderChat() {
  $("#log").innerHTML = chat.map((m) => m.role === "user"
    ? `<div class="result ignored"><p class="kicker" style="margin:0">You asked</p><p style="font-size:18px;margin:4px 0">${esc(m.text)}</p></div>`
    : m.role === "hint" ? `<div class="result needs_review"><b>That reads like a news headline.</b><p>Ask answers questions about scenarios and your data
        (“What if Kaohsiung closes for ten days?”). To see what a news item means for Veltrix, as an alert with impact, options and a briefing,
        run it through Check a headline.</p><div class="btns"><button class="btn small" data-hl="${esc(m.text)}">Check it as a headline</button></div></div>`
    : `<div class="card">${engineBadge(m.r)}${verdict(m.r.answer)}
        ${(m.r.tables || []).map(tableHtml).join("")}
        ${m.r.working?.length ? `<details><summary class="muted">${m.r.engine === "claude" ? "Working: Veltrix Co-Pilot's reading and the engine's steps" : "Working (playbook §3)"}</summary><ol class="steps">${m.r.working.map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></details>` : ""}
        ${m.r.assumptions?.length ? `<details><summary class="muted">Assumptions</summary><ul>${m.r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}</div>`).join("");
  document.querySelectorAll("[data-hl]").forEach((b) => (b.onclick = () => goPending({ kind: "h", text: b.dataset.hl })));
}
async function viewAsk() {
  $("#app").innerHTML = `${hed("Ask · shared", "Ask the <em>co-pilot</em>.")}<nav class="seg" aria-label="Ask mode"><a href="#/ask" class="on">Ask a question</a><a href="#/simulate" class="">Check a headline</a></nav>
    <p class="sub"><b>Ask</b> is for questions about scenarios and your own data: “What if Kaohsiung closes for ten days?”, “Which customers miss 95% OTIF if…?”.
    You get a direct answer with the working. <b>Check a headline</b> is for a news item: it runs as if the news just arrived and gives a full alert
    (triage, linked parts and customers, ₹ impact, ranked options, briefing). Typos, Hinglish and comparisons are fine; every number comes from the impact engine.
    <span id="eng" class="muted"></span></p>
    <div class="examples">${ASK_EXAMPLES.map((e, i) => `<button data-i="${i}">${esc(e)}</button>`).join("")}</div>
    <div id="log"></div>
    <form class="card stack" id="askf"><label>Your question<input name="q" required maxlength="400" placeholder="e.g. Which products stop first if Ningbo closes for three weeks?"></label>
      <div class="btns"><button class="btn" type="submit">Ask</button></div></form>`;
  renderChat();
  api("/api/chat-engine").then((e) => { const el = $("#eng"); if (el) el.textContent = e.engine === "claude" ? `Now answering: Veltrix Co-Pilot AI reader.` : "Now answering: rule-based parser (no API key set)."; }).catch(() => {});
  const send = async (q) => {
    chat.push({ role: "user", text: q });
    if (!looksLikeQuestion(q)) chat.push({ role: "hint", text: q });
    chat.push({ role: "bot", r: { answer: "Reading your question…" } }); renderChat(); chat.pop();
    try { const r = await api("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
      chat.push({ role: "bot", r }); } catch (e) { chat.push({ role: "bot", r: { answer: "Error: " + e.message.slice(0, 200) } }); }
    renderChat(); $("#askf").scrollIntoView({ behavior: "smooth", block: "end" });
  };
  document.querySelectorAll(".examples button").forEach((b) => (b.onclick = () => send(ASK_EXAMPLES[+b.dataset.i])));
  $("#askf").onsubmit = (ev) => { ev.preventDefault(); const q = ev.target.q.value.trim(); if (q) { ev.target.q.value = ""; send(q); } };
  const pend = takePending("q"); if (pend) send(pend);
}

/* ---------------- replay (T10) ---------------- */
function replayVerdict(r) {
  const est = r.seen.delay_estimate_days, act = r.actual_delay_days, lost = r.actual_revenue_lost_inr;
  if (r.had_warning === false) {          /* sudden event: the brief expects day-one value, not early warning */
    const teamDay = r.team_alert_date ? Math.round((new Date(r.team_alert_date) - new Date(r.start_date)) / 864e5) : null;
    const when = r.detected ? `it alerted on impact day${teamDay > 0 ? `, ${teamDay} day${teamDay === 1 ? "" : "s"} before the team noticed` : ""} and ${r.team_decision_day} days before the team's first decision`
      : "it would have quantified the impact on day one";
    const lc = (t) => t.charAt(0).toLowerCase() + t.slice(1);
    const list = (xs) => xs.length > 1 ? xs.slice(0, -1).join(", ") + " and " + xs[xs.length - 1] : xs[0];
    const fast = (r.top_options || []).find((o) => o.fixes_shortage && (o.net_value_inr ?? 0) < 0 && o.on_time !== false);
    const recs = r.recommended || [];
    const did = recs.length ? `Its recommendation: ${list(recs.map((x) => lc(optText(x))))}${r.margin_protected_inr > 0 ? `, keeping ${inr(r.margin_protected_inr)} more profit` : ""}${r.plan_cost_inr > 0 ? ` for ${inr(r.plan_cost_inr)}` : ""}.`
      : lost > 0 ? "No option paid back on what it knew that day, so the loss stands." : "Stock covered the outage: no action, no spend.";
    const st = r.structural && r.structural.revenue_protected_inr > 0
      ? ` The real lesson is structural: ${list(r.structural.parts.map((p) => { const m = p.match(/^(PRT-\d+) → qualify (SUP-\d+) \((\d+) wk\)/); return m ? `qualifying ${supName(m[2])} for the ${partName(m[1])} (${m[3]} weeks)` : nameIds(p.replace(/ in advance$/, "")); }))} in advance, for about ${inr(r.structural.cost_inr)}, would have protected about ${inr(r.structural.revenue_protected_inr)}.` : "";
    return `No public warning was possible, so ${when}. ${fast ? `The only fast fix, ${lc(optText(fast))} (${inr(fast.cost_inr)}), costs more than it saves. ` : ""}${did}${st}`;
  }
  if (!r.detected) return `No public warning, so no early alert; on day one it would have quantified the impact and ranked options.`;
  if (!r.recommended.length && lost > 0 && est != null && est < act)
    return `It alerted ${r.copilot_lead_days} days early, but expected supply to be cut for ${est} days; it was actually ${act}. Stock looked enough, so it advised monitoring, and the ${inr(lost)} loss would still have happened. A miss on duration, not on detection.`;
  if (!r.recommended.length && lost > 0) return `It alerted ${r.copilot_lead_days} days early but no option paid back on what it knew that day, so the ${inr(lost)} loss would still have happened.`;
  if (!r.recommended.length) return `It alerted ${r.copilot_lead_days} days early and correctly said stock was enough: no action, no spend${r.avoided_waste_inr > 0 ? `, and ${inr(r.avoided_waste_inr)} of the team's spend skipped` : ""}.`;
  return `It alerted ${r.copilot_lead_days} days early; its plan would have protected about ${inr(Math.max(0, r.vs_actual_protected_expected_inr))} of the ${inr(lost)} lost, for ${inr(r.plan_cost_inr)}.`;
}
async function viewReplay(did = "D04") {
  const [list, r] = await Promise.all([get("/api/replays"), api(`/api/replays/${encodeURIComponent(did)}`)]);
  const s = list.summary;
  const opts = (r.top_options || []).map((o) => `<tr><td>${niceOpt(o)}</td><td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td>
    <td>${o.on_time ? "in time" : "late"}</td><td>${esc(o.approver)}</td></tr>`).join("");
  const rec = r.recommended.length ? r.recommended.map((x) => `<li><b>${esc(optText(x))}</b> for ${esc(partName(x.part_id))} <span class="pid">${esc(x.part_id)}</span>: ${inr(x.cost_inr)}, ${x.time_to_effect_days} d to effect; ${esc(x.approver)}</li>`).join("")
    : "<li>No option clears the playbook's net-value bar (margin protected must exceed cost).</li>";
  const st = r.structural;
  $("#app").innerHTML = `${hed("Replay · shared", "What if it had been <em>live</em>?")}
    <p class="sub">The co-pilot sees only what it would have known that day: its own alert date from the signal back-test, stock cover at the time, and its
    <i>own</i> delay estimate. Its plan is then applied to what actually happened.</p>
    <div class="tiles"><div class="tile"><b>₹${s.revenue_protected_expected_cr} cr</b><span>expected revenue protected across all 18 disruptions (of ₹${s.actual_revenue_lost_cr} cr lost)</span></div>
      <div class="tile"><b>₹${s.plan_cost_cr} cr</b><span>cost of the recommended plans; ROI on plans ${s.roi_on_plans ?? "—"}×</span></div>
      <div class="tile"><b>₹${s.avoided_waste_cr} cr</b><span>of ₹${s.team_wasted_cr} cr wasted spend avoided (cover was enough)</span></div>
      <div class="tile"><b>₹${s.structural_protected_cr} cr</b><span>more if unqualified alternates had been qualified in advance (structural; overlaps with plans)</span></div></div>
    <div class="tabs">${list.rows.map((x) => `<button data-d="${esc(x.disruption_id)}" class="${x.disruption_id === r.disruption_id ? "on" : ""}">${esc(x.disruption_id)}</button>`).join("")}</div>
    <h2>${esc(r.disruption_id)} · ${esc(r.title)}</h2>
    ${replayTimeline(r)}
    <div class="row"><div class="card">
      <table><tbody>
        <tr><td>Impact started</td><td>${date(r.start_date)}</td></tr>
        <tr><td><b>Co-pilot first alert</b></td><td><b>${r.detected ? date(r.copilot_alert_date) + ` (${r.copilot_lead_days} d before impact)` : "not detected"}</b></td></tr>
        <tr><td>Team first alert</td><td>${date(r.team_alert_date)}</td></tr>
        <tr><td>Team first decision</td><td>day +${r.team_decision_day} after impact</td></tr>
        <tr><td>How long supply would be cut off: co-pilot's estimate on the day / what actually happened</td><td>${r.seen.delay_estimate_days ?? "—"} days / ${r.actual_delay_days} days</td></tr>
        <tr><td>Revenue at risk it would have shown on the day</td><td>${inr(r.seen.revenue_at_risk_inr)} (${r.seen.skus_stopped} products)</td></tr>
      </tbody></table>
      <h3 style="margin-top:14px">It would have recommended</h3><ul>${rec}</ul>
      <div class="result ${r.vs_actual_protected_expected_inr > 0 ? "inbox" : ""}"><b>${esc(replayVerdict(r))}</b></div>
      <h3>Outcome in rupees</h3><table><tbody>
        <tr><td>Revenue Veltrix actually lost</td><td class="num">${inr(r.actual_revenue_lost_inr)}</td></tr>
        <tr><td>Revenue still lost if the co-pilot's plan had been followed${r.recommended.length ? "" : " (it advised no action, so the loss is unchanged)"}</td><td class="num">${inr(r.with_plan_lost_inr)}</td></tr>
        <tr><td><b>Revenue the co-pilot would have protected</b>${r.recommended.length ? ` (expected: × ${Math.round(r.plan_p_works * 100)}% chance the plan works)` : ""}</td><td class="num"><b>${inr(Math.max(0, r.vs_actual_protected_expected_inr))}</b></td></tr>
        <tr><td>Cost of its plan</td><td class="num">${inr(r.plan_cost_inr)}</td></tr>
        <tr><td>Profit (margin) protected / late-delivery penalties avoided</td><td class="num">${inr(r.margin_protected_inr)} / ${inr(r.penalties_avoided_inr)}</td></tr>
        <tr><td>Team's spend on parts that turned out to have enough stock / of it, what the co-pilot would have skipped</td><td class="num">${inr(r.team_wasted_inr)} / ${inr(r.avoided_waste_inr)}</td></tr>
      </tbody></table>
      ${st ? `<div class="result" style="margin-top:12px"><b>Structural fix the exposure map flags</b><p>${st.parts.map(esc).join("; ")}: about ${inr(st.cost_inr)}.
        Had this been done before the event, a switch would land ~19 days after impact: <b>${inr(st.revenue_protected_inr)}</b> of revenue protected.</p></div>` : ""}
    </div><div class="card"><h3>Options it ranked (on the day)</h3><table><thead><tr><th>Option</th><th class="num">Cost</th><th class="num">Net value</th><th>Timing</th><th>Approver</th></tr></thead>
      <tbody>${opts || '<tr><td colspan="5" class="muted">Cover was enough: no options needed.</td></tr>'}</tbody></table>
      <details><summary class="muted">Working on the day</summary><ol class="steps">${(r.seen.working || []).map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></details>
      <p class="muted">Switches are assumed to take hold in 19 days (observed in history), not the playbook's 5–10. Team actions the co-pilot didn't cover still count.</p></div></div>`;
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => (location.hash = `#/replay/${b.dataset.d}`)));
}

/* ---------------- business case (brief §1, §3, §7, Stage 1 + 3; playbook §5–§6) ---------------- */
/* Every figure is from the data pack and the replay; every assumption is labelled where it is used and listed at the end. */
const ASSUME = {
  A1: "Two years of history (Oct 2024 – Sep 2026, 18 disruptions); yearly figures are the two-year totals ÷ 2.",
  A2: "Alert day = the co-pilot's own first alert in the signal back-test, not hindsight.",
  A3: "On alert day the co-pilot uses its own estimate of how long supply is cut (event-type default × recovery ratio fitted on D01–D13), not the actual duration.",
  A4: "Chance an action works in time (our assumption): pre-buy and re-route 90%, air freight 85%, switching or qualifying a known alternate 70%, broker buy 70%, a new supplier or demand shaping 50%, re-allocation 100%.",
  A5: "Switching to a qualified alternate takes hold in 19 days, as observed in the history, not the playbook's 5–10.",
  A6: "55% of a shortage becomes lost sales and 45% ships late with contract penalties (matches the data pack's disruption_impacts).",
  A7: "Only what the co-pilot adds over what the team actually did is credited; the team's own actions still count in every case.",
  A8: "Wasted spend = the team's actions on parts the data pack marks as having enough cover (had_shortage = False) that the co-pilot's own estimate would also have judged safe.",
  A9: "Running costs are our estimates (the brief gives none), set on the generous side; model calls at list price with $1 = ₹88.",
  A10: "Outlier test drops events that lost more than $1M (about ₹8.8 cr), the problem owner's rule.",
  A11: "Structural moves: supplier outage rate 2.9% per supplier per year (5 outages across 87 suppliers in 2 years), qualification ₹15 lakh per part (playbook range ₹8–25 lakh), holding cost 22% a year (playbook).",
};
const aref = (...k) => k.map((x) => `<button type="button" class="aref" data-aref title="${esc(ASSUME[x])}">${x}</button>`).join(" ");

async function viewBusiness() {
  const [m, rp, meta] = await Promise.all([get("/api/business-case"), get("/api/replays"), get("/api/meta")]);
  const rs = rp.summary, b = m.base, base = m.scenarios[0], h = meta.headline, ts = meta.timeline_summary || {};
  const x = (v) => v == null ? "—" : `${v.toFixed(1)}×`;
  const cr = (v) => `₹${(v / 1e7).toFixed(2)} cr`;
  const rows = rp.rows;
  const net2 = rs.margin_protected_cr + rs.penalties_avoided_cr + rs.avoided_waste_cr - rs.plan_cost_cr;
  const lossAvoided2 = rs.margin_protected_cr + rs.penalties_avoided_cr + rs.avoided_waste_cr;
  const ss = m.structural_summary, moves = m.structural.filter((r) => r.net_annual_value_inr > 0);
  const COST_LABEL = { "build and pilot one off": "Build and 3-month pilot", "news and data feeds": "News and data feeds", hosting: "Hosting",
    "model calls": "AI model calls", "risk owner": "Risk owner (half a risk analyst)", maintenance: "Maintenance (a quarter of an engineer)" };
  const COST_BASIS = {
    "build and pilot one off": "₹35 lakh one-off: connect the ERP stock and in-transit feed, set up, run a 3-month pilot; spread over 3 years.",
    "news and data feeds": "Allowance for one licensed news feed. The public sources the brief lists (GDELT, PortWatch, Global Trade Alert) are free.",
    hosting: "Allowance for the web app, a managed database and monitoring.",
    "model calls": "Calculated: 5,000 signals a day read by a small model, plus briefings and questions on a large model, at list price.",
    "risk owner": "0.5 of a ~₹24 lakh a year analyst to own the inbox and weekly review; the brief notes nobody owns monitoring today.",
    maintenance: "0.25 of a ~₹32 lakh a year engineer for rules, data feeds and model updates.",
  };
  const SCEN = { "Base: all 18 disruptions": "Base case: all 18 disruptions",
    "Test period only (Feb–Sep 2026, annualised)": "Only the held-out test months (Feb–Sep 2026), annualised",
    "Outliers removed (events losing > $1M)": "Big events removed: any disruption that lost more than about ₹8.8 cr",
    "Half the probability of success": "Every action half as likely to work",
    "Costs doubled": "Running costs doubled" };
  const tl = (r) => r.detected ? (r.copilot_lead_days > 0 ? `${r.copilot_lead_days} d before` : "on the day") : "not detected";
  const teamDay = (r) => { const d = Math.round((new Date(r.team_alert_date) - new Date(r.start_date)) / 864e5); return d === 0 ? "on the day" : d > 0 ? `${d} d after` : `${-d} d before`; };
  const act = (r) => r.recommended?.length ? r.recommended.slice(0, 2).map((o) => esc(optText(o))).join("; ") + (r.recommended.length > 2 ? ` +${r.recommended.length - 2}` : "") : '<span class="muted">No action (stock judged enough)</span>';
  const wasteRows = rows.filter((r) => r.team_wasted_inr > 0);
  const sumBy = (xs) => { const c = {}; xs.forEach((a) => (c[a.action] = (c[a.action] || 0) + 1)); return Object.entries(c).map(([k, n]) => `${esc(k)}${n > 1 ? ` ×${n}` : ""}`).join(", "); };

  $("#app").innerHTML = `${hed("Business case · shared", "What resilience is <em>worth</em> to Veltrix.")}
    <p class="sub" style="font-size:20px">Replayed over the last two years, the co-pilot nets <b>${inr(b.net)} a year</b> against <b>${inr(m.annual_cost_inr)}</b>
      a year to run: a <b>${x(base.roi)}</b> return that pays back in about <b>${(base.payback_months * 30).toFixed(0)} days</b>. ${aref("A1", "A9")}</p>
    <p class="muted">Built the way the brief asks: replay all 18 disruptions with the co-pilot's alert date and top-ranked option, value the result with the playbook's
      ROI method, and include the co-pilot's own running costs. Labels like <span class="aref">A4</span> point to the assumptions listed at the end.</p>

    <p class="sub">Today: ₹${h.revenue_lost_inr_cr.toFixed(1)} cr of revenue lost to ${h.disruptions} disruptions in two years, and ₹${h.mitigation_spend_no_shortage_inr_cr.toFixed(1)} cr of ₹${h.mitigation_spend_inr_cr.toFixed(1)} cr
      mitigation spend wasted on parts that had enough stock; public warnings came a median ${ts.median_warning_lead_days ?? 18} days ahead, the team noticed ${ts.median_team_alert_offset_days ?? 1} day after impact.</p>

    <h2>Loss avoided, by the <em>playbook's formula</em></h2>
    <p class="sub">Playbook §6: <b>ROI = (loss avoided − cost) ÷ cost</b>, where loss avoided = margin protected + penalties avoided + expedite costs avoided.
      Revenue protected is sales kept; only the profit on those sales counts, because the cost of making them is spent either way. ${aref("A6", "A7")}</p>
    <div class="card"><table><thead><tr><th>Line</th><th class="num">Two years</th><th class="num">Per year</th></tr></thead><tbody>
      <tr><td class="muted">Revenue protected (sales kept, for reference)</td><td class="num muted">₹${rs.revenue_protected_expected_cr} cr</td><td class="num muted">₹${(rs.revenue_protected_expected_cr / 2).toFixed(2)} cr</td></tr>
      <tr><td>Margin protected</td><td class="num">₹${rs.margin_protected_cr} cr</td><td class="num">${inr(b.margin_protected)}</td></tr>
      <tr><td>+ Penalties avoided</td><td class="num">₹${rs.penalties_avoided_cr} cr</td><td class="num">${inr(b.penalties_avoided)}</td></tr>
      <tr><td>+ Expedite and buffer spend avoided (detail under wasted spend, below)</td><td class="num">₹${rs.avoided_waste_cr} cr</td><td class="num">${inr(b.waste_avoided)}</td></tr>
      <tr><td><b>= Loss avoided</b></td><td class="num"><b>₹${lossAvoided2.toFixed(2)} cr</b></td><td class="num"><b>${inr(b.margin_protected + b.penalties_avoided + b.waste_avoided)}</b></td></tr>
      <tr><td>− Cost of the actions it recommends</td><td class="num">−₹${rs.plan_cost_cr} cr</td><td class="num">−${inr(b.mitigation_cost)}</td></tr>
      <tr><td><b>= Net benefit</b></td><td class="num"><b>₹${net2.toFixed(2)} cr</b></td><td class="num"><b>${inr(b.net)}</b></td></tr></tbody></table>
      <p class="muted">ROI on the recommended actions alone (margin + penalties they protect, before any wasted spend skipped) =
        (₹${(rs.margin_protected_cr + rs.penalties_avoided_cr).toFixed(2)} cr − ₹${rs.plan_cost_cr} cr) ÷ ₹${rs.plan_cost_cr} cr ≈ <b>${rs.roi_on_plans}×</b>
        (the playbook's worked example is about 3.1× for a single pre-buy).</p></div>

    <h2>ROI on the co-pilot itself, <em>including running costs</em></h2>
    <p class="sub">The brief asks for this explicitly (Stage 3). The brief and playbook give no running costs, so these are our estimates, labelled as such. ${aref("A9")}</p>
    <div class="card"><table><thead><tr><th>Running cost</th><th class="num">Per year</th><th>Basis (our estimate unless stated)</th></tr></thead><tbody>
      ${m.cost_rows.map((r) => `<tr><td>${esc(COST_LABEL[r.item] || r.item)}</td><td class="num">${inr(r.annual_inr)}</td><td class="muted">${esc(COST_BASIS[r.item] || r.note)}</td></tr>`).join("")}
      <tr><td><b>Total</b></td><td class="num"><b>${inr(m.annual_cost_inr)}</b></td><td></td></tr></tbody></table>
      <table style="margin-top:16px"><tbody>
        <tr><td>Net benefit per year (from the loss-avoided table)</td><td class="num">${inr(b.net)}</td></tr>
        <tr><td>Running cost per year</td><td class="num">${inr(m.annual_cost_inr)}</td></tr>
        <tr><td><b>ROI = (net benefit − running cost) ÷ running cost</b></td><td class="num"><b>${x(base.roi)}</b></td></tr>
        <tr><td>Payback: running cost ÷ net benefit per month</td><td class="num">${base.payback_months.toFixed(1)} months</td></tr></tbody></table></div>

    <h2>How <em>robust</em> is it?</h2>
    <p class="sub">The same calculation with harsher assumptions. It still pays back in every case. ${aref("A10")}</p>
    <div class="card"><table><thead><tr><th>Scenario</th><th class="num">Net benefit / yr</th><th class="num">Running cost / yr</th><th class="num">ROI</th><th class="num">Payback (months)</th></tr></thead>
      <tbody>${m.scenarios.map((r) => `<tr><td>${esc(SCEN[r.scenario] || r.scenario)}</td><td class="num">${inr(r.net_benefit_inr)}</td><td class="num">${inr(r.copilot_cost_inr)}</td>
        <td class="num"><b>${x(r.roi)}</b></td><td class="num">${r.payback_months ? r.payback_months.toFixed(1) : "—"}</td></tr>`).join("")}</tbody></table></div>

    <h2>Replay: all <em>18 disruptions</em></h2>
    <p class="sub">Each disruption replayed with the co-pilot's own alert day and its top-ranked option on that day, applied to what really happened. ${aref("A2", "A3", "A4", "A5", "A7")}</p>
    <div class="card"><div style="overflow-x:auto"><table><thead><tr><th>#</th><th>Disruption</th><th>Co-pilot alert</th><th>Team alert</th><th>Its top action</th>
      <th class="num">Action cost</th><th class="num">Revenue lost</th><th class="num">Revenue protected</th><th class="num">Margin protected</th><th class="num">Waste skipped</th></tr></thead><tbody>
      ${rows.map((r) => `<tr class="click" data-rep="${esc(r.disruption_id)}"><td>${esc(r.disruption_id)}</td><td><b>${esc(r.title)}</b></td><td>${tl(r)}</td><td>${teamDay(r)}</td>
        <td>${act(r)}</td><td class="num">${inr(r.plan_cost_inr)}</td><td class="num">${inr(r.actual_revenue_lost_inr)}</td>
        <td class="num">${inr(Math.max(0, r.vs_actual_protected_expected_inr))}</td><td class="num">${inr(r.margin_protected_inr)}</td><td class="num">${inr(r.avoided_waste_inr)}</td></tr>`).join("")}
      <tr><td></td><td><b>Total, two years</b></td><td></td><td></td><td></td><td class="num"><b>₹${rs.plan_cost_cr} cr</b></td><td class="num"><b>₹${rs.actual_revenue_lost_cr} cr</b></td>
        <td class="num"><b>₹${rs.revenue_protected_expected_cr} cr</b></td><td class="num"><b>₹${rs.margin_protected_cr} cr</b></td><td class="num"><b>₹${rs.avoided_waste_cr} cr</b></td></tr>
      </tbody></table></div>
      <p class="muted">Revenue protected is expected value: what the plan saves × the chance it works. Open a row for its full replay.</p></div>

    <h2>Wasted mitigation spend, <em>with the logic</em></h2>
    <p class="sub">The brief's metric: ₹${h.mitigation_spend_no_shortage_inr_cr.toFixed(1)} cr of ₹${h.mitigation_spend_inr_cr.toFixed(1)} cr went on parts that turned out to have enough stock.
      The co-pilot compares each part's days of cover with its own delay estimate; where cover is longer, it says “no action”. ${aref("A3", "A8")}</p>
    <div class="card"><div style="overflow-x:auto"><table><thead><tr><th>Disruption</th><th>What the team bought</th><th class="num">Team spent</th><th class="num">Co-pilot would have skipped</th><th>Why</th></tr></thead><tbody>
      ${wasteRows.map((r) => `<tr><td><b>${esc(r.disruption_id)}</b> ${esc(r.title)}</td><td>${sumBy(r.waste_actions)}</td><td class="num">${inr(r.team_wasted_inr)}</td>
        <td class="num">${inr(r.avoided_waste_inr)}</td><td>${r.avoided_waste_inr >= r.team_wasted_inr - 1 ? "Its estimate showed cover outlasting the delay for every one of these parts."
          : "It skipped the parts it saw as covered; for the rest its own estimate showed a shortage, so it would also have acted."}</td></tr>`).join("")}
      <tr><td><b>Total</b></td><td></td><td class="num"><b>₹${rs.team_wasted_cr} cr</b></td><td class="num"><b>₹${rs.avoided_waste_cr} cr</b></td><td></td></tr></tbody></table></div>
      <p class="muted">Most of this was “pre-buy buffer stock (late)”: ordered after the event began and arriving after the peak (data pack outcome notes).</p></div>

    <h2>Structural moves: <em>fix it before</em> it happens</h2>
    <p class="sub">The brief's stretch goal: dual sourcing and buffer levels from the back-test, with cost and avoided loss. Kept out of the ROI above;
      it is an input to next year's sourcing budget, approved by Head of Supply Chain + Quality. ${aref("A11")}</p>
    <div class="card"><div style="overflow-x:auto"><table><thead><tr><th>Part</th><th class="num">Cover / lead time (d)</th><th>Move</th><th class="num">One-off cost</th><th class="num">Expected loss avoided / yr, net</th></tr></thead><tbody>
      ${moves.map((r) => `<tr><td><b>${esc(r.description)}</b> <span class="pid">${esc(r.part_id)}</span></td><td class="num">${r.cover_days} / ${r.lead_time_days}</td>
        <td>${esc(nameIds(r.recommendation))}</td><td class="num">${/Qualify/.test(r.recommendation) ? inr(r.qualify_cost_once_inr) : "—"}</td><td class="num">${inr(r.net_annual_value_inr)}</td></tr>`).join("")}
      <tr><td><b>Total (${moves.length} moves)</b></td><td></td><td></td><td class="num"><b>₹${ss.one_off_qualification_cost_cr.toFixed(1)} cr</b></td><td class="num"><b>₹${ss.net_annual_value_cr.toFixed(1)} cr</b></td></tr></tbody></table></div>
      <p class="muted">Example: D05, the Penang fire, cost ₹61.4 cr. Qualifying the alternate MOSFET supplier in advance (about ₹15 lakh) would have protected about ₹49.8 cr of it.</p></div>

    <h2>A <em>3-month pilot</em> the COO can approve</h2>
    <div class="card" id="pilot"><table><tbody>
      <tr><td><b>What</b></td><td>The co-pilot on Veltrix's live stock feed and the free public feeds (news, port activity, trade measures), for the two categories with the
        most revenue behind single-source parts: PCBs and semiconductors. Alerts go to the category managers and the Head of Supply Chain.</td></tr>
      <tr><td><b>Cost</b></td><td>The build-and-pilot line above (₹35 lakh one-off, our estimate), plus the risk owner's time for three months.</td></tr>
      <tr><td><b>What we measure</b></td><td>The brief's own metrics on live signals: recall ≥ 80%, alert precision ≥ 60%, warning ≥ 7 days before impact,
        signal to quantified impact &lt; 5 minutes, and mitigation spend on parts that had enough stock (today ₹4.6 cr in two years).</td></tr>
      <tr><td><b>Go / no-go</b></td><td>Go to full roll-out if alert precision ≥ 60% with no more than about 2 inbox alerts a week, and the team says the briefings are
        forwardable without edits. Stop if the team ignores the inbox.</td></tr>
      <tr><td><b>Guardrails</b></td><td>The co-pilot recommends; people decide. It never orders, books freight or contacts suppliers. Supplier data stays out of model training.</td></tr>
      <tr><td><b>Approval</b></td><td>COO, with the CFO for the budget.</td></tr></tbody></table>
      <div class="btns" style="margin-top:12px"><button class="btn secondary" id="printpilot">Print this page</button></div></div>

    <h2 id="assumptions">Assumptions, <em>in one place</em></h2>
    <div class="card"><table><tbody>${Object.entries(ASSUME).map(([k, v]) => `<tr><td class="num"><b>${k}</b></td><td>${esc(v)}</td></tr>`).join("")}</tbody></table>
      <p class="muted">From the data pack: revenue, losses, mitigation actions and their costs, stock cover, lead times, margins, penalties, the 55% lost-sale share.
      From the playbook: the impact method, the ranking rule, the ROI formula, holding cost and qualification cost ranges. Everything else above is labelled as ours.</p></div>
`;
  document.querySelectorAll("[data-rep]").forEach((r) => (r.onclick = () => (location.hash = `#/replay/${r.dataset.rep}`)));
  $("#printpilot").onclick = () => print();
  document.querySelectorAll("[data-aref]").forEach((b) => (b.onclick = () => $("#assumptions").scrollIntoView({ behavior: "smooth" })));
}

/* ---------------- live news feed ---------------- */
const ago = (s) => { if (!s) return ""; const m = Math.round((Date.now() - new Date(s)) / 60000);
  return m < 60 ? `${Math.max(m, 1)} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} days ago`; };
async function viewLive(refresh) {
  $("#app").innerHTML = `${hed("Live news · shared", "Today's news, <em>read for Veltrix</em>.")}
    <p class="sub">Real headlines from the last 3 days (Google News), searched for our ports, lanes, fab clusters and commodities, and run through
    the same pipeline as <a href="#/simulate">Check a headline</a>: triage, Veltrix Co-Pilot extraction, linking to Veltrix's network, impact on today's stock and options.</p>
    <div class="btns"><button class="btn" id="lrefresh">Fetch latest news</button> <span class="muted" id="lstamp"></span></div>
    <div id="lout"><p class="muted">${refresh ? "Fetching and reading the news… (up to 30 s)" : "Loading…"}</p></div>`;
  $("#lrefresh").onclick = () => viewLive(true);
  let r;
  try {
    r = await api(refresh ? "/api/live/refresh" : "/api/live", refresh ? { method: "POST" } : {});
    if (!r.fetched_at && !refresh) return viewLive(true);           // first visit: fetch straight away
  } catch (e) { $("#lout").innerHTML = `<div class="result needs_review">Could not fetch the news: ${esc(e.message.slice(0, 200))}</div>`; return; }
  const c = r.counts;
  $("#lstamp").textContent = r.fetched_at ? `Fetched ${ago(r.fetched_at)}${r.cached && refresh ? " (refreshes at most every " + Math.round(r.cooldown_s / 60) + " min)" : ""}` : "";
  const head = { ignored: "Ignored", needs_review: "Needs review", watch: "Watch log", inbox: "Alert: inbox" };
  const card = (i) => `<div class="result ${esc(i.decision)}">
      <b>${esc(head[i.decision])}</b> · <a href="${esc(/^https?:\/\//.test(i.url) ? i.url : "#/live")}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a>
      <p class="muted" style="margin:4px 0">${esc(i.sources.join(", "))}${i.sources.length > 1 ? ` (${i.sources.length} sources, one story)` : ""} · ${esc(ago(i.published))}
        · score ${i.score} vs ${i.threshold}${i.event_type ? ` · ${esc(i.event_type.replace(/_/g, " "))}` : ""}</p>
      ${i.message ? `<p style="margin:4px 0">${esc(i.message)}</p>` : ""}
      ${i.claude ? `<p class="muted" style="margin:4px 0">Veltrix Co-Pilot: ${i.claude.relevant ? "supply risk to our network" : "not a live risk to our network"} (${esc(i.claude.status.replace(/_/g, " "))}) · ${esc(i.claude.reason)}${i.claude_promoted ? " · flagged what the word list missed" : ""}</p>` : ""}
      ${i.links.length ? `<div>${i.links.map(node).join("")}</div>` : ""}
      ${i.alert ? `<div class="btns" style="margin-top:6px"><a class="btn small" href="#/alert/${encodeURIComponent(i.alert.alert_id)}">Open alert · P${i.alert.priority} · ${esc(i.alert.revenue_at_risk_fmt)} at risk · ${esc(i.alert.owner)}</a></div>` : ""}</div>`;
  const hot = r.items.filter((i) => i.decision !== "ignored");
  /* the AI reader thinks it touches our network, but the decision rule chosen on train data is the word list: shown for a person, not alerted */
  const flagged = r.items.filter((i) => i.decision === "ignored" && i.claude?.relevant);
  const cold = r.items.filter((i) => i.decision === "ignored" && !i.claude?.relevant);
  const fcard = (i) => card({ ...i, decision: "needs_review", message: null }).replace(">Needs review<", ">Veltrix Co-Pilot flagged · not alerted<");
  $("#lout").innerHTML = `<div class="tiles">
      <div class="tile"><b>${r.items.length}</b><span>headlines read (duplicates merged)</span></div>
      <div class="tile"><b>${c.inbox}</b><span>alerts for the inbox</span></div>
      <div class="tile"><b>${c.watch + c.needs_review}</b><span>watch or needs review</span></div>
      <div class="tile"><b>${flagged.length}</b><span>flagged by Veltrix Co-Pilot for a person to check</span></div>
      <div class="tile"><b>${cold.length}</b><span>ignored: not a supply event for our network</span></div></div>
    ${r.errors.length ? `<p class="muted">Source problems: ${esc(r.errors.join("; "))}</p>` : ""}
    ${hot.length ? hot.map(card).join("") : `<div class="result"><b>No alerts right now.</b><p>Every headline was read and none passed the alert rule for our ports, lanes, fab clusters or commodities. That is the normal day: the co-pilot stays quiet rather than spamming the team.</p></div>`}
    ${flagged.length ? `<h3>Veltrix Co-Pilot flagged for a person to check (${flagged.length})</h3>
      <p class="muted" style="margin-top:0">Veltrix Co-Pilot reads these as a possible risk to our network. They are not alerted: the decision rule chosen on the training months uses the word list,
      so this reading advises but does not decide yet. The Head of Supply Chain can open the story and judge.</p>${flagged.map(fcard).join("")}` : ""}
    ${cold.length ? `<details class="card"><summary><b>${cold.length} ignored headlines</b> and why</summary>${cold.map(card).join("")}</details>` : ""}`;
}

/* ---------------- ask bar (every page) ---------------- */
let PENDING = null;                       /* text typed in the masthead ask bar, picked up by the Ask or Check page */
let PENDING_SNIPPET = "";
const takePending = (kind) => { const p = PENDING; if (p && p.kind === kind) { PENDING = null; PENDING_SNIPPET = p.snippet || ""; return p.text; } return null; };
const goPending = (p) => { PENDING = p; const want = p.kind === "q" ? "#/ask" : "#/simulate"; if (location.hash === want) route(); else location.hash = want; };
/* suggestions under the ask bar: the same example questions and test headlines as the Ask and Check pages */
(function askSuggestions() {
  const box = $("#asksug"), inp = $("#askbar").q;
  const render = () => {
    const qs2 = [...new Set([...(typeof PERSONA_ASK !== "undefined" && role() ? PERSONA_ASK[role()] : []), ...ASK_EXAMPLES])];
    box.innerHTML = `<div><h3>Ask a question</h3>${qs2.map((q, i) => `<button type="button" data-sq="${i}">${esc(q)}</button>`).join("")}</div>
      <div><h3>Check a test headline</h3>${EXAMPLES.map((e, i) => `<button type="button" data-sh="${i}"><b>${esc(e[0])}</b> ${esc(e[1])}</button>`).join("")}</div>`;
    box.querySelectorAll("[data-sq]").forEach((b) => (b.onmousedown = (ev) => { ev.preventDefault(); box.hidden = true; inp.blur(); goPending({ kind: "q", text: qs2[+b.dataset.sq] }); }));
    box.querySelectorAll("[data-sh]").forEach((b) => (b.onmousedown = (ev) => { ev.preventDefault(); box.hidden = true; inp.blur(); const e = EXAMPLES[+b.dataset.sh]; goPending({ kind: "h", text: e[1], snippet: e[2] }); }));
  };
  inp.addEventListener("focus", () => { render(); box.hidden = false; });
  inp.addEventListener("input", () => { box.hidden = inp.value.trim().length > 0; });
  inp.addEventListener("blur", () => { box.hidden = true; });
  inp.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { box.hidden = true; inp.blur(); } });
})();
const looksLikeQuestion = (t) => /\?\s*$/.test(t) || /^(what|which|who|whom|when|where|why|how|is|are|was|were|do|does|did|can|could|should|will|would|show|list|compare|tell|give|kya|kaun|kitna)\b/i.test(t);
$("#askbar").onsubmit = (ev) => {
  ev.preventDefault(); const t = ev.target.q.value.trim(); if (!t) return;
  ev.target.q.value = ""; PENDING = { kind: looksLikeQuestion(t) ? "q" : "h", text: t };
  const want = PENDING.kind === "q" ? "#/ask" : "#/simulate";
  if (location.hash === want) route(); else location.hash = want;
};
/* ---------------- role switcher ---------------- */
$("#role").onchange = (ev) => {
  setRole(ev.target.value);
  const r = (location.hash || "#/home").split("/")[1];
  if (!r || ["home", "desk", "p"].includes(r)) { if (location.hash === "#/desk") route(); else location.hash = "#/desk"; }
  else route();
};

/* ---------------- router ---------------- */
const NAVMAP = { desk: "desk", p: "desk", inbox: "alerts", alert: "alerts", live: "live", ask: "ask", simulate: "ask", exposure: "exposure",
  register: "register", replay: "replay", business: "business", backtest: "evidence", evidence: "evidence" };
async function route() {
  const [, r, id] = (location.hash || "#/home").split("/");
  if (r === "p" && PERSONA_VIEWS[id]) setRole(id);
  const sec = !r || r === "home" ? "home" : NAVMAP[r] || "alerts";
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === sec));
  $("#role").value = role();
  try {
    await loadNames();
    if (sec === "home") await viewHome();
    else if (sec === "desk") { const k = role(); if (k) await PERSONA_VIEWS[k](); else await viewHome(); }
    else if (r === "alert" && id) await viewAlert(decodeURIComponent(id));
    else if (r === "register") await viewRegister();
    else if (r === "exposure") await viewExposure();
    else if (r === "simulate") await viewSimulate();
    else if (r === "live") await viewLive(false);
    else if (r === "ask") await viewAsk();
    else if (r === "replay") await viewReplay(id ? decodeURIComponent(id) : "D04");
    else if (sec === "evidence") await viewBacktest();
    else if (r === "business") await viewBusiness();
    else await viewInbox();
    window.scrollTo(0, 0);
  } catch (e) { $("#app").innerHTML = `<div class="result needs_review">Could not load: ${esc(e.message.slice(0, 300))}</div>`; }
}
addEventListener("hashchange", route);
addEventListener("DOMContentLoaded", route);   /* after personas.js has loaded */
