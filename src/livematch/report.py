"""Self-contained post-match HTML report (one file, inline SVG, works offline).

Usage:
    python -m livematch.report <match_id> [-o report.html]
"""

from __future__ import annotations

import argparse
import html
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from livematch.analytics.geometry import event_start
from livematch.analytics.models import get_models
from livematch.analytics.passes import pass_network
from livematch.metrics.engine import MetricsEngine
from livematch.schema import PITCH_LENGTH as L
from livematch.schema import PITCH_WIDTH as W
from livematch.schema import Team
from livematch.sources.base import DataSource

HOME, AWAY = "#e5384f", "#1f9fd1"
INK, MUTED, LINE = "#0f172a", "#64748b", "#e2e8f0"


def _esc(v: Any) -> str:
    return html.escape(str(v))


def _clock(source: DataSource, frame: int, period: int) -> str:
    start = source.info.period_starts.get(period, 0)
    offset = {1: 0, 2: 45 * 60}.get(period, 0)
    secs = offset + max(0, frame - start) / source.info.fps
    return f"{int(secs // 60):02d}:{int(secs % 60):02d}"


# ---------------------------------------------------------------------- svg helpers
def _pitch(inner: str, width: int = 460) -> str:
    """Pitch in metres; y is flipped so that y = 0 is at the bottom."""
    lines = f"""
    <rect x="0" y="0" width="{L}" height="{W}" fill="#f1f7f2" stroke="#9ab3a2" stroke-width="0.4"/>
    <line x1="{L / 2}" y1="0" x2="{L / 2}" y2="{W}" stroke="#9ab3a2" stroke-width="0.4"/>
    <circle cx="{L / 2}" cy="{W / 2}" r="9.15" fill="none" stroke="#9ab3a2" stroke-width="0.4"/>
    <rect x="0" y="{W / 2 - 20.16}" width="16.5" height="40.32" fill="none" stroke="#9ab3a2"
      stroke-width="0.4"/>
    <rect x="{L - 16.5}" y="{W / 2 - 20.16}" width="16.5" height="40.32" fill="none"
      stroke="#9ab3a2" stroke-width="0.4"/>"""
    return (
        f'<svg viewBox="-1 -1 {L + 2} {W + 2}" width="{width}" '
        f'xmlns="http://www.w3.org/2000/svg">{lines}'
        f'<g transform="translate(0 {W}) scale(1 -1)">{inner}</g></svg>'
    )


def _heatmap_svg(counts: np.ndarray, color: str) -> str:
    ny, nx = counts.shape
    mx = counts.max() or 1.0
    cw, ch = L / nx, W / ny
    cells = []
    for j in range(ny):
        for i in range(nx):
            v = counts[j, i] / mx
            if v > 0.02:
                cells.append(
                    f'<rect x="{i * cw:.2f}" y="{j * ch:.2f}" width="{cw:.2f}" height="{ch:.2f}" '
                    f'fill="{color}" fill-opacity="{0.08 + 0.85 * v**0.7:.2f}"/>'
                )
    return _pitch("".join(cells))


def _network_svg(net: dict[str, Any], color: str, numbers: dict[str, int]) -> str:
    pos = {n["player"]: (n["x"], n["y"], n["n"]) for n in net["nodes"]}
    mx = max([e["count"] for e in net["edges"]] or [1])
    parts = []
    for e in net["edges"]:
        a, b = pos[e["a"]], pos[e["b"]]
        parts.append(
            f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{color}" '
            f'stroke-opacity="0.55" stroke-width="{0.3 + 2.2 * e["count"] / mx:.2f}"/>'
        )
    mxn = max([p[2] for p in pos.values()] or [1])
    for pid, (x, y, n) in pos.items():
        r = 1.2 + 2.0 * (n / mxn) ** 0.5
        parts.append(
            f'<circle cx="{x}" cy="{y}" r="{r:.2f}" fill="{color}" stroke="white" '
            f'stroke-width="0.4"/>'
        )
        parts.append(
            f'<text x="{x}" y="{-y + 0.9}" transform="scale(1 -1)" font-size="2.4" '
            f'text-anchor="middle" fill="white" font-weight="700">{numbers.get(pid, "")}</text>'
        )
    return _pitch("".join(parts))


