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
      <a href="reports/m2.html" target="_blank" rel="noopener">Impact engine</a> · <a href="reports/m3.html" target="_blank" rel="noopener">Signal back-test</a></p></div>`;
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
    else if (r === "backtest") await viewBacktest();
    else await viewInbox();
    window.scrollTo(0, 0);
  } catch (e) { $("#app").innerHTML = `<div class="result needs_review">Could not load: ${esc(e.message.slice(0, 300))}</div>`; }
}
addEventListener("hashchange", route);
route();
