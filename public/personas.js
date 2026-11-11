/* Persona pages: one simple page per user the brief names (category manager, Head of Supply Chain, COO, sales).
   Read-only views over /api/persona plus the existing decision log, simulate and ask endpoints. Text is always escaped. */
"use strict";

const PERSONAS = [
  { key: "category", name: "Category manager", q: "What threatens my parts, and what can I do?",
    gets: ["Alerts for your category", "Your parts that run out before resupply", "Check any news headline"] },
  { key: "hosc", name: "Head of Supply Chain", q: "What needs my decision?",
    gets: ["Approval queue with impact and options together", "Approve, escalate or reject", "Weekly risk review"] },
  { key: "coo", name: "COO", q: "What is at risk this month?",
    gets: ["Revenue and customers at risk, at a glance", "Top three risks in one line each", "Large mitigations to approve"] },
  { key: "sales", name: "Sales / key-account manager", q: "Which customer deliveries are at risk?",
    gets: ["Products at risk for each customer, and when", "Weeks below the 95% OTIF target", "A draft note to the customer"] },
];
const PERSONA_ASK = {
  category: ["What happens if Penang port shuts for 2 weeks?", "Which parts have no alternate supplier?", "Show me the options for AL-019"],
  hosc: ["Which alerts need a decision today?", "Which supplier should we qualify first?", "Compare a 30-day Kaohsiung closure with a 30-day Shanghai closure"],
  coo: ["Which customers miss their 95% OTIF target if Penang semiconductor output stops for six weeks?", "What is the payback period of this co-pilot?", "What did the Red Sea crisis cost us?"],
  sales: ["Is Ojas Motors exposed to anything right now?", "What's the impact of a 10 day Suez closure on Ojas Motors specifically?", "Which customers are hit if Shanghai port closes for 3 weeks?"],
};
const pget = (k, d) => { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } };
const pset = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

