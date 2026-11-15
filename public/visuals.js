/* Visual summaries: the brief's chain (signal → network → impact → options → approver) drawn for one alert, the
   cover-vs-delay picture, plain names for part and supplier ids, and the replay timeline. Plain JS, escaped text only. */
"use strict";
let NAMES = null;
const loadNames = () => NAMES ? Promise.resolve(NAMES)
  : api("/api/names").then((n) => (NAMES = n)).catch(() => (NAMES = { suppliers: {}, parts: {} }));
const supName = (id) => { const s = NAMES?.suppliers?.[id]; return s ? `${s.name} (${s.country})` : id; };
const partName = (id) => NAMES?.parts?.[id]?.name || id || "";
/* "Switch to qualified alternate SUP-005" → "Switch to qualified alternate Yuhe New Semiconductor Corp. (Taiwan)" */
const optText = (o) => String(o.option || "").replace(/SUP-\d+/g, (m) => supName(m));
const niceOpt = (o) => `<b>${esc(optText(o))}</b>${o.part_id ? `<div class="muted">for ${esc(partName(o.part_id))} <span class="pid">${esc(o.part_id)}</span></div>` : ""}`;
const goodOpts = (a) => (a.options || []).filter((o) => o.part_id && o.worth_it !== false && (o.net_value_inr ?? 0) > 0);
const uniq = (xs) => [...new Set(xs.filter(Boolean))];
const linkName = (n) => n.split(":").slice(1).join(":") || n;

function flowStrip(a) {
  const parts = a.parts || [], skus = a.skus || [];
  const hit = skus.filter((s) => s.units_short > 0);
  const custs = uniq(hit.map((s) => s.customer));
  const maxShort = Math.max(0, ...parts.map((p) => p.shortage_days || 0));
  const best = goodOpts(a)[0];
  const atRisk = (a.revenue_at_risk || 0) > 0;
  const step = (n, k, big, small, cls = "") => `<div class="fstep ${cls}"><span class="fk"><i>0${n}</i>${esc(k)}</span><b>${big}</b><span>${small}</span></div>`;
  return `<div class="flow" role="list" aria-label="How the co-pilot got from signal to decision">
    ${step(1, "Signal", `${a.n_signals} signal${a.n_signals === 1 ? "" : "s"} · ${a.n_sources} source${a.n_sources === 1 ? "" : "s"}`,
      `${esc(a.kind)} · ${Math.round((a.confidence || 0) * 100)}% confidence`)}
    ${step(2, "Linked to our network", `${parts.length} part${parts.length === 1 ? "" : "s"} · ${skus.length} product${skus.length === 1 ? "" : "s"}`,
      esc((a.links || []).map(linkName).join(", ")))}
    ${step(3, "Impact", atRisk ? esc(a.revenue_at_risk_fmt) + " at risk" : "Cover holds",
      atRisk ? `short up to ${maxShort.toFixed(0)} days · ${custs.length} customer${custs.length === 1 ? "" : "s"} hit` : "stock outlasts the expected delay",
      atRisk ? "bad" : "ok")}
    ${step(4, "Best option", best ? esc(optText(best)) : "No action: monitor",
      best ? `${esc(partName(best.part_id))} · costs ${inr(best.cost_inr)} · net ${inr(best.net_value_inr)}` : "no spend needed")}
    ${step(5, "Who decides", esc(best ? best.approver : a.owner), `quantified in ${a.seconds_to_quantify ?? "<1"} s · the co-pilot never orders`)}
  </div>`;
}

function traceCols(a) {
  const parts = a.parts || [], skus = a.skus || [];
  const col = (title, items) => {
    const shown = items.slice(0, 6), more = items.length - shown.length;
    return `<div class="tcol"><h4>${esc(title)}</h4>${shown.map(([t, cls, tip]) => `<span class="tnode ${cls || ""}" title="${esc(tip || t)}">${esc(t)}</span>`).join("")}
      ${more > 0 ? `<span class="muted tmore">+${more} more</span>` : ""}</div>`;
  };
  const sups = uniq(parts.map((p) => p.primary_supplier_id));
  const prodShort = {}; skus.forEach((s) => (prodShort[s.sku_name || s.sku_id] = (prodShort[s.sku_name || s.sku_id] || 0) + (s.units_short || 0)));
  const custShort = {}; skus.forEach((s) => (custShort[s.customer] = (custShort[s.customer] || 0) + (s.units_short || 0)));
  const sortHit = (o) => Object.entries(o).sort((x, y) => y[1] - x[1]);
  return `<div class="trace">
    ${col("News names", (a.links || []).map((n) => [linkName(n), "where", n.split(":")[0]]))}
    ${col("Suppliers", sups.map((id) => [supName(id), "", id]))}
    ${col("Parts", parts.map((p) => [`${partName(p.part_id)}${p.single_source ? " · single source" : ""}`, p.shortage_days > 0 ? "hit" : "safe",
      `${p.part_id}: ${p.days_of_cover} d cover vs ${p.effective_delay_days} d delay`]))}
    ${col("Products", sortHit(prodShort).map(([n, u]) => [n, u > 0 ? "hit" : "safe", u > 0 ? `${Math.round(u).toLocaleString("en-IN")} units short` : "no shortage"]))}
    ${col("Customers", sortHit(custShort).map(([n, u]) => [n, u > 0 ? "hit" : "safe", u > 0 ? "deliveries at risk" : "no shortage"]))}
  </div><div class="legend"><span><span class="sw pig"></span>runs short</span><span><span class="sw ink"></span>covered</span></div>`;
}