def _xg_timeline_svg(source: DataSource) -> str:
    models = get_models()
    n = max(1, len(source))
    width, height, pad = 900, 180, 30
    xs = lambda f: pad + (width - 2 * pad) * f / n  # noqa: E731
    series = {"home": [(0, 0.0)], "away": [(0, 0.0)]}
    goals = []
    for e in source.events:
        if e.event_type != "SHOT" or e.team is None or (p := event_start(e)) is None:
            continue
        s = series[e.team.value]
        s.append((e.frame_id, s[-1][1] + models.xg.predict(*p)))
        if e.is_goal:
            goals.append((e.effective_frame, e.team.value))
    top = max(1.0, max(v for s in series.values() for _, v in s) * 1.1)
    ys = lambda v: height - pad - (height - 2 * pad) * v / top  # noqa: E731
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    out.append(
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" '
        f'stroke="{LINE}"/>'
    )
    p2 = source.info.period_starts.get(2)
    if p2:
        out.append(
            f'<line x1="{xs(p2):.1f}" y1="{pad}" x2="{xs(p2):.1f}" y2="{height - pad}" '
            f'stroke="{LINE}" stroke-dasharray="4 4"/>'
        )
    for team, color in (("home", HOME), ("away", AWAY)):
        pts = series[team] + [(n, series[team][-1][1])]
        # step chart: horizontal then vertical
        d = f"M{xs(0):.1f},{ys(0):.1f}"
        prev = 0.0
        for f, v in pts[1:]:
            d += f" L{xs(f):.1f},{ys(prev):.1f} L{xs(f):.1f},{ys(v):.1f}"
            prev = v
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"/>')
        out.append(
            f'<text x="{width - pad + 4}" y="{ys(prev) + 4:.1f}" font-size="12" '
            f'fill="{color}">{prev:.2f}</text>'
        )
    for f, team in goals:
        out.append(f'<text x="{xs(f) - 6:.1f}" y="{pad - 8}" font-size="13">⚽</text>')
        out.append(
            f'<line x1="{xs(f):.1f}" y1="{pad - 4}" x2="{xs(f):.1f}" y2="{height - pad}" '
            f'stroke="{HOME if team == "home" else AWAY}" stroke-opacity="0.35"/>'
        )
    out.append(f'<text x="{pad}" y="{height - 8}" font-size="11" fill="{MUTED}">0\'</text>')
    out.append(
        f'<text x="{width - pad - 20}" y="{height - 8}" font-size="11" fill="{MUTED}">'
        f"fine</text></svg>"
    )
    return "".join(out)


# ---------------------------------------------------------------------- report
def compute_final_engine(source: DataSource, state: Any | None = None) -> MetricsEngine:
    """Engine after the whole match: restored from a checkpoint or computed."""
    engine = MetricsEngine.for_source(source)
    if state is not None:
        engine.restore(state)
    else:
        for f in source.frames():
            engine.update(f)
    return engine


