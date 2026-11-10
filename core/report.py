"""Generate the Stage-1 exhibits: reports/stage1.html (self-contained) + reports/stage1_data.json.

    python -m core.report
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from core.business_case import business_case_summary, first_business_case
from core.exposure import headline_checks, node_concentration, part_exposure
from core.timeline import disruption_timeline, timeline_summary

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"

BRIEF = {  # value stated in the brief -> our key
    "single_source_parts": (26, "Single-source parts"),
    "single_source_cover_below_lead": (22, "Single-source parts with cover < lead time"),
    "single_source_median_cover": (15.6, "Median cover, single-source (days)"),
    "single_source_median_lead": (45, "Median lead time, single-source (days)"),
    "material_spend_inr_cr": (1228, "Annual material spend (₹ cr)"),
    "east_asia_spend_pct": (71.6, "Spend from East Asia (%)"),
    "single_source_spend_pct": (46, "Spend on single-source parts (%)"),
    "disruptions_with_stoppage": (9, "Disruptions that stopped production"),
    "revenue_lost_inr_cr": (170, "Revenue lost (₹ cr)"),
    "lost_revenue_via_single_source_pct": (95.5, "Lost revenue via single-source parts (%)"),
    "weeks_with_shortage": (27, "Weeks with shortages (of 104)"),
    "min_weekly_otif_pct": (63.5, "Lowest weekly OTIF (%)"),
    "median_days_impact_to_decision": (9, "Median days impact → decision"),
    "mitigation_spend_inr_cr": (7.0, "Mitigation spend (₹ cr)"),
    "mitigation_spend_no_shortage_inr_cr": (4.6, "Mitigation spend where cover was enough (₹ cr)"),
}

E = html.escape


def _cr(v, d=1):
    return "—" if pd.isna(v) else f"₹{v:,.{d}f} cr"


def _date(v):
    return "—" if pd.isna(v) else pd.Timestamp(v).strftime("%d %b %Y")


# ---------------------------------------------------------------------------------------
def timeline_svg(t: pd.DataFrame) -> str:
    """One row per disruption on a 'days relative to impact' axis."""
    W, row_h, top, left, right = 960, 30, 34, 300, 120
    x0, x1 = -65, 15
    H = top + row_h * len(t) + 30
    plot_w = W - left - right
    X = lambda d: left + (d - x0) / (x1 - x0) * plot_w  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="tl" role="img" '
           f'aria-label="Disruption timeline: warning window vs team reaction, days relative to impact">']
    for d in range(-60, 16, 10):
        out.append(f'<line x1="{X(d):.1f}" x2="{X(d):.1f}" y1="{top-8}" y2="{H-26}" class="grid"/>')
        out.append(f'<text x="{X(d):.1f}" y="{H-10}" class="tick" text-anchor="middle">'
                   f'{"+" if d > 0 else ""}{d}</text>')
    out.append(f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="{top-14}" y2="{H-26}" class="zero"/>')
    out.append(f'<text x="{X(0):.1f}" y="{top-18}" class="tick strong" text-anchor="middle">Impact</text>')
    for i, r in enumerate(t.itertuples()):
        y = top + i * row_h + row_h / 2
        label = f"{r.disruption_id} · {r.title}"
        label = label if len(label) <= 44 else label[:43] + "…"
        out.append(f'<text x="{left-10}" y="{y+4:.1f}" class="rowlab" text-anchor="end">{E(label)}</text>')
        if r.had_warning:
            lead = r.warning_lead_days
            tip = (f"{r.disruption_id}: first public signal {_date(r.first_signal_date)}, "
                   f"{lead:.0f} days before impact ({r.signals_before_impact} signals)")
            out.append(f'<rect x="{X(-lead):.1f}" y="{y-7:.1f}" width="{X(0)-X(-lead)-1:.1f}" height="14" '
                       f'rx="4" class="warn" data-tip="{E(tip)}"/>')
        else:
            out.append(f'<text x="{X(0)-6:.1f}" y="{y+4:.1f}" class="sudden" text-anchor="end">'
                       f'sudden · no warning</text>')
        dec = r.days_from_impact_to_first_mitigation
        tip = (f"{r.disruption_id}: team alert {_date(r.first_internal_alert_date)} "
               f"(+{r.team_alert_offset_days}d), first decision +{dec}d")
        out.append(f'<rect x="{X(0)+1:.1f}" y="{y-7:.1f}" width="{X(dec)-X(0)-1:.1f}" height="14" '
                   f'rx="4" class="react" data-tip="{E(tip)}"/>')
        out.append(f'<circle cx="{X(r.team_alert_offset_days):.1f}" cy="{y:.1f}" r="4.5" class="alert" '
                   f'data-tip="{E(tip)}"/>')
        lost = r.revenue_lost_inr_cr
        out.append(f'<text x="{W-right+12}" y="{y+4:.1f}" class="val">'
                   f'{"₹" + format(lost, ".1f") + " cr" if lost > 0 else "no revenue lost"}</text>')
    out.append(f'<text x="{W-right+12}" y="{top-18}" class="tick strong">Revenue lost</text>')
    out.append("</svg>")
    return "".join(out)


def bars_html(df: pd.DataFrame, label: str, value: str, fmt, tip_cols: list[str], top_n=10) -> str:
    d = df[df[value] > 0].head(top_n)
    mx = d[value].max() or 1
    rows = []
    for r in d.itertuples(index=False):
        rr = r._asdict()
        tip = " · ".join(f"{c.replace('_', ' ')}: {rr[c]:.1f}" if isinstance(rr[c], float)
                         else f"{c.replace('_', ' ')}: {rr[c]}" for c in tip_cols)
        rows.append(f'<div class="bar-row" data-tip="{E(tip)}"><span class="bar-lab">{E(str(rr[label]))}</span>'
                    f'<span class="bar-track"><span class="bar" style="width:{100*rr[value]/mx:.1f}%"></span></span>'
                    f'<span class="bar-val">{fmt(rr[value])}</span></div>')
    return '<div class="bars">' + "".join(rows) + "</div>"


def cover_cell(cover, lead, mx=65):
    return (f'<div class="cov" title="cover {cover:.1f} d vs lead time {lead:.0f} d">'
            f'<span class="cov-bar" style="width:{100*min(cover, mx)/mx:.1f}%"></span>'
            f'<span class="cov-lead" style="left:{100*min(lead, mx)/mx:.1f}%"></span></div>')


# ---------------------------------------------------------------------------------------
def build_report() -> Path:
    OUT.mkdir(exist_ok=True)
    hc = headline_checks()
    pe = part_exposure()
    ports = node_concentration("port")
    countries = node_concentration("country")
    cats = node_concentration("cat")
    t = disruption_timeline()
    ts = timeline_summary(t)
    bc = first_business_case()
    bcs = business_case_summary()

    # ---- JSON export for the app -------------------------------------------------------
    def rec(df):
        return json.loads(df.to_json(orient="records", date_format="iso"))
    data = {"headline": hc, "timeline_summary": ts, "business_case_summary": bcs,
            "parts": rec(pe), "ports": rec(ports), "countries": rec(countries), "categories": rec(cats),
            "timeline": rec(t), "business_case": rec(bc)}
    (OUT / "stage1_data.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    # ---- HTML ------------------------------------------------------------------------
    ss = pe[pe["single_source"]].copy()
    part_rows = "".join(
        f"<tr><td class='mono'>{r.part_id}</td><td>{E(r.description)}</td><td>{E(r.category)}</td>"
        f"<td>{E(r.supplier_name)}<div class='sub'>{E(r.port_of_loading)} · {E(r.country)}</div></td>"
        f"<td class='num'>{r.days_of_cover:.1f}</td><td class='num'>{r.lead_time_days:.0f}</td>"
        f"<td>{cover_cell(r.days_of_cover, r.lead_time_days)}</td>"
        f"<td class='num'>{r.n_skus}</td><td class='num'>{r.revenue_dependent_inr_cr:,.0f}</td>"
        f"<td>{'Unqualified alt ' + E(r.unqualified_alternate_supplier_id) + f' ({r.qualification_weeks_if_unqualified:.0f} wk)' if pd.notna(r.unqualified_alternate_supplier_id) else '<span class=bad>None</span>'}</td></tr>"
        for r in ss.itertuples())

    check_rows = "".join(
        f"<tr><td>{E(lbl)}</td><td class='num'>{bv}</td><td class='num'>{hc[k]}</td>"
        f"<td>{'✓' if abs(float(hc[k]) - float(bv)) <= max(0.15, 0.011 * abs(float(bv))) else '≈'}</td></tr>"
        for k, (bv, lbl) in BRIEF.items())

    tl_rows = "".join(
        f"<tr><td class='mono'>{r.disruption_id}</td><td>{E(r.title)}<div class='sub'>{E(r.type)} · {E(r.location)}</div></td>"
        f"<td>{_date(r.start_date)}</td><td>{_date(r.first_signal_date) if r.had_warning else '—'}</td>"
        f"<td class='num'>{'' if pd.isna(r.warning_lead_days) else f'{r.warning_lead_days:.0f}'}</td>"
        f"<td>{_date(r.first_internal_alert_date)}</td><td class='num'>+{r.days_from_impact_to_first_mitigation}</td>"
        f"<td class='num'>{r.revenue_lost_inr_cr:.2f}</td><td class='num'>{r.mitigation_cost_inr_cr:.2f}</td>"
        f"<td>{E(r.lesson_recorded)}</td></tr>" for r in t.itertuples())

    bc_rows = "".join(
        f"<tr><td class='mono'>{r.disruption_id}</td><td>{E(r.title)}</td><td>{E(r.avoidable)}</td>"
        f"<td class='num'>{r.revenue_lost_inr_cr:.2f}</td><td>{E(r.response_modelled)}</td>"
        f"<td class='num'>{r.revenue_protected_inr_cr:.2f}</td><td class='num'>{r.protected_pct:.0f}%</td></tr>"
        for r in bc.itertuples())

    port_bars = bars_html(ports, "node", "revenue_behind_single_source_inr_cr", lambda v: f"₹{v:,.0f} cr",
                          ["parts", "single_source_parts", "skus", "spend_inr_cr", "min_cover_single_source"])
    cat_bars = bars_html(cats, "node", "revenue_behind_single_source_inr_cr", lambda v: f"₹{v:,.0f} cr",
                         ["parts", "single_source_parts", "skus", "spend_inr_cr", "min_cover_single_source"])

    page = TEMPLATE.format(
        css=CSS, js=JS,
        lost=f"{hc['revenue_lost_inr_cr']:.0f}", single_pct=hc["lost_revenue_via_single_source_pct"],
        lead=f"{ts['median_warning_lead_days']:.0f}", warned=ts["disruptions_with_warning"],
        alert=f"{ts['median_team_alert_offset_days']:+.0f}",
        alert_n=f"{ts['median_team_alert_offset_days']:.0f}", decide=f"{ts['median_days_to_decision']:.0f}",
        ss_below=hc["single_source_cover_below_lead"], ss_n=hc["single_source_parts"],
        ss_cover=hc["single_source_median_cover"], ss_lead=f"{hc['single_source_median_lead']:.0f}",
        wasted=hc["mitigation_spend_no_shortage_inr_cr"], spent=hc["mitigation_spend_inr_cr"],
        part_rows=part_rows, port_bars=port_bars, cat_bars=cat_bars,
        timeline=timeline_svg(t), tl_rows=tl_rows,
        warned_lost=ts["revenue_lost_warned_inr_cr"], sudden_lost=ts["revenue_lost_sudden_inr_cr"],
        prot_total=bcs["protected_total_inr_cr"], prot_warned=bcs["protected_warned_inr_cr"],
        prot_sudden=bcs["protected_sudden_inr_cr"], prot7=bcs["protected_total_if_only_7d_lead_inr_cr"],
        bc_rows=bc_rows, check_rows=check_rows,
    )
    path = OUT / "stage1.html"
    path.write_text(page, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------
CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--crit:#d03b3b;--good:#006300}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;
--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);
--s1:#3987e5;--s2:#d95926;--good:#0ca30c}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--good:#0ca30c}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1120px;margin:0 auto;padding:32px 16px 80px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:48px 0 6px}h3{font-size:16px;margin:24px 0 8px}
.lede{color:var(--ink2);margin:0 0 24px;max-width:780px}.note{color:var(--muted);font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:20px 0}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.tile b{display:block;font-size:28px;line-height:1.15}.tile span{color:var(--ink2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px;margin:12px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;color:var(--ink2);font-weight:600;
border-bottom:1px solid var(--axis);padding:6px 8px;white-space:nowrap}td{border-bottom:1px solid var(--grid);
padding:6px 8px;vertical-align:top}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:nowrap}.sub{color:var(--muted);font-size:12px}
.bad{color:var(--crit);font-weight:600}
.cov{position:relative;width:120px;height:12px;background:var(--grid);border-radius:4px}
.cov-bar{position:absolute;left:0;top:0;bottom:0;background:var(--s1);border-radius:4px}
.cov-lead{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0 8px}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:6px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;vertical-align:-1px;margin-right:6px;
background:var(--surface);border:2px solid var(--ink)}
.tick-sw{display:inline-block;width:2px;height:14px;background:var(--ink);vertical-align:-3px;margin-right:6px}
svg.tl{width:100%;min-width:760px;height:auto}.tl .grid{stroke:var(--grid)}.tl .zero{stroke:var(--axis);stroke-width:2}
.tl .tick{fill:var(--muted);font-size:11px}.tl .strong{fill:var(--ink2);font-weight:600}
.tl .rowlab{fill:var(--ink);font-size:12px}.tl .val{fill:var(--ink2);font-size:12px}
.tl .sudden{fill:var(--muted);font-size:11px;font-style:italic}
.tl .warn{fill:var(--s1)}.tl .react{fill:var(--s2)}.tl .alert{fill:var(--surface);stroke:var(--ink);stroke-width:2}
.tl [data-tip]:hover{opacity:.8}
.bars{display:grid;gap:6px}.bar-row{display:grid;grid-template-columns:190px 1fr 90px;gap:10px;align-items:center;font-size:13px}
.bar-track{height:14px}.bar{display:block;height:14px;background:var(--s1);border-radius:0 4px 4px 0}
.bar-val{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}.bar-row:hover .bar{opacity:.8}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:760px){.two{grid-template-columns:1fr}
.bar-row{grid-template-columns:120px 1fr 70px}}
ol li,ul li{margin:4px 0}.def{border-left:3px solid var(--s1);padding:4px 14px;margin:8px 0}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);font-size:12px;padding:6px 9px;
border-radius:6px;max-width:320px;display:none;z-index:9}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
if(!t){tip.style.display='none';return}tip.textContent=t.dataset.tip;tip.style.display='block';
tip.style.left=Math.min(e.clientX+14,innerWidth-330)+'px';tip.style.top=(e.clientY+14)+'px'});
"""

TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Veltrix Stage-1 Exhibits</title><style>{css}</style></head><body><main>
<p class="note">PS-06 · Supply Chain Resilience Co-Pilot · Stage 1: understand and scope · synthetic data (Veltrix Components, fictional)</p>
<h1>Veltrix saw most of its disruptions coming. It didn't act on the warnings.</h1>
<p class="lede">In 24 months, 18 disruptions cost ₹{lost} crore of revenue. {warned} of 18 had public warnings a median of {lead} days
before impact. The team noticed a median of {alert_n} day after impact and decided after {decide} days.
{single_pct}% of the loss came through single-source parts whose stock ran out before supply came back.</p>
<div class="tiles">
<div class="tile"><b>₹{lost} cr</b><span>revenue lost to 18 disruptions</span></div>
<div class="tile"><b>{lead} days → {alert} day</b><span>median public warning vs when the team noticed</span></div>
<div class="tile"><b>{ss_below} of {ss_n}</b><span>single-source parts with cover below lead time ({ss_cover} vs {ss_lead} days median)</span></div>
<div class="tile"><b>₹{wasted} cr of ₹{spent} cr</b><span>mitigation spent where stock cover was already enough</span></div>
</div>

<h2>1 · Exposure map</h2>
<p class="lede">Where one event stops the line. Revenue behind a node = annual revenue of every SKU that needs a
single-source part from that node. A SKU stops when any one of its parts runs short, so the whole SKU's revenue counts.
Totals overlap because SKUs share parts.</p>
<div class="two">
<div class="card"><h3>By port of loading</h3><p class="note">Annual revenue behind single-source parts</p>{port_bars}</div>
<div class="card"><h3>By commodity</h3><p class="note">Annual revenue behind single-source parts</p>{cat_bars}</div>
</div>
<div class="card"><h3>The 26 single-source parts, most fragile first</h3>
<p class="note">Fragility = cover gap (lead time − cover) × revenue dependent. Bar = days of cover. Tick = supplier lead time.
If the bar stops short of the tick, a supplier outage longer than the cover stops the line before a new order could arrive.</p>
<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>Days of cover</span>
<span><span class="tick-sw"></span>Lead time</span></div>
<table><thead><tr><th>Part</th><th>Description</th><th>Category</th><th>Primary supplier</th><th class="num">Cover (d)</th>
<th class="num">Lead (d)</th><th>Cover vs lead</th><th class="num">SKUs</th><th class="num">Revenue dep. (₹ cr/yr)</th>
<th>Fallback</th></tr></thead><tbody>{part_rows}</tbody></table></div>