function coverChart(a) {
  const parts = (a.parts || []).slice().sort((x, y) => (y.shortage_days || 0) - (x.shortage_days || 0)).slice(0, 6);
  if (!parts.length) return "";
  const best = {}; goodOpts(a).forEach((o) => { if (!(o.part_id in best) && o.on_time !== false && o.fixes_shortage) best[o.part_id] = o; });
  const span = Math.max(30, ...parts.map((p) => Math.max(p.days_of_cover, p.effective_delay_days))) * 1.08;
  const pc = (d) => `${Math.min(100, (100 * Math.max(0, d)) / span).toFixed(2)}%`;
  const step = span > 90 ? 30 : 15;
  const ticks = []; for (let d = 0; d <= span; d += step) ticks.push(d);
  const rows = parts.map((p) => {
    const short = p.effective_delay_days > p.days_of_cover, o = best[p.part_id];
    const fix = o && o.effect_day_vs_impact != null ? `<i class="cfix" style="left:${pc(o.effect_day_vs_impact)}" title="Best option takes effect on day ${o.effect_day_vs_impact}"></i>` : "";
    return `<div class="crow"><span class="clab"><b>${esc(partName(p.part_id))}</b><span class="muted">${esc(supName(p.primary_supplier_id))}</span></span>
      <span class="ctrack"><i class="cstock" style="width:${pc(Math.min(p.days_of_cover, span))}" title="Stock lasts ${p.days_of_cover} days"></i>
        ${short ? `<i class="cshort" style="left:${pc(p.days_of_cover)};width:${pc(p.effective_delay_days - p.days_of_cover)}" title="Short for ${p.shortage_days} days"></i>` : ""}
        <i class="cback" style="left:${pc(p.effective_delay_days)}" title="Supply back on day ${p.effective_delay_days}"></i>${fix}</span>
      <span class="cval ${short ? "bad" : "ok"}">${short ? `short ${Math.round(p.shortage_days)} d` : `holds, +${Math.round(p.days_of_cover - p.effective_delay_days)} d spare`}</span></div>`;
  }).join("");
  return `<div class="cchart"><div class="crow cax"><span></span><span class="ctrack axis">${ticks.map((d) => `<em style="left:${pc(d)}">day ${d}</em>`).join("")}</span><span></span></div>${rows}</div>
    <div class="legend"><span><span class="sw hatch"></span>stock lasts</span><span><span class="sw box"></span>line runs short</span>
      <span><span class="sw rule"></span>supply back (expected delay)</span><span><span class="sw mark" style="transform:rotate(45deg)"></span>best option lands</span></div>`;
}

function alertVisual(a) {
  return `${flowStrip(a)}
    <div class="row vis"><div class="card"><h3>Where it hits: news → suppliers → parts → products → customers</h3>${traceCols(a)}</div>
      <div class="card"><h3>Stock runs out vs supply comes back</h3>${coverChart(a)}</div></div>`;
}

/* Replay timeline: when the news was public, when the co-pilot would have alerted, and when the team actually moved. */
function replayTimeline(r) {
  const t0 = new Date(r.start_date).getTime(), day = (s) => s ? Math.round((new Date(s).getTime() - t0) / 864e5) : null;
  const sig = day(r.first_signal_date), cop = r.detected ? day(r.copilot_alert_date) : null, team = day(r.team_alert_date);
  const dec = r.team_decision_day ?? null;
  const vals = [sig, cop, 0, team, dec].filter((v) => v != null);
  const lo = Math.min(...vals) - 4, hi = Math.max(...vals) + 4;
  const pc = (d) => `${((100 * (d - lo)) / (hi - lo)).toFixed(2)}%`;
  const fmtd = (d) => d === 0 ? "impact day" : d < 0 ? `${-d} d before` : `${d} d after`;
  const top = [], bot = [];
  if (sig != null) top.push([sig, "First public news", "sig"]);
  if (cop != null) {
    if (sig != null && Math.abs(cop - sig) <= 2) top[0] = [cop, "News + co-pilot alert", "cop"];
    else top.push([cop, "Co-pilot alert", "cop"]);
  }
  if (team != null) bot.push([team, "Team's first alert", "team"]);
  if (dec != null) bot.push([dec, "Team's first decision", "team"]);
  const mark = ([d, lab, cls], lane) => `<div class="tlm ${cls} ${lane}" style="left:${pc(d)}"><i></i><span><b>${esc(lab)}</b><em>${fmtd(d)}</em></span></div>`;
  const gap = cop != null && cop < 0 ? `<div class="tlgap" style="left:${pc(cop)};width:calc(${pc(0)} - ${pc(cop)})"><span>${-cop} days to act</span></div>` : "";
  return `<div class="card"><h3>Timeline: co-pilot vs what the team did</h3>
    <div class="tl">${top.map((m) => mark(m, "up")).join("")}<div class="tlaxis"></div>${gap}
      <div class="tlm impact" style="left:${pc(0)}"><i></i><span><b>Impact</b><em>${date(r.start_date)}</em></span></div>
      ${bot.map((m) => mark(m, "down")).join("")}</div>
    <p class="muted" style="margin:6px 0 0">${r.detected && cop < 0 ? `The co-pilot would have alerted <b>${-cop} days before impact</b>; the team first moved ${team > 0 ? team + " days after" : "on the day of"} impact and decided on day +${dec}.`
      : "A sudden event: no public warning before impact. The co-pilot's value is quantifying impact and ranking options on day one."}</p></div>`;
}
/* Free text from the engine: swap ids for names ("for PRT-004" → "for Si MOSFET 100V"). */
const nameIds = (t) => String(t || "").replace(/SUP-\d+/g, (m) => supName(m)).replace(/PRT-\d+/g, (m) => partName(m));