def build_report(source: DataSource, engine: MetricsEngine) -> str:
    snap = engine.snapshot()
    info = source.info
    players = {p.index: p for p in source.players}
    numbers = {p.player_id: p.number for p in source.players}
    t = snap["teams"]
    models = get_models()

    def row(label: str, h: Any, a: Any) -> str:
        return (
            f"<tr><td class=h>{_esc(h)}</td><th>{_esc(label)}</th><td class=a>{_esc(a)}</td></tr>"
        )

    def pct(v: float) -> str:
        return f"{100 * v:.0f}%"

    stats = "".join(
        [
            row("Possesso", pct(snap["poss"]["home"]), pct(snap["poss"]["away"])),
            row("Pitch control", pct(snap["pc"]["home"]), pct(snap["pc"]["away"])),
            row(
                "Tiri (in porta)",
                f"{t['home']['shots']} ({t['home']['on_target']})",
                f"{t['away']['shots']} ({t['away']['on_target']})",
            ),
            row("xG (dimostrativo)", f"{snap['xg']['home']:.2f}", f"{snap['xg']['away']:.2f}"),
            row(
                "xT generato (dimostrativo)",
                f"{snap['xt']['home']:.2f}",
                f"{snap['xt']['away']:.2f}",
            ),
            row("Passaggi", t["home"]["passes"], t["away"]["passes"]),
            row("Distanza (km)", f"{t['home']['dist_km']:.1f}", f"{t['away']['dist_km']:.1f}"),
            row("Sprint", t["home"]["sprints"], t["away"]["sprints"]),
            row("Alta intensità (m)", f"{t['home']['hi_m']:.0f}", f"{t['away']['hi_m']:.0f}"),
            row("Larghezza media (m)", t["home"]["avg_width"], t["away"]["avg_width"]),
            row("Lunghezza media (m)", t["home"]["avg_length"], t["away"]["avg_length"]),
            row("Linea difensiva media (m)", t["home"]["avg_line"], t["away"]["avg_line"]),
            row("Falli commessi", t["home"]["fouls"], t["away"]["fouls"]),
            row("Calci d'angolo", t["home"]["corners"], t["away"]["corners"]),
        ]
    )

    def top(col: int, label: str, fmt: str) -> str:
        rows = sorted(snap["players"], key=lambda r: -r[col])[:5]
        items = "".join(
            f'<li><span class="dot" style="background:{HOME if players[r[0]].team == Team.HOME else AWAY}">'
            f"{players[r[0]].number}</span> {fmt.format(r[col])}</li>"
            for r in rows
        )
        return f"<div class=card><h3>{label}</h3><ol>{items}</ol></div>"

    tops = (
        top(1, "Distanza percorsa", "{:.0f} m")
        + top(3, "Velocità massima", "{:.1f} m/s")
        + top(4, "Sprint", "{} sprint")
        + top(7, "xT generato", "{:.3f}")
    )

    heat = {}
    for team in (Team.HOME, Team.AWAY):
        idx = [p.index for p in source.players if p.team == team and not p.is_goalkeeper]
        heat[team] = engine.heat.counts[idx].sum(axis=0)
    nets = {team: pass_network(source.events, team) for team in (Team.HOME, Team.AWAY)}

    key_events = []
    for e in source.events:
        if e.event_type not in ("SHOT", "CARD") or e.team is None:
            continue
        label = "GOL" if e.is_goal else ("Tiro" if e.event_type == "SHOT" else "Cartellino")
        xg = ""
        if e.event_type == "SHOT" and (p := event_start(e)) is not None:
            xg = f"xG {models.xg.predict(*p):.2f}"
        color = HOME if e.team == Team.HOME else AWAY
        key_events.append(
            f"<tr><td>{_clock(source, e.effective_frame, e.period)}</td>"
            f'<td style="color:{color};font-weight:{700 if e.is_goal else 400}">{label}</td>'
            f"<td>{_esc((e.player_id or '')[1:])}</td><td>{_esc(e.subtype.lower())}</td>"
            f"<td>{xg}</td></tr>"
        )

    score = f"{t['home']['goals']} – {t['away']['goals']}"
    xgm = models.xg
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report · {_esc(info.title)}</title>
<style>
 body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: {INK}; margin: 0;
        background: #f8fafc; }}
 main {{ max-width: 980px; margin: 0 auto; padding: 28px 20px 60px; }}
 header {{ display: flex; justify-content: space-between; align-items: end; border-bottom: 2px solid {INK};
          padding-bottom: 12px; margin-bottom: 18px; }}
 h1 {{ margin: 0; font-size: 26px; }} h2 {{ font-size: 15px; text-transform: uppercase;
       letter-spacing: .12em; color: {MUTED}; margin: 28px 0 10px; }}
 h3 {{ margin: 0 0 8px; font-size: 13px; color: {MUTED}; }}
 .score {{ font-size: 40px; font-weight: 800; }} .score .h {{ color: {HOME}; }} .score .a {{ color: {AWAY}; }}
 .note {{ background: #fff7ed; border: 1px solid #fdba74; padding: 10px 14px; border-radius: 10px;
          font-size: 13px; }}
 table.stats {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
 table.stats th {{ font-weight: 500; color: {MUTED}; font-size: 13px; padding: 5px; }}
 table.stats td {{ width: 30%; padding: 5px; font-weight: 700; }}
 td.h {{ color: {HOME}; }} td.a {{ color: {AWAY}; text-align: right; }}
 table.stats tr + tr {{ border-top: 1px solid {LINE}; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
 .two {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }}
 .card {{ background: white; border: 1px solid {LINE}; border-radius: 12px; padding: 14px; }}
 .card svg {{ width: 100%; height: auto; }}
 ol {{ margin: 0; padding-left: 18px; }} li {{ margin: 4px 0; }}
 .dot {{ display: inline-block; min-width: 20px; height: 20px; line-height: 20px; border-radius: 50%;
        color: white; font-size: 11px; font-weight: 700; text-align: center; }}
 table.ev {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
 table.ev td {{ padding: 4px 6px; border-bottom: 1px solid {LINE}; }}
 footer {{ color: {MUTED}; font-size: 12px; margin-top: 30px; }}
</style></head><body><main>
<header><div><h1>{_esc(info.title)}</h1>
<div style="color:{MUTED}">Report post-partita · {_esc(info.home_name)} vs {_esc(info.away_name)}
 · durata dati {info.duration_s / 60:.0f} min</div></div>
<div class="score"><span class="h">{score.split(" – ")[0]}</span> – <span class="a">{score.split(" – ")[1]}</span></div>
</header>
<p class="note"><b>Modelli dimostrativi.</b> xT e xG sono stimati su 2 sole partite pubbliche
(xG: N = {xgm.n_shots} tiri, {xgm.n_goals} gol; IC 95% bootstrap dei coefficienti — distanza
{xgm.ci95.get("distance_m")}, angolo {xgm.ci95.get("angle_rad")}). Servono a illustrare il metodo, non a valutare giocatori.</p>
<h2>Statistiche di squadra</h2>
<div class="card"><table class="stats">
<tr><td class=h>{_esc(info.home_name)}</td><th></th><td class=a>{_esc(info.away_name)}</td></tr>
{stats}</table></div>
<h2>xG cumulato</h2><div class="card">{_xg_timeline_svg(source)}</div>
<h2>Migliori giocatori</h2><div class="grid">{tops}</div>
<h2>Heatmap di squadra (giocatori di movimento)</h2>
<div class="two"><div class="card"><h3>{_esc(info.home_name)} → attacca verso destra</h3>
{_heatmap_svg(heat[Team.HOME], HOME)}</div>
<div class="card"><h3>{_esc(info.away_name)} ← attacca verso sinistra</h3>
{_heatmap_svg(heat[Team.AWAY], AWAY)}</div></div>
<h2>Rete dei passaggi (posizione media delle azioni, collegamenti con ≥ 3 passaggi)</h2>
<div class="two"><div class="card">{_network_svg(nets[Team.HOME], HOME, numbers)}</div>
<div class="card">{_network_svg(nets[Team.AWAY], AWAY, numbers)}</div></div>
<h2>Eventi chiave</h2><div class="card"><table class="ev">
<tr><th>Min</th><th>Evento</th><th>#</th><th>Dettaglio</th><th></th></tr>{"".join(key_events)}</table></div>
<footer>Generato da Live Match Tracking il {datetime.now():%d/%m/%Y %H:%M}.
Dati: Metrica Sports sample data. File autonomo, funziona offline.</footer>
</main></body></html>"""


def main() -> None:
    from livematch.catalog import default_catalog
    from livematch.session import CheckpointStore

    parser = argparse.ArgumentParser(description="Generate a post-match HTML report")
    parser.add_argument("match_id")
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()
    catalog = default_catalog()
    if args.match_id not in catalog:
        raise SystemExit(
            f"unknown match {args.match_id!r}; available: "
            f"{', '.join(e.match_id for e in catalog.list())}"
        )
    src = catalog.get(args.match_id)
    store = CheckpointStore(src, MetricsEngine.for_source)
    store.run()  # uses the on-disk cache when available
    engine = compute_final_engine(src, store.final_state())
    out = Path(args.output or f"report_{args.match_id}.html")
    out.write_text(build_report(src, engine), encoding="utf-8")
    print(f"report written to {out.resolve()}")


if __name__ == "__main__":
    main()
