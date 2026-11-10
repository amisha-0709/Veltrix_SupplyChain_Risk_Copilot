/* Veltrix Risk Co-Pilot UI: plain JS, no build step. All text is escaped before it reaches the DOM. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (p, opt) => { const r = await fetch(p, opt); if (!r.ok) throw new Error(`${r.status} ${await r.text()}`); return r.json(); };
const cache = {};
const get = (p) => (cache[p] ??= api(p));
const inr = (v) => { if (v == null) return "—"; const a = Math.abs(v); if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} cr`; if (a >= 1e5) return `₹${(v / 1e5).toFixed(1)} lakh`; return `₹${Math.round(v).toLocaleString("en-IN")}`; };
const date = (s) => s ? new Date(s).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";
const pcls = (p) => p >= 20 ? "p-crit" : p >= 12 ? "p-high" : p >= 6 ? "p-med" : "p-low";
const pill = (p, L, I) => `<span class="pill ${pcls(p)}" title="Priority = likelihood × impact">P${p}${L ? ` <small style="font-weight:400">${L}×${I}</small>` : ""}</span>`;
const toast = (m) => { const t = $("#toast"); t.textContent = m; t.style.display = "block"; clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), 2600); };
const node = (n) => { const [t, name] = n.split(":"); return `<span class="tag" title="${esc(t)}">${esc(name)}</span>`; };

/* theme */
(function theme() {
  let t = null; try { t = localStorage.getItem("theme"); } catch (e) {}
  if (t) document.documentElement.dataset.theme = t;
  $("#theme").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const nx = cur === "dark" ? "light" : "dark"; document.documentElement.dataset.theme = nx;
    try { localStorage.setItem("theme", nx); } catch (e) {}
    route();
  };
})();

/* ---------------- views ---------------- */
async function viewInbox(tab = "inbox") {
  const [meta, alerts] = await Promise.all([get("/api/meta"), api("/api/alerts")]);
  const inbox = alerts.filter((a) => a.inbox), watch = alerts.filter((a) => !a.inbox);
  const bt = meta.backtest;
  const rows = (tab === "inbox" ? inbox : watch).map((a) => `
    <tr class="click" data-id="${esc(a.alert_id)}">
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
    <h1>Alerts</h1>
    <p class="sub">Every external signal that touches Veltrix's suppliers, ports, lanes or commodities becomes one alert per event, quantified with
    the playbook method. Priority ≥ 6 goes to the inbox; the rest is the watch log. Stock position: ${esc(meta.snapshot_date)}.</p>
    <div class="tiles">
      <div class="tile"><b>${meta.counts.inbox}</b><span>alerts needing an owner (priority ≥ 6)</span></div>
      <div class="tile"><b>${(bt.signals.test.recall * 100).toFixed(1)}%</b><span>recall on the test period (target ≥ 80%)</span></div>
      <div class="tile"><b>${Math.round(bt.alerts.test.precision * 100)}%</b><span>alert precision on test (target ≥ 60%)</span></div>
      <div class="tile"><b>${bt.lead.test.median_lead_days.toFixed(1)} d</b><span>median warning before impact (team today: ${bt.lead_all.median_team_lead_days > 0 ? "" : "+"}${-bt.lead_all.median_team_lead_days} d after)</span></div>
    </div>
    <div class="tabs"><button data-t="inbox" class="${tab === "inbox" ? "on" : ""}">Inbox (${inbox.length})</button>
      <button data-t="watch" class="${tab === "watch" ? "on" : ""}">Watch log (${watch.length})</button></div>
    <div class="card"><table><thead><tr><th>Priority</th><th>Alert</th><th>First seen</th><th class="num">Revenue at risk</th>
      <th>Owner</th><th class="num">Sources / signals</th><th class="num">Confidence</th><th>Response</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="8" class="muted">Nothing here.</td></tr>'}</tbody></table></div>
    <p class="muted">Alerts are replayed from two years of signals (Oct 2024 – Sep 2026) and quantified on today's stock. Open an alert for its one-page briefing.</p>`;
  document.querySelectorAll("tr[data-id]").forEach((r) => (r.onclick = () => (location.hash = `#/alert/${r.dataset.id}`)));
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => viewInbox(b.dataset.t)));
}