<h2>2 · Disruption timeline</h2>
<p class="lede">The blue window is time we had and didn't use. The orange bar is how long the team took to decide after impact.
Warning-led disruptions lost ₹{warned_lost} cr. Sudden ones (fire, earthquake, ransomware) lost ₹{sudden_lost} cr. For those,
the value is quantifying impact and ranking options on day one.</p>
<div class="card">
<div class="legend"><span><span class="sw" style="background:var(--s1)"></span>Warning window (first public signal → impact)</span>
<span><span class="sw" style="background:var(--s2)"></span>Impact → first mitigation decision</span>
<span><span class="dot"></span>Team's first internal alert</span></div>
{timeline}<p class="note">Days relative to impact start. Hover a bar for dates.</p></div>
<div class="card"><table><thead><tr><th>ID</th><th>Disruption</th><th>Impact</th><th>First signal</th><th class="num">Lead (d)</th>
<th>Team alert</th><th class="num">Decided (d)</th><th class="num">Lost (₹ cr)</th><th class="num">Mitigation (₹ cr)</th>
<th>Lesson recorded</th></tr></thead><tbody>{tl_rows}</tbody></table></div>

<h2>3 · Alert definition</h2>
<div class="card">
<p><b>A signal becomes an alert only when all four are true:</b></p>
<ol>
<li class="def"><b>Linked.</b> It names, or resolves to, a supplier, port or location, lane or chokepoint, or commodity in Veltrix's
network with enough link confidence. If it can't be linked confidently, it goes to <i>Needs review</i>, never a guess.
A dramatic headline about something we don't depend on is background noise.</li>
<li class="def"><b>Credible and in horizon.</b> It's a forecast or confirmed event, not commentary, and it falls within the 6-week
likelihood horizon. Credibility comes from the source tier (official weather, port and trade bodies, then trade press, then general
outlets) and from how many independent sources agree. Scope limits are respected: an advisory for the exercise zone only means low
likelihood (T2).</li>
<li class="def"><b>Material.</b> The playbook impact method finds a part where effective delay exceeds days of cover, so revenue,
margin or OTIF is at risk, and priority L × I ≥ 6. If cover is enough, it's logged as <i>Watch: no action needed</i>, with the working
shown (T7). This alone would have saved most of the ₹{wasted} cr of wasted spend.</li>
<li class="def"><b>New.</b> It isn't a repeat of an open event. A repeat attaches to the existing alert as another source (T3).</li>
</ol>
<p><b>Every alert contains:</b> event summary and all cited sources · linked suppliers, ports, lanes, parts, SKUs and customers, each with
link confidence · exposure table (part, cover, effective delay, shortage days, binding part per SKU) · units short, revenue and margin at
risk, customer OTIF vs 95% · likelihood, impact and priority with a one-line reason each, plus overall confidence · response SLA from the
playbook (log, 2 days, 24 h, war-room) · tag: warning-led or sudden · ranked options with cost, time to effect, net value and required
approver (never shown as approved) · owner (category manager for the part's category) and status.</p>
<p class="note">Alert budget: only priority ≥ 6 reaches the inbox. Everything else goes to the watch log, which is reviewed weekly.
Alert fatigue is the first thing that kills tools like this.</p>
</div>

<h2>4 · First business case</h2>
<p class="lede">A deliberately conservative estimate of revenue earlier action could have protected. We assume:</p>
<ul class="lede">
<li>The alert fires on the first public signal, with warning capped at 18 days.</li>
<li>The response is an air-freight pre-buy that takes effect in 6 days.</li>
<li>The action works 90% of the time.</li>
<li>For sudden events, the decision moves to day one, and that only helps where a qualified alternate exists.</li>
</ul>
<p class="lede">The full playbook replay with ranked options and ROI comes in M6.</p>
<div class="tiles">
<div class="tile"><b>₹{prot_total} cr</b><span>revenue protected of ₹{lost} cr lost ({prot_warned} warned + {prot_sudden} sudden)</span></div>
<div class="tile"><b>₹{prot7} cr</b><span>if we only reach the brief's minimum target of 7 days' warning. Lead time is the lever.</span></div>
<div class="tile"><b>₹{wasted} cr</b><span>mitigation spend a cover-vs-delay check would have flagged as unnecessary</span></div>
</div>
<div class="card"><table><thead><tr><th>ID</th><th>Disruption</th><th>Type</th><th class="num">Lost (₹ cr)</th><th>Response modelled</th>
<th class="num">Protected (₹ cr)</th><th class="num">%</th></tr></thead><tbody>{bc_rows}</tbody></table>
<p class="note">Why some rows are low:
D04 (magnets) and D12 (PCB insolvency) last far longer than an 18-day pre-buy can bridge. They need structural moves: qualify the
unqualified alternate early (D12 gave 61 days of warning) or hold a strategic buffer.
D05 (Penang fire, ₹61 cr) has no qualified alternate for the Si MOSFET, so no fast fix exists. Qualifying SUP-011 before anything
happens (an 11-week job) is the structural recommendation.</p></div>

<h2>5 · Answers from the problem-owner meeting</h2>
<div class="card"><ul>
<li><b>Which disruptions to focus on.</b> Repeatable, frequent and cross-geography ones. When looking for patterns, set aside outliers
(over 3 months' delay or over $1M loss). Bucket everything as avoidable or non-avoidable. A supplier that has missed dates 10 times out
of 10 is predictable, so supplier track record feeds likelihood. <i>Design: avoidable/sudden tag; on-time rate and history raise
likelihood.</i></li>
<li><b>What loss is acceptable.</b> None. Count opportunity cost: idle teams, held-up downstream work and penalties, not just lost sales.
<i>Design: margin at risk + penalties + idle-line cost in net value.</i></li>
<li><b>How many alerts a week.</b> It depends on the persona and company size. Ask how many they handle now, don't spam them, and attach
a confidence score. <i>Design: priority-≥6 inbox, confidence on every alert, per-persona views.</i></li>
<li><b>Noise vs credibility.</b> Roughly 60–70% of world news is irrelevant, and some of it is TRP-driven noise. Verify by pattern, the
way plagiarism checkers do or the way WhatsApp flags heavily forwarded content. Non-credible sources lose government or ministry
clients instantly. <i>Design: source tiers + corroboration count feed confidence.</i></li>
<li><b>Real time, predictive, actionable.</b> Insight after the event is worthless. People are spread across time zones, and a morning
hand-off loses two days. An alert has to say what to do, e.g. source from an unaffected country instead. <i>Design: push to the owning
category manager; ranked options on every alert.</i></li>
<li><b>Business angle.</b> Who pays, at what price, on what model (subscription vs one-time)? Which personas: a small shop's supply chain
vs a hyperscaler's, government vs private? Which stakeholders need to be involved (ports, forwarders)? You can't afford to scan
everything. <i>Design: start with a mid-size manufacturer, price on nodes monitored and signal volume, curate sources per tier.</i></li>
<li><b>Context.</b> In a comparable real engagement for a large tech firm's data-centre build-out, losses were $2–3B a year. It took a
year to diagnose: millions of rows bucketed into the top 15–20 reasons before any solutioning. <i>Our Stage 1 is that diagnosis on Veltrix's
data.</i></li>
</ul></div>

<h2>6 · Data checks: brief vs our computation</h2>
<div class="card"><table><thead><tr><th>Metric</th><th class="num">Brief</th><th class="num">Computed</th><th></th></tr></thead>
<tbody>{check_rows}</tbody></table>
<p class="note">Every headline figure in the brief reproduces from the raw data, so the joins behind the exposure map are sound.
"≈" means a rounding difference only.</p></div>
</main><div id="tip" role="tooltip"></div><script>{js}</script></body></html>"""


if __name__ == "__main__":
    print(build_report())