/* Decisions: the server log is per instance on the hosted demo, so this browser also keeps its own copy. */
const localDecisions = () => { try { return JSON.parse(sessionStorage.getItem("decisions") || "[]"); } catch (e) { return []; } };
async function decide(alert_id, decision, by, option, note = "") {
  const d = { alert_id, decision, by, option, note };
  const mine = localDecisions(); mine.push({ ...d, at: new Date().toISOString().slice(0, 19) });
  try { sessionStorage.setItem("decisions", JSON.stringify(mine)); } catch (e) {}
  try { await api("/api/decisions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(d) }); } catch (e) {}
  delete cache["/api/persona"];
  toast(`${decision[0].toUpperCase() + decision.slice(1)} · recorded only, nothing is ordered or sent`);
}
async function personaData() {
  const p = await api("/api/persona");
  const mine = {}; localDecisions().forEach((d) => (mine[d.alert_id] = d));
  p.alerts.forEach((a) => {
    const m = mine[a.alert_id];
    if (m && (!a.last_decision || m.at > a.last_decision.at)) { a.last_decision = m; a.status = `${m.decision} by ${m.by}`; }
  });
  return p;
}
const openStatus = (a) => !a.last_decision || ["proposed", "watching"].includes(a.last_decision.decision);
const optLabel = (o) => `${o.part_id ? o.part_id + " · " : ""}${o.option}`;
const briefLink = (a, txt = "One-page briefing") => `<a href="/api/alerts/${encodeURIComponent(a.alert_id)}/briefing" target="_blank" rel="noopener">${txt}</a>`;
const statusTag = (a) => {
  const d = a.last_decision?.decision;
  const cls = d === "approved" ? "s-good" : d === "rejected" ? "s-muted" : d === "escalated" ? "s-warn" : d === "proposed" ? "s-info" : "";
  return `<span class="status ${cls}">${esc(a.status || "Open")}</span>`;
};

function personaHead(key, extra = "") {
  const p = PERSONAS.find((x) => x.key === key);
  pset("persona", key);
  return `<div class="phead"><div><p class="muted" style="margin:0"><a href="#/home">← Switch role</a></p>
    <h1>${esc(p.name)}</h1><p class="sub" style="margin:0">${esc(p.q)} Impact is worked out on stock as of 30 Sep 2026.</p></div>${extra}</div>`;
}

/* ---------- shared: ask box ---------- */
function askBlock(key) {
  return `<section class="block"><h2>Ask the co-pilot</h2>
    <div class="examples">${PERSONA_ASK[key].map((e, i) => `<button data-pq="${i}">${esc(e)}</button>`).join("")}</div>
    <form class="askrow" id="pask"><input name="q" required maxlength="400" placeholder="Type a question in plain words"><button class="btn" type="submit">Ask</button></form>
    <div id="plog"></div></section>`;
}
function wireAsk(key) {
  const send = async (q) => {
    const log = $("#plog");
    log.innerHTML = `<div class="result"><b>${esc(q)}</b><p class="muted">Working it out…</p></div>`;
    try {
      const r = await api("/api/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
      log.innerHTML = `<div class="result"><b>${esc(q)}</b><p style="white-space:pre-line">${esc(r.answer)}</p>
        ${(r.tables || []).slice(0, 2).map(tableHtml).join("")}
        ${r.working?.length ? `<details><summary class="muted">How this was worked out</summary><ol class="steps">${r.working.map((w) => `<li>${esc(w.replace(/^\d+\.\s*/, ""))}</li>`).join("")}</ol></details>` : ""}</div>`;
    } catch (e) { log.innerHTML = `<div class="result needs_review">Could not answer: ${esc(e.message.slice(0, 200))}</div>`; }
  };
  document.querySelectorAll("[data-pq]").forEach((b) => (b.onclick = () => send(PERSONA_ASK[key][+b.dataset.pq])));
  $("#pask").onsubmit = (ev) => { ev.preventDefault(); const q = ev.target.q.value.trim(); if (q) { ev.target.q.value = ""; send(q); } };
}

/* ---------- home: who are you? ---------- */
async function viewHome() {
  const last = pget("persona", "");
  $("#app").innerHTML = `<div class="hero"><h1>Who is using the co-pilot today?</h1>
    <p class="sub">Pick your role. Each page shows only what that role needs, with plain numbers and one place to ask questions.
    The co-pilot reads outside news and warnings, works out what they mean for Veltrix's parts, products and customers, and recommends what to do.
    People decide.</p></div>
    <div class="pgrid">${PERSONAS.map((p) => `<a class="pcard${p.key === last ? " last" : ""}" href="#/p/${p.key}">
      <span class="pname">${esc(p.name)}${p.key === last ? ' <small class="muted">· last used</small>' : ""}</span>
      <span class="pq">“${esc(p.q)}”</span>
      <ul>${p.gets.map((g) => `<li>${esc(g)}</li>`).join("")}</ul><span class="go">Open →</span></a>`).join("")}</div>
    <p class="muted" style="margin-top:22px">Evaluating the MVP? <a href="#/inbox">All tools</a> has the full alert inbox, risk register,
    exposure map, signal tester, replays, back-test and business case.</p>`;
}

/* ---------- category manager ---------- */
async function viewCategory() {
  const p = await personaData();
  const counts = {}; p.alerts.forEach((a) => (counts[a.category] = (counts[a.category] || 0) + (a.inbox ? 10 : 1)));
  let cat = pget("persona-cat", "");
  if (!p.categories.includes(cat)) cat = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || p.categories[0];
  const sel = `<label class="pick">My category<select id="cat">${p.categories.map((c) => `<option${c === cat ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></label>`;
  const mine = p.alerts.filter((a) => a.category === cat);
  const hot = mine.filter((a) => a.inbox), watch = mine.filter((a) => !a.inbox);
  const parts = p.parts.filter((x) => x.category === cat).sort((a, b) => (a.days_of_cover - a.lead_time_days) - (b.days_of_cover - b.lead_time_days));
  const alertCard = (a) => `<div class="qcard">
    <div class="qtop">${pill(a.priority)} <b>${esc(a.title)}</b> ${statusTag(a)}</div>
    <p class="qline"><b>${esc(a.revenue_at_risk_fmt || "—")}</b> revenue at risk · ${a.customers.length} customer(s) hit · ${briefLink(a)} · <a href="#/alert/${encodeURIComponent(a.alert_id)}">Full detail</a></p>
    ${a.options.length ? `<table><thead><tr><th>Recommended option</th><th class="num">Cost</th><th class="num">Net value</th><th>Takes effect</th><th>Who approves</th><th></th></tr></thead><tbody>
      ${a.options.map((o, i) => `<tr><td>${esc(optLabel(o))}</td><td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td>
        <td>${o.time_to_effect_days ?? "—"} days${o.on_time === false ? " (late)" : ""}</td><td>${esc(o.approver)}</td>
        <td><button class="btn small" data-prop="${esc(a.alert_id)}" data-oi="${i}">Propose</button></td></tr>`).join("")}</tbody></table>`
      : `<p class="muted">No action needed: stock lasts longer than the expected delay.</p>`}</div>`;
  $("#app").innerHTML = personaHead("category", sel) + `
    <section class="block"><h2>Alerts for ${esc(cat)} <span class="muted">(${hot.length} need action${watch.length ? `, ${watch.length} on watch` : ""})</span></h2>
      ${hot.length ? hot.map(alertCard).join("") : `<p class="muted">Nothing needs action in ${esc(cat)} right now.</p>`}
      ${watch.length ? `<details><summary>${watch.length} lower-priority item(s) on watch</summary>${watch.map((a) =>
        `<p class="qline">${pill(a.priority)} ${esc(a.title)} · ${esc(a.revenue_at_risk_fmt || "—")} · <a href="#/alert/${encodeURIComponent(a.alert_id)}">detail</a></p>`).join("")}</details>` : ""}</section>
    <section class="block"><h2>My parts: days of stock vs supplier lead time</h2>
      <p class="muted" style="margin-top:0">A part whose stock runs out before a new order could arrive is exposed if its supplier stops.</p>
      <div style="overflow-x:auto"><table><thead><tr><th>Part</th><th>Supplier</th><th class="num">Days of stock</th><th class="num">Lead time (days)</th><th>Backup supplier</th><th></th></tr></thead><tbody>
      ${parts.map((x) => `<tr><td><b>${esc(x.part_id)}</b> ${esc(x.description)}${x.single_source ? ' <span class="tag">single source</span>' : ""}</td>
        <td>${esc(x.supplier_name)} <span class="muted">(${esc(x.country)})</span></td><td class="num">${x.days_of_cover}</td><td class="num">${x.lead_time_days}</td>
        <td>${x.qualified_alternate_supplier_id ? `ready (${esc(x.qualified_alternate_supplier_id)})` : x.unqualified_alternate_supplier_id ? `needs qualifying (${esc(x.unqualified_alternate_supplier_id)})` : '<span style="color:var(--crit)">none</span>'}</td>
        <td>${x.cover_below_lead_time ? '<span class="status s-warn">runs out first</span>' : '<span class="status s-good">covered</span>'}</td></tr>`).join("")}</tbody></table></div></section>
    <section class="block"><h2>Check a news headline</h2>
      <form class="askrow" id="psim"><input name="headline" required minlength="5" maxlength="300" placeholder="Paste a headline, e.g. Typhoon forecast to close Kaohsiung port for a week"><button class="btn" type="submit">Check</button></form>
      <div id="psimout"></div></section>` + askBlock("category");
  $("#cat").onchange = (e) => { pset("persona-cat", e.target.value); viewCategory(); };
  document.querySelectorAll("[data-prop]").forEach((b) => (b.onclick = async () => {
    const a = p.alerts.find((x) => x.alert_id === b.dataset.prop), o = a.options[+b.dataset.oi];
    await decide(a.alert_id, "proposed", "Category manager", optLabel(o), "Proposed from the category manager page"); viewCategory();
  }));
  $("#psim").onsubmit = async (ev) => {
    ev.preventDefault(); const out = $("#psimout"); out.innerHTML = '<p class="muted">Checking…</p>';
    try {
      const r = await api("/api/simulate", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ headline: ev.target.headline.value.trim() }) });
      const head = { ignored: "Not a risk to Veltrix: logged only", needs_review: "Unclear: sent to a person to review", watch: "Low priority: added to the watch list", inbox: "Alert raised" }[r.decision] || r.decision;
      out.innerHTML = `<div class="result ${esc(r.decision)}"><b>${esc(head)}</b>${r.message ? `<p>${esc(r.message)}</p>` : ""}
        ${r.alert ? `<p><b>${esc(r.alert.revenue_at_risk_fmt || "")}</b> revenue at risk · <a href="#/alert/${encodeURIComponent(r.alert.alert_id)}">Open the alert</a> · ${briefLink(r.alert)}</p>` : ""}</div>`;
    } catch (e) { out.innerHTML = `<div class="result needs_review">Could not check: ${esc(e.message.slice(0, 200))}</div>`; }
  };
  wireAsk("category");
}

/* ---------- Head of Supply Chain ---------- */
async function viewHosc() {
  const p = await personaData();
  const queue = p.alerts.filter((a) => a.inbox && openStatus(a));
  const done = p.alerts.filter((a) => a.inbox && !openStatus(a));
  const proposed = queue.filter((a) => a.last_decision?.decision === "proposed").length;
  const card = (a) => {
    const needsCoo = a.options.some((o) => /COO|CEO/.test(o.approver || ""));
    return `<div class="qcard">
      <div class="qtop">${pill(a.priority)} <b>${esc(a.title)}</b> ${statusTag(a)}</div>
      <p class="qline"><b>${esc(a.revenue_at_risk_fmt || "—")}</b> revenue at risk · customers: ${a.customers.map((c) => esc(c.customer)).join(", ") || "none"} ·
        owner ${esc(a.owner)} · ${briefLink(a)}</p>
      ${a.options.length ? `<table><thead><tr><th>Recommended</th><th class="num">Cost</th><th class="num">Net value</th><th>Approver</th></tr></thead><tbody>
        ${a.options.map((o) => `<tr><td>${esc(optLabel(o))}</td><td class="num">${inr(o.cost_inr)}</td><td class="num">${inr(o.net_value_inr)}</td><td>${esc(o.approver)}</td></tr>`).join("")}</tbody></table>`
        : `<p class="muted">No action recommended: stock covers the delay.</p>`}
      ${needsCoo ? `<p class="muted">One option is above your limit and needs the COO.</p>` : ""}
      <div class="btns"><button class="btn good" data-d="approved" data-a="${esc(a.alert_id)}">Approve</button>
        <button class="btn secondary" data-d="escalated" data-a="${esc(a.alert_id)}">Escalate to COO</button>
        <button class="btn secondary" data-d="rejected" data-a="${esc(a.alert_id)}">Reject</button></div></div>`;
  };
  $("#app").innerHTML = personaHead("hosc") + `
    <div class="tiles"><div class="tile"><b>${queue.length}</b><span>alerts waiting for a decision</span></div>
      <div class="tile"><b>${inr(queue.reduce((s, a) => s + (a.revenue_at_risk || 0), 0))}</b><span>revenue at risk across them</span></div>
      <div class="tile"><b>${proposed}</b><span>proposed by category managers</span></div></div>
    <section class="block"><h2>Approval queue</h2>${queue.length ? queue.map(card).join("") : '<p class="muted">Queue is empty.</p>'}
      ${done.length ? `<details><summary>${done.length} decided</summary>${done.map((a) => `<p class="qline">${esc(a.title)} ${statusTag(a)}</p>`).join("")}</details>` : ""}</section>
    <section class="block"><h2>Weekly risk review</h2><div style="overflow-x:auto"><table><thead><tr><th>Priority</th><th>Risk</th><th>Owner</th><th class="num">At risk</th><th>Status</th></tr></thead><tbody>
      ${p.alerts.slice(0, 8).map((a) => `<tr class="click" data-go="${esc(a.alert_id)}"><td>${pill(a.priority)}</td><td>${esc(a.title)}</td><td>${esc(a.category)}</td>
        <td class="num">${esc(a.revenue_at_risk_fmt || "—")}</td><td>${esc(a.status || "")}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted"><a href="#/register">Full risk register</a></p></section>` + askBlock("hosc");
  document.querySelectorAll("[data-d]").forEach((b) => (b.onclick = async () => {
    const a = p.alerts.find((x) => x.alert_id === b.dataset.a);
    await decide(a.alert_id, b.dataset.d, "Head of Supply Chain", a.options.map(optLabel).join("; ") || "No action"); viewHosc();
  }));
  document.querySelectorAll("[data-go]").forEach((r) => (r.onclick = () => (location.hash = `#/alert/${encodeURIComponent(r.dataset.go)}`)));
  wireAsk("hosc");
}

/* ---------- COO ---------- */
async function viewCoo() {
  const [p, bc] = await Promise.all([personaData(), get("/api/business-case").catch(() => null)]);
  const open = p.alerts.filter((a) => a.inbox && openStatus(a));
  const hot = p.alerts.filter((a) => a.inbox);
  const custs = new Set(); hot.forEach((a) => a.customers.forEach((c) => c.weeks_below > 0 && custs.add(c.customer)));
  const mine = p.alerts.filter((a) => a.last_decision?.decision === "escalated" || (a.inbox && openStatus(a) && a.options.some((o) => /COO|CEO/.test(o.approver || ""))));
  const base = bc?.scenarios?.[0];
  $("#app").innerHTML = personaHead("coo") + `
    <div class="tiles"><div class="tile big"><b>${inr(hot.reduce((s, a) => s + (a.revenue_at_risk || 0), 0))}</b><span>revenue at risk on ${hot.length} high-priority risks</span></div>
      <div class="tile big"><b>${custs.size} of ${p.customers.length}</b><span>customers would fall below 95% on-time delivery</span></div>
      <div class="tile big"><b>${mine.length}</b><span>decision(s) waiting on you</span></div></div>
    <section class="block"><h2>Top risks</h2>${hot.slice(0, 3).map((a) => `<div class="qcard">
      <div class="qtop">${pill(a.priority)} <b>${esc(a.title)}</b> ${statusTag(a)}</div>
      <p class="qline"><b>${esc(a.revenue_at_risk_fmt)}</b> at risk · ${a.customers.length} customer(s): ${a.customers.slice(0, 4).map((c) => esc(c.customer)).join(", ")}${a.customers.length > 4 ? ` +${a.customers.length - 4} more` : ""}</p>
      <p class="qline">${esc((a.ask || "").replace(/^Decide:\s*/, "Recommended: "))}</p><p class="qline">${briefLink(a, "Read the one-page briefing")}</p></div>`).join("")}
      ${hot.length > 3 ? `<p class="muted">${hot.length - 3} more in the <a href="#/p/hosc">Head of Supply Chain queue</a>.</p>` : ""}</section>
    <section class="block"><h2>Needs your approval</h2>${mine.length ? mine.map((a) => `<div class="qcard">
      <div class="qtop">${pill(a.priority)} <b>${esc(a.title)}</b> ${statusTag(a)}</div>
      <p class="qline">${esc(a.revenue_at_risk_fmt)} at risk · ${briefLink(a)}</p>
      <div class="btns"><button class="btn good" data-c="approved" data-a="${esc(a.alert_id)}">Approve</button>
      <button class="btn secondary" data-c="rejected" data-a="${esc(a.alert_id)}">Reject</button></div></div>`).join("")
      : `<p class="muted">Nothing needs you right now: every open proposal is within the Head of Supply Chain's approval limit.</p>`}</section>
    ${base ? `<section class="block"><h2>Is the co-pilot worth it?</h2><p>Replayed over the last two years it would net <b>${inr(base.net_benefit_inr)} a year</b>
      for <b>${inr(base.copilot_cost_inr)}</b> running cost, a <b>${base.roi.toFixed(1)}× return</b>, paying back in under a month.
      <a href="reports/coo_onepager.html" target="_blank" rel="noopener">One-page pilot proposal</a> · <a href="#/business">Full business case</a></p></section>` : ""}` + askBlock("coo");
  document.querySelectorAll("[data-c]").forEach((b) => (b.onclick = async () => {
    const a = p.alerts.find((x) => x.alert_id === b.dataset.a);
    await decide(a.alert_id, b.dataset.c, "COO", a.options.map(optLabel).join("; ") || "No action"); viewCoo();
  }));
  wireAsk("coo");
}

/* ---------- sales / key-account manager ---------- */
async function viewSales() {
  const p = await personaData();
  let cust = pget("persona-cust", "");
  if (!p.customers.includes(cust)) cust = p.customers[0];
  const sel = `<label class="pick">Customer<select id="cust">${p.customers.map((c) => `<option${c === cust ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></label>`;
  const hits = p.alerts.filter((a) => a.inbox).flatMap((a) => a.customers.filter((c) => c.customer === cust).map((c) => ({ a, c })));
  const rows = hits.flatMap(({ a, c }) => c.products.map((x) => ({ a, c, x })));
  const worst = hits.reduce((m, h) => (h.c.worst_otif != null && (m == null || h.c.worst_otif < m) ? h.c.worst_otif : m), null);
  const first = hits.map((h) => h.c.first_week_below).filter(Boolean).sort()[0];
  const prods = [...new Set(rows.map((r) => r.x.sku_name || r.x.sku_id))];
  /* The note covers the customer's biggest single risk: units from separate risks are not added together. */
  const top = hits.slice().sort((p1, p2) => p2.c.revenue_at_risk_inr - p1.c.revenue_at_risk_inr)[0];
  const tprods = top ? top.c.products.map((x) => x.sku_name || x.sku_id) : [];
  const units = top ? top.c.products.reduce((s, x) => s + (x.units_short || 0), 0) : 0;
  const draft = top ? `Dear ${cust} team,

We are tracking a supply risk (${top.a.kind.toLowerCase()}) that may affect deliveries of ${tprods.slice(0, 4).join(", ")}${tprods.length > 4 ? " and other products" : ""}.
Our current estimate is a shortfall of about ${units.toLocaleString("en-IN")} units${top.c.first_week_below ? `, starting around the week of ${date(top.c.first_week_below)}` : ""}.
We are acting on it now and will confirm your allocation and delivery dates within the week.

We will keep you updated as the situation develops.` : "";
  $("#app").innerHTML = personaHead("sales", sel) + `
    <div class="tiles"><div class="tile big"><b>${prods.length}</b><span>${esc(cust)} products at risk</span></div>
      <div class="tile big"><b>${worst == null ? "—" : Math.round(worst * 100) + "%"}</b><span>worst weekly on-time delivery (target 95%)</span></div>
      <div class="tile big"><b>${first ? date(first) : "—"}</b><span>first week below target</span></div></div>
    <section class="block"><h2>Deliveries at risk for ${esc(cust)}</h2>${rows.length ? `<div style="overflow-x:auto"><table><thead><tr><th>Product</th><th>Because of</th>
      <th class="num">Units short</th><th class="num">Runs short from</th><th class="num">Revenue at risk</th></tr></thead><tbody>
      ${rows.sort((a, b) => (b.x.revenue_at_risk_inr || 0) - (a.x.revenue_at_risk_inr || 0)).map(({ a, x }) => `<tr><td><b>${esc(x.sku_name || x.sku_id)}</b> <span class="muted">${esc(x.sku_id)}</span></td>
        <td>${esc(a.title)} <span class="muted">· ${briefLink(a, "briefing")}</span></td><td class="num">${(x.units_short || 0).toLocaleString("en-IN")}</td>
        <td class="num">${x.stops_from_day != null ? `day ${Math.round(x.stops_from_day)}` : "—"}</td><td class="num">${inr(x.revenue_at_risk_inr)}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted">"Runs short from day N" counts from the start of the disruption.</p>` : `<p class="muted">No open risk touches ${esc(cust)}'s deliveries.</p>`}</section>
    ${draft ? `<section class="block"><h2>Draft note to the customer</h2><textarea id="draft" rows="8">${esc(draft)}</textarea>
      <div class="btns" style="margin-top:8px"><button class="btn secondary" id="copyd">Copy</button></div>
      <p class="muted">A draft for you to edit. The co-pilot never contacts customers or suppliers.</p></section>` : ""}` + askBlock("sales");
  $("#cust").onchange = (e) => { pset("persona-cust", e.target.value); viewSales(); };
  const c = $("#copyd"); if (c) c.onclick = async () => { try { await navigator.clipboard.writeText($("#draft").value); toast("Draft copied"); } catch (e) { toast("Copy blocked by the browser"); } };
  wireAsk("sales");
}

const PERSONA_VIEWS = { category: viewCategory, hosc: viewHosc, coo: viewCoo, sales: viewSales };