let BRIEF_CSS = null;
async function briefFrame(a) {
  BRIEF_CSS ??= await (await fetch("/api/brief.css")).text();
  const dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
  const darkCss = dark ? ":root{color-scheme:dark;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--surface:#1a1a19;--page:#1a1a19}.ask{background:#16263b}" : ":root{--page:#ffffff}";
  return `<!doctype html><html><head><meta charset=utf-8><style>${BRIEF_CSS}${darkCss}.sheet{margin:0;max-width:none;border:0;border-radius:10px}body{background:var(--surface)}</style></head><body>${a.brief_html}</body></html>`;
}

async function viewAlert(id, tab = "options") {
  const a = await api(`/api/alerts/${encodeURIComponent(id)}`);
  const dec = await api(`/api/decisions?alert_id=${encodeURIComponent(id)}`).catch(() => []);
  const opts = a.options || [];
  const optRows = opts.map((o) => `<tr><td class="num">${o.rank ?? 1}</td><td>${esc(o.part_id || "")}</td>
    <td title="${esc(o.note || "")}"><b>${esc(o.option)}</b>${o.note ? ' <span class="muted" aria-hidden="true">ⓘ</span>' : ""}</td>
    <td class="num">${o.time_to_effect_days ?? "—"} d</td><td>${o.on_time === false ? "late" : "in time"}</td>
    <td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td><td class="num">${o.roi == null ? "—" : o.roi.toFixed(1) + "×"}</td>
    <td>${esc(o.approver)}</td></tr>`).join("");
  const parts = (a.parts || []).map((p) => `<tr><td>${esc(p.part_id)}</td><td>${esc(p.description)}</td><td>${p.single_source ? "single" : "dual"}</td>
    <td class="num">${p.days_of_cover}</td><td class="num">${p.effective_delay_days}</td><td class="num">${p.shortage_days}</td>
    <td><div class="cov" title="cover vs delay"><i style="width:${Math.min(100, (p.days_of_cover / 70) * 100)}%"></i><b style="left:${Math.min(100, (p.effective_delay_days / 70) * 100)}%"></b></div></td></tr>`).join("");
  const skus = (a.skus || []).filter((s) => s.units_short > 0).map((s) => `<tr><td>${esc(s.sku_id)}</td><td>${esc(s.customer)}</td><td>${esc(s.binding_part)}</td>
    <td class="num">${s.shortage_days}</td><td class="num">${(s.units_short || 0).toLocaleString("en-IN")}</td><td class="num">${inr(s.revenue_at_risk_inr)}</td>
    <td class="num">${inr(s.margin_at_risk_inr)}</td><td class="num">${inr(s.penalty_inr)}</td></tr>`).join("");
  const otif = {}; (a.otif || []).forEach((o) => ((otif[o.customer] ??= []).push(o)));
  const otifRows = Object.entries(otif).map(([c, ws]) => `<tr><td>${esc(c)}</td>${ws.slice(0, 10).map((w) =>
    `<td class="num" style="${w.below_target ? "color:var(--crit);font-weight:600" : ""}" title="week of ${esc(w.week_start)}">${Math.round(w.otif * 100)}%</td>`).join("")}</tr>`).join("");
  const srcs = (a.brief.sources || []).map((s) => `<tr><td>${esc(s.date)}</td><td>${esc(s.source)}</td><td>${esc(s.text)}</td><td class="muted">${esc(s.id)}</td></tr>`).join("");
  const decRows = dec.map((d) => `<tr><td>${esc(d.at)}</td><td>${esc(d.by)}</td><td><b>${esc(d.decision)}</b></td><td>${esc(d.option)}</td><td>${esc(d.note)}</td></tr>`).join("");
  const T = {
    options: `<table><thead><tr><th class="num">#</th><th>Part</th><th>Option</th><th class="num">Effect</th><th>Timing</th><th class="num">Cost</th>
      <th class="num">Net value</th><th class="num">ROI</th><th>Approver</th></tr></thead><tbody>${optRows}</tbody></table>
      <p class="muted">Net value = margin avoided × P(works in time) − cost − penalties anyway (playbook §5). Options are shown for approval, never as approved.</p>`,
    working: `<ol class="steps">${(a.working || []).map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol>
      <h3 style="margin-top:14px">Parts</h3><table><thead><tr><th>Part</th><th>Description</th><th>Sourcing</th><th class="num">Cover (d)</th><th class="num">Delay (d)</th>
      <th class="num">Short (d)</th><th>Cover vs delay</th></tr></thead><tbody>${parts}</tbody></table>
      ${skus ? `<h3 style="margin-top:14px">Products that stop</h3><table><thead><tr><th>SKU</th><th>Customer</th><th>Binding part</th><th class="num">Short (d)</th>
      <th class="num">Units</th><th class="num">Revenue at risk</th><th class="num">Margin</th><th class="num">Penalties</th></tr></thead><tbody>${skus}</tbody></table>` : ""}
      ${otifRows ? `<h3 style="margin-top:14px">Weekly OTIF by customer</h3><table><tbody>${otifRows}</tbody></table>` : ""}`,
    sources: `<table><thead><tr><th>Date</th><th>Source</th><th>Headline</th><th>ID</th></tr></thead><tbody>${srcs}</tbody></table>`,
    decide: `<form class="stack" id="dec">
      <label>Option<select name="option">${opts.map((o) => `<option>${esc((o.part_id ? o.part_id + " · " : "") + o.option)}</option>`).join("")}</select></label>
      <label>Decision<select name="decision"><option>proposed</option><option>approved</option><option>escalated</option><option>rejected</option><option>watching</option><option>dismissed</option></select></label>
      <label>Decided by (role)<input name="by" required placeholder="e.g. Head of Supply Chain" value="${esc(a.owner)}"></label>
      <label>Note<textarea name="note" placeholder="Why, and any conditions"></textarea></label>
      <div class="btns"><button class="btn" type="submit">Record decision</button></div>
      <p class="muted">This only records what a person decided (playbook §8). Nothing is ordered, booked or sent.</p></form>
      ${decRows ? `<h3 style="margin-top:14px">Decision log</h3><table><thead><tr><th>When</th><th>Who</th><th>Decision</th><th>Option</th><th>Note</th></tr></thead><tbody>${decRows}</tbody></table>` : ""}`,
  };
  $("#app").innerHTML = `
    <p><a href="#/inbox">← Alerts</a></p>
    <div class="btns" style="justify-content:space-between;align-items:center">
      <h1 style="margin:0">${pill(a.priority, a.likelihood, a.impact)} ${esc(a.title)}</h1>
      <div class="btns"><a class="btn secondary" href="/api/alerts/${encodeURIComponent(a.alert_id)}/briefing" target="_blank" rel="noopener">Printable briefing</a>
      <button class="btn secondary" id="copy">Copy as email</button></div></div>
    <p class="muted">${esc(a.alert_id)} · ${esc(a.kind)} · first seen ${date(a.first_seen)} · ${a.n_signals} signals from ${a.n_sources} sources
      · quantified in ${a.seconds_to_quantify}s${a.actual_disruptions?.length ? ` · history: ${esc(a.actual_disruptions.join(", "))}` : ""}</p>
    <div class="row">
      <div class="card" style="padding:0"><iframe class="brief" id="brief" title="One-page briefing"></iframe></div>
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
  $("#app").innerHTML = `<h1>Risk register</h1>
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
  $("#app").innerHTML = `<h1>Exposure map</h1>
    <p class="sub">Where one event stops the line. Revenue behind a node = annual revenue of every product that needs a single-source part
    shipped from or through it (a product stops when any one part runs out).</p>
    <div class="tiles"><div class="tile"><b>${h.single_source_cover_below_lead} of ${h.single_source_parts}</b><span>single-source parts with cover below lead time</span></div>
      <div class="tile"><b>${h.east_asia_spend_pct}%</b><span>of ₹${Math.round(h.material_spend_inr_cr)} cr material spend ships from East Asia</span></div>
      <div class="tile"><b>${h.lost_revenue_via_single_source_pct}%</b><span>of past lost revenue came through single-source parts</span></div>
      <div class="tile"><b>${h.single_source_median_cover} vs ${h.single_source_median_lead} d</b><span>median cover vs lead time, single-source parts</span></div></div>
    <div class="row"><div class="card"><h3>By port of loading</h3>${bars(ex.ports, "node", "revenue_behind_single_source_inr_cr", cr)}</div>
      <div class="card"><h3>By commodity</h3>${bars(ex.categories, "node", "revenue_behind_single_source_inr_cr", cr)}</div></div>
    <div class="card"><h3>Single-source parts, most fragile first</h3>
      <div class="legend"><span><span class="sw" style="background:var(--bar)"></span>days of cover</span><span><span class="sw" style="background:var(--ink);width:2px"></span>supplier lead time</span></div>
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
  $("#app").innerHTML = `<h1>Try a signal</h1>
    <p class="sub">Paste a headline and the co-pilot runs the full pipeline live: triage → link to the network → impact on today's stock → ranked options → briefing.
    Typed signals are not stored beyond this session.</p>
    <div class="examples">${EXAMPLES.map((e, i) => `<button data-i="${i}">${esc(e[0])}</button>`).join("")}</div>
    <div class="card"><form class="stack" id="sim">
      <label>Headline<input name="headline" required minlength="5" maxlength="300"></label>
      <label>Snippet (optional)<textarea name="snippet" maxlength="600"></textarea></label>
      <label>Expected duration in days (optional)<input name="duration_days" type="number" min="0" max="365" step="1"></label>
      <div class="btns"><button class="btn" type="submit">Run the co-pilot</button></div></form></div>
    <div id="out"></div>`;
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
      if (r.alert) {
        const a = r.alert;
        html += `<div class="btns" style="margin:8px 0"><a class="btn" href="#/alert/${encodeURIComponent(a.alert_id)}">Open full alert</a></div>
          <div class="card" style="padding:0"><iframe class="brief" id="sbrief" title="Briefing"></iframe></div>`;
      }
      $("#out").innerHTML = html;
      if (r.alert) { const f = $("#sbrief"); f.srcdoc = await briefFrame(r.alert); f.onload = () => { try { f.style.height = f.contentDocument.body.scrollHeight + 20 + "px"; } catch (e) {} }; }
    } catch (e) { $("#out").innerHTML = `<div class="result needs_review">Error: ${esc(e.message.slice(0, 300))}</div>`; }
  };
}

async function viewBacktest() {
  const b = await get("/api/backtest");
  const s = b.signals.test, a = b.alerts.test, l = b.lead.test;
  const m2 = b.m2?.summary;
  $("#app").innerHTML = `<h1>Back-test</h1>
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
      <p class="muted">Full exhibits: <a href="reports/stage1.html" target="_blank" rel="noopener">Stage 1</a> ·
      <a href="reports/m2.html" target="_blank" rel="noopener">Impact engine</a> · <a href="reports/m3.html" target="_blank" rel="noopener">Signal back-test</a> ·
      <a href="reports/acceptance.html" target="_blank" rel="noopener">Acceptance tests T1–T10</a> · <a href="#/replay/D05">D05 replay (T10)</a></p></div>`;
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
function renderChat() {
  $("#log").innerHTML = chat.map((m) => m.role === "user"
    ? `<div class="result" style="border-color:var(--axis)"><b>You</b><p>${esc(m.text)}</p></div>`
    : `<div class="card"><p style="white-space:pre-line;margin-top:0">${esc(m.r.answer)}</p>
        ${(m.r.tables || []).map(tableHtml).join("")}
        ${m.r.working?.length ? `<details><summary class="muted">Working (playbook §3)</summary><ol class="steps">${m.r.working.map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></details>` : ""}
        ${m.r.assumptions?.length ? `<details><summary class="muted">Assumptions</summary><ul>${m.r.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></details>` : ""}</div>`).join("");
}
async function viewAsk() {
  $("#app").innerHTML = `<h1>Ask the co-pilot</h1>
    <p class="sub">Questions are answered by the same impact engine that quantifies alerts: places and commodities are matched to Veltrix's network, and every
    answer shows its working. If a question can't be linked to the network, it asks rather than guesses.</p>
    <div class="examples">${ASK_EXAMPLES.map((e, i) => `<button data-i="${i}">${esc(e)}</button>`).join("")}</div>
    <div id="log"></div>
    <form class="card stack" id="askf"><label>Your question<input name="q" required maxlength="400" placeholder="e.g. Which products stop first if Ningbo closes for three weeks?"></label>
      <div class="btns"><button class="btn" type="submit">Ask</button></div></form>`;
  renderChat();
  const send = async (q) => {
    chat.push({ role: "user", text: q }); renderChat();
    try { const r = await api("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
      chat.push({ role: "bot", r }); } catch (e) { chat.push({ role: "bot", r: { answer: "Error: " + e.message.slice(0, 200) } }); }
    renderChat(); $("#askf").scrollIntoView({ behavior: "smooth", block: "end" });
  };
  document.querySelectorAll(".examples button").forEach((b) => (b.onclick = () => send(ASK_EXAMPLES[+b.dataset.i])));
  $("#askf").onsubmit = (ev) => { ev.preventDefault(); const q = ev.target.q.value.trim(); if (q) { ev.target.q.value = ""; send(q); } };
}

/* ---------------- replay (T10) ---------------- */
async function viewReplay(did = "D05") {
  const [list, r] = await Promise.all([get("/api/replays"), api(`/api/replays/${encodeURIComponent(did)}`)]);
  const s = list.summary;
  const opts = (r.top_options || []).map((o) => `<tr><td>${esc(o.option)}</td><td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td>
    <td>${o.on_time ? "in time" : "late"}</td><td>${esc(o.approver)}</td></tr>`).join("");
  const rec = r.recommended.length ? r.recommended.map((x) => `<li><b>${esc(x.option)}</b> (${esc(x.part_id)}): ${inr(x.cost_inr)}, ${x.time_to_effect_days} d to effect; ${esc(x.approver)}</li>`).join("")
    : "<li>No option clears the playbook's net-value bar (margin protected must exceed cost).</li>";
  const st = r.structural;
  $("#app").innerHTML = `<h1>Replay: what if the co-pilot had been live?</h1>
    <p class="sub">The co-pilot sees only what it would have known that day: its own alert date from the signal back-test, stock cover at the time, and its
    <i>own</i> delay estimate. Its plan is then applied to what actually happened.</p>
    <div class="tiles"><div class="tile"><b>₹${s.revenue_protected_expected_cr} cr</b><span>expected revenue protected across all 18 disruptions (of ₹${s.actual_revenue_lost_cr} cr lost)</span></div>
      <div class="tile"><b>₹${s.plan_cost_cr} cr</b><span>cost of the recommended plans; ROI on plans ${s.roi_on_plans ?? "—"}×</span></div>
      <div class="tile"><b>₹${s.avoided_waste_cr} cr</b><span>of ₹${s.team_wasted_cr} cr wasted spend avoided (cover was enough)</span></div>
      <div class="tile"><b>₹${s.structural_protected_cr} cr</b><span>more if unqualified alternates had been qualified in advance (structural; overlaps with plans)</span></div></div>
    <div class="tabs">${list.rows.map((x) => `<button data-d="${esc(x.disruption_id)}" class="${x.disruption_id === r.disruption_id ? "on" : ""}">${esc(x.disruption_id)}</button>`).join("")}</div>
    <div class="row"><div class="card">
      <h2 style="margin-top:0">${esc(r.disruption_id)} · ${esc(r.title)}</h2>
      <table><tbody>
        <tr><td>Impact started</td><td>${date(r.start_date)}</td></tr>
        <tr><td><b>Co-pilot first alert</b></td><td><b>${r.detected ? date(r.copilot_alert_date) + ` (${r.copilot_lead_days} d before impact)` : "not detected"}</b></td></tr>
        <tr><td>Team first alert</td><td>${date(r.team_alert_date)}</td></tr>
        <tr><td>Team first decision</td><td>day +${r.team_decision_day} after impact</td></tr>
        <tr><td>Co-pilot's delay estimate vs actual</td><td>${r.seen.delay_estimate_days ?? "—"} d vs ${r.actual_delay_days} d</td></tr>
        <tr><td>Revenue at risk it would have shown</td><td>${inr(r.seen.revenue_at_risk_inr)} (${r.seen.skus_stopped} SKUs)</td></tr>
      </tbody></table>
      <h3 style="margin-top:14px">It would have recommended</h3><ul>${rec}</ul>
      <h3>Outcome</h3><table><tbody>
        <tr><td>Actually lost</td><td class="num">${inr(r.actual_revenue_lost_inr)}</td></tr>
        <tr><td>Lost with the co-pilot's plan (if it works)</td><td class="num">${inr(r.with_plan_lost_inr)}</td></tr>
        <tr><td><b>Expected revenue protected</b> (× P works ${r.plan_p_works})</td><td class="num"><b>${inr(r.vs_actual_protected_expected_inr)}</b></td></tr>
        <tr><td>Plan cost</td><td class="num">${inr(r.plan_cost_inr)}</td></tr>
        <tr><td>Margin protected / penalties avoided</td><td class="num">${inr(r.margin_protected_inr)} / ${inr(r.penalties_avoided_inr)}</td></tr>
        <tr><td>Wasted spend it would have skipped</td><td class="num">${inr(r.avoided_waste_inr)} of ${inr(r.team_wasted_inr)}</td></tr>
      </tbody></table>
      ${st ? `<div class="result" style="margin-top:12px"><b>Structural fix the exposure map flags</b><p>${st.parts.map(esc).join("; ")}: about ${inr(st.cost_inr)}.
        Had this been done before the event, a switch would land ~19 days after impact: <b>${inr(st.revenue_protected_inr)}</b> of revenue protected.</p></div>` : ""}
    </div><div class="card"><h3>Options it ranked (on the day)</h3><table><thead><tr><th>Option</th><th class="num">Cost</th><th class="num">Net value</th><th>Timing</th><th>Approver</th></tr></thead>
      <tbody>${opts || '<tr><td colspan="5" class="muted">Cover was enough: no options needed.</td></tr>'}</tbody></table>
      <details><summary class="muted">Working on the day</summary><ol class="steps">${(r.seen.working || []).map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></details>
      <p class="muted">Switches are assumed to take hold in 19 days (observed in history), not the playbook's 5–10. Team actions the co-pilot didn't cover still count.</p></div></div>`;
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => (location.hash = `#/replay/${b.dataset.d}`)));
}

/* ---------------- business case (M6) ---------------- */
async function viewBusiness() {
  const m = await get("/api/business-case");
  const b = m.base, ss = m.structural_summary, base = m.scenarios[0];
  const x = (v) => v == null ? "—" : `${v.toFixed(1)}×`;
  const pc = (v) => v == null ? "—" : `${Math.round(v * 100)}%`;
  const moves = m.structural.filter((r) => r.net_annual_value_inr > 0);
  $("#app").innerHTML = `<h1>Business case</h1>
    <p class="sub">All 18 disruptions replayed as if the co-pilot had been live. Only what it adds over the team's own actions is credited, in margin,
    weighted by the chance each action works, net of what the actions cost; annualised over 2 years.</p>
    <div class="tiles"><div class="tile"><b>${inr(b.net)}</b><span>net benefit per year</span></div>
      <div class="tile"><b>${inr(m.annual_cost_inr)}</b><span>co-pilot running cost per year, including people</span></div>
      <div class="tile"><b>${x(base.roi)}</b><span>ROI; ${x(Math.min(...m.scenarios.map((r) => r.roi)))} in the harshest sensitivity</span></div>
      <div class="tile"><b>₹${ss.net_annual_value_cr.toFixed(1)} cr/yr</b><span>extra from ${ss.parts_with_positive_move} structural moves (not in the ROI)</span></div></div>
    <div class="row"><div class="card"><h3>Benefit per year</h3><table><tbody>
      <tr><td>Margin protected</td><td class="num">${inr(b.margin_protected)}</td></tr>
      <tr><td>Penalties avoided</td><td class="num">${inr(b.penalties_avoided)}</td></tr>
      <tr><td>Spend avoided where cover was enough</td><td class="num">${inr(b.waste_avoided)}</td></tr>
      <tr><td>Less: cost of recommended actions</td><td class="num">−${inr(b.mitigation_cost)}</td></tr>
      <tr><td><b>Net</b></td><td class="num"><b>${inr(b.net)}</b></td></tr></tbody></table></div>
    <div class="card"><h3>Cost per year</h3><table><tbody>${m.cost_rows.map((r) => `<tr><td>${esc(r.item[0].toUpperCase() + r.item.slice(1))}</td><td class="num">${inr(r.annual_inr)}</td></tr>`).join("")}
      <tr><td><b>Total</b></td><td class="num"><b>${inr(m.annual_cost_inr)}</b></td></tr></tbody></table></div></div>
    <div class="card"><h3>Sensitivity</h3><table><thead><tr><th>Scenario</th><th class="num">Net benefit / yr</th><th class="num">Cost / yr</th><th class="num">ROI</th><th class="num">Payback (months)</th></tr></thead>
      <tbody>${m.scenarios.map((r) => `<tr><td>${esc(r.scenario)}</td><td class="num">${inr(r.net_benefit_inr)}</td><td class="num">${inr(r.copilot_cost_inr)}</td><td class="num">${x(r.roi)}</td><td class="num">${r.payback_months ? r.payback_months.toFixed(1) : "—"}</td></tr>`).join("")}</tbody></table></div>
    <div class="card"><h3>Structural moves for single-source parts (${moves.length} pay back)</h3><table><thead><tr><th>Part</th><th>Description</th><th class="num">Cover (d)</th><th>Move</th><th class="num">Net value / yr</th></tr></thead>
      <tbody>${moves.map((r) => `<tr><td>${esc(r.part_id)}</td><td>${esc(r.description)}</td><td class="num">${r.cover_days}</td><td>${esc(r.recommendation)}</td><td class="num">${inr(r.net_annual_value_inr)}</td></tr>`).join("")}</tbody></table>
      <p class="muted">One-off qualification ₹${ss.one_off_qualification_cost_cr.toFixed(1)} cr; extra buffer ${inr(ss.annual_buffer_cost_cr * 1e7)}/yr. An input to next year's sourcing budget, approved by Head of Supply Chain + Quality.</p></div>
    <div class="card"><h3>False alarms: each guard switched off</h3><table><thead><tr><th>Guard removed</th><th class="num">False signals (test)</th><th class="num">False alerts (test)</th><th class="num">Precision (test)</th></tr></thead>
      <tbody>${m.ablations.map((r) => `<tr><td>${esc(r["guard removed"])}</td><td class="num">${r.false_alarm_signals_test}</td><td class="num">${r.false_alerts_test}</td><td class="num">${pc(r.precision_test)}</td></tr>`).join("")}</tbody></table>
      <p class="muted">Load as built: ${m.load.alerts_per_week} alerts a week and ${m.load.inbox_per_month} inbox alerts a month, from ${m.load.signals_per_week} signals a week read.</p></div>
    <p class="muted">Full exhibits: <a href="reports/m6.html" target="_blank" rel="noopener">M6 report</a> ·
      <a href="reports/coo_onepager.html" target="_blank" rel="noopener">COO one-pager</a> (prints on one A4 page)</p>`;
}

/* ---------------- router ---------------- */
async function route() {
  const [, r, id] = (location.hash || "#/inbox").split("/");
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === (r === "alert" ? "inbox" : r)));
  try {
    if (r === "alert" && id) await viewAlert(decodeURIComponent(id));
    else if (r === "register") await viewRegister();
    else if (r === "exposure") await viewExposure();
    else if (r === "simulate") await viewSimulate();
    else if (r === "ask") await viewAsk();
    else if (r === "replay") await viewReplay(id ? decodeURIComponent(id) : "D05");
    else if (r === "backtest") await viewBacktest();
    else if (r === "business") await viewBusiness();
    else await viewInbox();
    window.scrollTo(0, 0);
  } catch (e) { $("#app").innerHTML = `<div class="result needs_review">Could not load: ${esc(e.message.slice(0, 300))}</div>`; }
}
addEventListener("hashchange", route);
route();
