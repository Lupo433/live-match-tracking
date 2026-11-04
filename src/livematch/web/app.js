/* Live Match Tracking - vanilla JS client.
 * Receives ~25 msg/s over a WebSocket and renders the pitch on a <canvas>
 * with requestAnimationFrame, interpolating between the last two snapshots. */
(() => {
  "use strict";

  const L = 105, W = 68;                      // pitch size in metres
  const COLORS = {
    home: "#ff4d6d", homeGK: "#ffd166",
    away: "#3ccbf4", awayGK: "#9b5de5",
    line: "rgba(255,255,255,0.78)",
  };
  const KEY_EVENTS = new Set(["SHOT", "CARD", "FAULT RECEIVED", "SET PIECE"]);
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------ state
  const S = {
    ws: null, info: null, players: [], events: [], matches: [],
    prev: null, curr: null, currAt: 0, tickMs: 40,
    trail: [], stats: null, selected: null,
    teamTab: "home", sortKey: "dist", playing: false, speed: 1,
    lastFeedIdx: -1,
  };

  // ------------------------------------------------------------------ canvas
  const canvas = $("pitch");
  const ctx = canvas.getContext("2d");
  let geom = { scale: 10, padX: 30, padY: 30, dpr: 1 };
  let pitchLayer = null;

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth;
    const pad = Math.max(14, cssW * 0.03);
    const scale = (cssW - 2 * pad) / L;
    const cssH = W * scale + 2 * pad;
    canvas.style.height = cssH + "px";
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    geom = { scale, padX: pad, padY: pad, dpr, cssW, cssH };
    pitchLayer = drawPitchLayer();
  }

  const X = (x) => geom.padX + x * geom.scale;
  const Y = (y) => geom.padY + (W - y) * geom.scale;

  function drawPitchLayer() {
    const off = document.createElement("canvas");
    off.width = canvas.width; off.height = canvas.height;
    const c = off.getContext("2d");
    c.scale(geom.dpr, geom.dpr);
    // background & grass stripes
    const g = c.createLinearGradient(0, 0, 0, geom.cssH);
    g.addColorStop(0, "#0f3d2e"); g.addColorStop(1, "#0b3226");
    c.fillStyle = g;
    c.fillRect(0, 0, geom.cssW, geom.cssH);
    const stripes = 14;
    for (let i = 0; i < stripes; i++) {
      if (i % 2) continue;
      c.fillStyle = "rgba(255,255,255,0.025)";
      c.fillRect(X(i * L / stripes), Y(W), (L / stripes) * geom.scale, W * geom.scale);
    }
    c.strokeStyle = COLORS.line;
    c.lineWidth = Math.max(1.2, geom.scale * 0.12);
    const s = geom.scale;
    const rect = (x, y, w, h) => c.strokeRect(X(x), Y(y + h), w * s, h * s);
    const circle = (x, y, r, a0 = 0, a1 = Math.PI * 2) => {
      c.beginPath(); c.arc(X(x), Y(y), r * s, a0, a1); c.stroke();
    };
    const dot = (x, y) => { c.beginPath(); c.arc(X(x), Y(y), Math.max(1.5, s * 0.25), 0, 7); c.fillStyle = COLORS.line; c.fill(); };
    rect(0, 0, L, W);
    c.beginPath(); c.moveTo(X(L / 2), Y(0)); c.lineTo(X(L / 2), Y(W)); c.stroke();
    circle(L / 2, W / 2, 9.15); dot(L / 2, W / 2);
    // penalty & goal areas, spots, arcs, goals
    for (const side of [0, 1]) {
      const x0 = side ? L - 16.5 : 0, xg = side ? L - 5.5 : 0;
      rect(x0, W / 2 - 20.16, 16.5, 40.32);
      rect(xg, W / 2 - 9.16, 5.5, 18.32);
      const px = side ? L - 11 : 11;
      dot(px, W / 2);
      const a = Math.acos(5.5 / 9.15);
      if (side) circle(px, W / 2, 9.15, Math.PI - a, Math.PI + a);
      else circle(px, W / 2, 9.15, -a, a);
      const gx = side ? L : -2;
      c.save(); c.lineWidth *= 1.4; rect(gx, W / 2 - 3.66, 2, 7.32); c.restore();
    }
    // corner arcs
    circle(0, 0, 1, -Math.PI / 2, 0); circle(L, 0, 1, Math.PI, Math.PI * 1.5);
    circle(0, W, 1, 0, Math.PI / 2); circle(L, W, 1, Math.PI / 2, Math.PI);
    // attack direction hint
    c.fillStyle = "rgba(255,255,255,0.25)";
    c.font = `${Math.max(10, s * 1.1)}px Inter, system-ui, sans-serif`;
    c.textAlign = "left";
    c.fillText("HOME →", X(1.5), Y(W) - 6);
    c.textAlign = "right";
    c.fillText("← AWAY", X(L - 1.5), Y(W) - 6);
    return off;
  }

  // ------------------------------------------------------------------ helpers
  const lerp = (a, b, t) => a + (b - a) * t;
  const fmtClock = (secs) => `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(Math.floor(secs % 60)).padStart(2, "0")}`;
  const playerColor = (p) => (p.team === "home" ? (p.gk ? COLORS.homeGK : COLORS.home) : (p.gk ? COLORS.awayGK : COLORS.away));

  function interpolatedPositions() {
    const { prev, curr } = S;
    if (!curr) return null;
    let t = 1;
    if (prev && Math.abs(curr.f - prev.f) < 40) {
      t = Math.min(1, (performance.now() - S.currAt) / S.tickMs);
    }
    const n = S.players.length;
    const out = new Array(n);
    for (let i = 0; i < n; i++) {
      const cx = curr.pl[2 * i], cy = curr.pl[2 * i + 1];
      if (cx === null) { out[i] = null; continue; }
      const px = prev ? prev.pl[2 * i] : null, py = prev ? prev.pl[2 * i + 1] : null;
      out[i] = (px === null || t >= 1) ? [cx, cy] : [lerp(px, cx, t), lerp(py, cy, t)];
    }
    let ball = curr.b;
    if (ball && prev && prev.b && t < 1) ball = [lerp(prev.b[0], ball[0], t), lerp(prev.b[1], ball[1], t)];
    return { pos: out, ball };
  }

  // convex hull (monotone chain) for the team-shape overlay
  function hull(points) {
    const p = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    if (p.length < 3) return p;
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lower = [], upper = [];
    for (const q of p) { while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], q) <= 0) lower.pop(); lower.push(q); }
    for (const q of p.slice().reverse()) { while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], q) <= 0) upper.pop(); upper.push(q); }
    return lower.slice(0, -1).concat(upper.slice(0, -1));
  }

  // ------------------------------------------------------------------ render loop
  function render() {
    requestAnimationFrame(render);
    if (!pitchLayer) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(pitchLayer, 0, 0);
    ctx.setTransform(geom.dpr, 0, 0, geom.dpr, 0, 0);
    const snap = interpolatedPositions();
    if (!snap) return;
    const s = geom.scale;

    if ($("togglePC").checked) drawPitchControl();
    if ($("toggleShape").checked) drawShapes(snap.pos);

    // ball trail
    if ($("toggleTrail").checked && S.trail.length > 1) {
      for (let i = 1; i < S.trail.length; i++) {
        const a = S.trail[i - 1], b = S.trail[i];
        if (!a || !b) continue;
        const alpha = i / S.trail.length;
        ctx.strokeStyle = `rgba(255,255,255,${0.55 * alpha})`;
        ctx.lineWidth = Math.max(1, s * 0.35 * alpha);
        ctx.beginPath(); ctx.moveTo(X(a[0]), Y(a[1])); ctx.lineTo(X(b[0]), Y(b[1])); ctx.stroke();
      }
    }

    // players
    const r = Math.max(7, s * 1.15);
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.font = `700 ${Math.max(8, r * 0.95)}px Inter, system-ui, sans-serif`;
    let owner = -1;
    if (snap.ball) {
      let bd = 2.5;
      snap.pos.forEach((p, i) => { if (!p) return; const d = Math.hypot(p[0] - snap.ball[0], p[1] - snap.ball[1]); if (d < bd) { bd = d; owner = i; } });
    }
    snap.pos.forEach((p, i) => {
      if (!p) return;
      const pl = S.players[i];
      if (i === owner) {
        ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), r + 4, 0, 7);
        ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.lineWidth = 2; ctx.stroke();
      }
      const x = X(p[0]), y = Y(p[1]);
      const sel = S.selected === i;
      ctx.beginPath(); ctx.arc(x, y + r * 0.18, r, 0, 7); ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, r, 0, 7);
      ctx.fillStyle = playerColor(pl); ctx.fill();
      ctx.lineWidth = sel ? 3 : 1.5;
      ctx.strokeStyle = sel ? "#b6f36b" : "rgba(11,15,23,0.85)";
      ctx.stroke();
      if (sel) { ctx.beginPath(); ctx.arc(x, y, r + 5, 0, 7); ctx.strokeStyle = "rgba(182,243,107,0.5)"; ctx.lineWidth = 2; ctx.stroke(); }
      ctx.fillStyle = "#0b0f17";
      ctx.fillText(String(pl.num), x, y + 0.5);
    });

    // ball
    if (snap.ball) {
      const bx = X(snap.ball[0]), by = Y(snap.ball[1]);
      const br = Math.max(4, s * 0.55);
      const glow = ctx.createRadialGradient(bx, by, 0, bx, by, br * 3);
      glow.addColorStop(0, "rgba(255,255,255,0.55)"); glow.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(bx, by, br * 3, 0, 7); ctx.fill();
      ctx.beginPath(); ctx.arc(bx, by, br, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = "#0b0f17"; ctx.stroke();
    }
  }

  function drawShapes(pos) {
    for (const team of ["home", "away"]) {
      const pts = [];
      pos.forEach((p, i) => { if (p && S.players[i].team === team && !S.players[i].gk) pts.push(p); });
      if (pts.length < 3) continue;
      const h = hull(pts);
      ctx.beginPath();
      h.forEach((q, k) => (k ? ctx.lineTo(X(q[0]), Y(q[1])) : ctx.moveTo(X(q[0]), Y(q[1]))));
      ctx.closePath();
      ctx.fillStyle = team === "home" ? "rgba(255,77,109,0.10)" : "rgba(60,203,244,0.10)";
      ctx.strokeStyle = team === "home" ? "rgba(255,77,109,0.45)" : "rgba(60,203,244,0.45)";
      ctx.lineWidth = 1.2; ctx.setLineDash([4, 4]);
      ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
      // defensive line = mean x of the 4 deepest outfield players (same rule as the server)
      const depth = pts.map((q) => (team === "home" ? q[0] : L - q[0])).sort((a, b) => a - b).slice(0, 4);
      const line = depth.reduce((a, b) => a + b, 0) / depth.length;
      const cx = pts.reduce((a, q) => a + q[0], 0) / pts.length, cy = pts.reduce((a, q) => a + q[1], 0) / pts.length;
      {
        const lx = team === "home" ? line : L - line;
        ctx.strokeStyle = team === "home" ? "rgba(255,77,109,0.6)" : "rgba(60,203,244,0.6)";
        ctx.setLineDash([2, 6]); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(X(lx), Y(0)); ctx.lineTo(X(lx), Y(W)); ctx.stroke(); ctx.setLineDash([]);
      }
      {
        // centroid: small cross
        const k = 5;
        ctx.strokeStyle = team === "home" ? COLORS.home : COLORS.away; ctx.lineWidth = 2.5;
        ctx.beginPath(); ctx.moveTo(X(cx) - k, Y(cy) - k); ctx.lineTo(X(cx) + k, Y(cy) + k);
        ctx.moveTo(X(cx) + k, Y(cy) - k); ctx.lineTo(X(cx) - k, Y(cy) + k); ctx.stroke();
      }
    }
  }

  let pcImg = null, pcKey = null;
  function drawPitchControl() {
    const pc = S.stats && S.stats.pc && S.stats.pc.grid;
    if (!pc) return;
    if (pcKey !== pc) {
      pcKey = pc;
      const { nx, ny, v } = pc;
      const off = document.createElement("canvas"); off.width = nx; off.height = ny;
      const c = off.getContext("2d"); const img = c.createImageData(nx, ny);
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        const p = v[j * nx + i] / 100;                       // home control prob
        const k = ((ny - 1 - j) * nx + i) * 4;               // flip y for canvas
        const home = [255, 77, 109], away = [60, 203, 244];
        for (let ch = 0; ch < 3; ch++) img.data[k + ch] = home[ch] * p + away[ch] * (1 - p);
        img.data[k + 3] = 18 + 72 * Math.abs(p - 0.5) * 2;
      }
      c.putImageData(img, 0, 0); pcImg = off;
    }
    ctx.save(); ctx.imageSmoothingEnabled = true; ctx.globalAlpha = 0.9;
    ctx.drawImage(pcImg, X(0), Y(W), L * geom.scale, W * geom.scale);
    ctx.restore();
  }

  // ------------------------------------------------------------------ UI updates
  function onFrame(m) {
    S.prev = S.curr; S.curr = m; S.currAt = performance.now();
    if (S.prev && Math.abs(m.f - S.prev.f) > 40) S.trail = [];
    S.trail.push(m.b);
    if (S.trail.length > 14) S.trail.shift();
    S.playing = m.playing; S.speed = m.speed;
    $("clock").textContent = m.clk;
    $("period").textContent = m.per === 1 ? "1T" : m.per === 2 ? "2T" : `P${m.per}`;
    $("playBtn").textContent = m.playing ? "❚❚" : "▶";
    $("liveDot").classList.toggle("on", m.playing);
    const frac = m.f / Math.max(1, S.info.n_frames - 1);
    $("progress").style.width = `${frac * 100}%`;
    $("head").style.left = `${frac * 100}%`;
    $("timeLabel").textContent = `${fmtClock(m.f / S.info.fps)} / ${fmtClock(S.info.duration_s)}`;
    document.querySelectorAll("#speeds button").forEach((b) => b.classList.toggle("active", Number(b.dataset.speed) === m.speed));
    const syncing = m.sync < 0.995;
    $("syncBadge").hidden = !syncing;
    if (syncing) $("syncPct").textContent = `${Math.round(m.sync * 100)}%`;
    updateScoreAndFeed(m.f);
    if (m.st) { S.stats = m.st; renderStats(); }
  }

  function updateScoreAndFeed(f) {
    let idx = -1;
    for (let i = 0; i < S.events.length && S.events[i].f <= f; i++) idx = i;
    // a goal "happens" when the ball crosses the line (gf), not at the shot frame
    const goalIn = (e) => e.goal && (e.gf ?? e.f) <= f;
    let pendingIn = 0;
    for (let i = Math.max(0, idx - 40); i <= idx; i++) if (S.events[i] && goalIn(S.events[i])) pendingIn++;
    const key = `${idx}:${pendingIn}`;
    if (key === S.lastFeedIdx) return;
    S.lastFeedIdx = key;
    let h = 0, a = 0;
    const feed = [];
    for (let i = 0; i <= idx; i++) {
      const e = S.events[i];
      if (goalIn(e)) { if (e.team === "home") h++; else a++; }
      if (KEY_EVENTS.has(e.type) || e.goal) feed.push(goalIn(e) || !e.goal ? e : { ...e, goal: false, pending: true });
    }
    const scoreTxt = `${h} – ${a}`;
    if (S.lastScore !== undefined && h + a > S.lastScore) {
      const g = feed.filter((e) => e.goal).pop();
      if (g && f - (g.gf ?? g.f) < 10 * S.info.fps) showGoal(g);         // only "live" goals, not seeks
    }
    S.lastScore = h + a;
    $("score").textContent = scoreTxt;
    const sig = (e) => (e ? `${e.f}|${e.type}|${e.goal}` : "");
    const lastKey = (feed.length ? sig(feed[feed.length - 1]) : "") + `#${h + a}`;
    if (lastKey === S.lastKeyEvent) return;                      // key-event list unchanged
    const appended = S.lastKeyEvent && feed.length >= 2 && (sig(feed[feed.length - 2]) + `#${h + a}` === S.lastKeyEvent || feed[feed.length - 1].goal);
    S.lastKeyEvent = lastKey;
    const ul = $("feed");
    ul.innerHTML = "";
    feed.slice(-25).reverse().forEach((e, k) => {
      const li = document.createElement("li");
      li.className = `${e.goal ? "goal" : ""} ${appended && k === 0 ? "new" : ""}`;
      const [ic, label] = eventLabel(e);
      const pl = e.player ? e.player.replace(/^[HA]/, "#") : "";
      li.innerHTML = `<span class="t">${eventClock(e)}</span><span class="ic">${ic}</span><span class="${e.team || ""}">${label}</span><span class="muted">${pl}</span>`;
      ul.appendChild(li);
    });
  }

  // broadcast-style clock of an event (second half starts at 45:00)
  function eventClock(e) {
    const offs = { 1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60 };
    const start = S.info.period_starts[String(e.period)];
    if (start === undefined) return fmtClock(e.t);
    const fr = e.goal && e.gf != null ? e.gf : e.f;
    return fmtClock(offs[e.period] + Math.max(0, (fr - start) / S.info.fps));
  }

  function showGoal(e) {
    if (!e) return;
    const el = $("goalBanner");
    el.className = `goal-banner show ${e.team}`;
    el.querySelector("b").textContent = `GOL ${e.team === "home" ? S.info.home_name : S.info.away_name}`;
    el.querySelector("span").textContent = e.player ? `#${e.player.slice(1)} · ${eventClock(e)}` : eventClock(e);
    clearTimeout(showGoal._t);
    showGoal._t = setTimeout(() => (el.className = "goal-banner"), 3500);
  }

  function eventLabel(e) {
    const sub = (e.sub || "").toUpperCase();
    if (e.goal) return ["⚽", "GOL"];
    if (e.pending) return ["◎", "Tiro in porta…"];
    if (e.type === "SHOT") {
      if (sub.includes("WOODWORK")) return ["◎", "Palo"];
      if (sub.includes("BLOCKED")) return ["◎", "Tiro respinto"];
      if (sub.includes("ON TARGET")) return ["◎", "Tiro parato"];
      return ["◎", "Tiro fuori"];
    }
    if (e.type === "CARD") return [sub.includes("RED") ? "🟥" : "🟨", "Cartellino"];
    if (e.type === "FAULT RECEIVED") return ["✕", "Fallo subito"];
    const sp = { "KICK OFF": "Calcio d'inizio", "THROW IN": "Rimessa laterale", "FREE KICK": "Punizione",
      "CORNER KICK": "Calcio d'angolo", "GOAL KICK": "Rinvio dal fondo", "PENALTY": "Rigore" };
    for (const k in sp) if (sub.includes(k)) return ["↺", sp[k]];
    return ["•", (e.sub || e.type).toLowerCase()];
  }

  function setDual(prefix, home) {
    const h = Math.round(home * 100);
    $(prefix + "Home").style.width = `${h}%`;
    $(prefix + "Away").style.width = `${100 - h}%`;
    $(prefix + "HomeLbl").textContent = `${h}%`;
    $(prefix + "AwayLbl").textContent = `${100 - h}%`;
  }

  function renderStats() {
    const st = S.stats;
    if (st.poss) setDual("poss", st.poss.home);
    if (st.pc) setDual("pc", st.pc.home);
    if (st.teams) {
      const t = st.teams, f1 = (v, d = 1) => (v == null ? "–" : Number(v).toFixed(d));
      const rows = [
        ["Tiri (in porta)", `${t.home.shots} (${t.home.on_target})`, `${t.away.shots} (${t.away.on_target})`],
        ["Passaggi", t.home.passes, t.away.passes],
        ["Distanza (km)", f1(t.home.dist_km, 2), f1(t.away.dist_km, 2)],
        ["Sprint", t.home.sprints, t.away.sprints],
        ["Alta intensità (m)", f1(t.home.hi_m, 0), f1(t.away.hi_m, 0)],
        ["Larghezza (m)", f1(t.home.width), f1(t.away.width)],
        ["Lunghezza (m)", f1(t.home.length), f1(t.away.length)],
        ["Linea difensiva (m)", f1(t.home.line), f1(t.away.line)],
        ["Falli commessi", t.home.fouls, t.away.fouls],
        ["Vel. palla km/h (max)", f1(st.ball ? st.ball.v * 3.6 : null, 0), `(${f1(st.ball ? st.ball.vmax * 3.6 : null, 0)})`],
      ];
      $("teamKpis").innerHTML = rows.map(([k, h, a]) => `<span class="h">${h}</span><span class="k">${k}</span><span class="a">${a}</span>`).join("");
    }
    if (st.players) renderTable();
    if (st.heat && S.selected === st.heat.i) renderHeatmap(st.heat);
  }

  function renderTable() {
    const rows = S.stats.players
      .map((r) => ({ i: r[0], dist: r[1], v: r[2], vmax: r[3], spr: r[4], hi: r[5], on: r[6], p: S.players[r[0]] }))
      .filter((r) => r.p.team === S.teamTab);
    const key = S.sortKey;
    rows.sort((a, b) => (key === "num" ? a.p.num - b.p.num : b[key] - a[key]));
    const maxDist = Math.max(1, ...rows.map((r) => r.dist));
    const tb = $("playersTable").querySelector("tbody");
    tb.innerHTML = rows.map((r) => `
      <tr data-i="${r.i}" class="${r.i === S.selected ? "selected" : ""} ${r.on ? "" : "off"}">
        <td><span class="num-badge" style="background:${playerColor(r.p)}">${r.p.num}</span>${r.p.gk ? "GK" : ""}</td>
        <td class="bar-cell"><div class="bar" style="width:${(r.dist / maxDist) * 100}%"></div><span>${(r.dist / 1000).toFixed(2)}</span></td>
        <td>${(r.v * 3.6).toFixed(0)}</td>
        <td>${(r.vmax * 3.6).toFixed(1)}</td>
        <td>${r.spr}</td>
        <td>${r.hi.toFixed(0)}</td>
      </tr>`).join("");
  }

  function renderHeatmap(h) {
    $("heatCard").hidden = false;
    const p = S.players[h.i];
    $("heatTitle").textContent = `Heatmap · ${p.team === "home" ? "Home" : "Away"} #${p.num}${p.gk ? " (GK)" : ""}`;
    const cv = $("heatmap");
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth || 360, hh = w * (W / L);
    cv.width = w * dpr; cv.height = hh * dpr; cv.style.height = hh + "px";
    const c = cv.getContext("2d"); c.scale(dpr, dpr);
    c.fillStyle = "#0b3226"; c.fillRect(0, 0, w, hh);
    const { nx, ny, v } = h;
    const max = Math.max(1e-9, ...v);
    const cw = w / nx, ch = hh / ny;
    const rgb = p.team === "home" ? [255, 77, 109] : [60, 203, 244];
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const val = v[j * nx + i] / max;
      if (val <= 0) continue;
      const a = Math.pow(val, 0.6);
      c.fillStyle = `rgba(${Math.round(lerp(rgb[0], 255, a * 0.6))},${Math.round(lerp(rgb[1], 230, a * 0.6))},${Math.round(lerp(rgb[2], 120, a * 0.6))},${0.15 + 0.85 * a})`;
      c.fillRect(i * cw, hh - (j + 1) * ch, cw + 0.5, ch + 0.5);
    }
    // minimal lines
    c.strokeStyle = "rgba(255,255,255,0.5)"; c.lineWidth = 1;
    c.strokeRect(0.5, 0.5, w - 1, hh - 1);
    c.beginPath(); c.moveTo(w / 2, 0); c.lineTo(w / 2, hh); c.stroke();
    c.beginPath(); c.arc(w / 2, hh / 2, 9.15 * w / L, 0, 7); c.stroke();
    c.strokeRect(0.5, hh / 2 - 20.16 * w / L, 16.5 * w / L, 40.32 * w / L);
    c.strokeRect(w - 16.5 * w / L - 0.5, hh / 2 - 20.16 * w / L, 16.5 * w / L, 40.32 * w / L);
  }

  function buildTimeline() {
    const box = $("timelineEvents");
    box.innerHTML = "";
    const n = Math.max(1, S.info.n_frames - 1);
    const p2 = S.info.period_starts["2"];
    $("halfMarker").style.left = p2 ? `${(p2 / n) * 100}%` : "-10px";
    for (const e of S.events) {
      if (!(e.type === "SHOT" || e.type === "CARD")) continue;
      const d = document.createElement("div");
      d.className = `tl-ev ${e.team || ""} ${e.goal ? "goal" : ""}`;
      d.style.left = `${(e.f / n) * 100}%`;
      d.title = `${eventClock(e)} ${e.goal ? "GOL" : e.type} ${e.team || ""} ${e.player || ""}`;
      box.appendChild(d);
    }
  }

  function onInit(m) {
    S.info = m.match; S.players = m.players; S.events = m.events; S.matches = m.matches;
    S.prev = S.curr = null; S.trail = []; S.stats = null; S.selected = null; S.lastFeedIdx = -2; S.lastScore = undefined; S.lastKeyEvent = undefined;
    $("loading").hidden = true;
    $("heatCard").hidden = true;
    $("homeName").textContent = m.match.home_name;
    $("awayName").textContent = m.match.away_name;
    const sel = $("matchSelect");
    sel.innerHTML = m.matches.map((x) => `<option value="${x.match_id}" ${x.match_id === m.match.match_id ? "selected" : ""}>${x.title}</option>`).join("");
    $("speeds").innerHTML = m.speeds.map((v) => `<button data-speed="${v}">${v}×</button>`).join("");
    document.title = `Live · ${m.match.title}`;
    buildTimeline();
  }

  // ------------------------------------------------------------------ network
  function send(obj) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj)); }

  function connect(matchId) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const q = matchId ? `?match_id=${encodeURIComponent(matchId)}` : "";
    const ws = new WebSocket(`${proto}://${location.host}/ws${q}`);
    S.ws = ws;
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "frame") onFrame(m);
      else if (m.type === "init") onInit(m);
      else if (m.type === "loading") $("loading").hidden = false;
      else if (m.type === "error") console.warn("server:", m.message);
    };
    ws.onclose = () => {
      $("liveDot").classList.remove("on");
      setTimeout(() => connect(S.info ? S.info.match_id : matchId), 1500);
    };
  }

  // ------------------------------------------------------------------ inputs
  $("playBtn").onclick = () => send({ cmd: S.playing ? "pause" : "play" });
  $("speeds").onclick = (e) => { const b = e.target.closest("button"); if (b) send({ cmd: "set_speed", speed: Number(b.dataset.speed) }); };
  $("timeline").onclick = (e) => {
    const r = $("timeline").getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    send({ cmd: "seek", fraction: frac });
  };
  $("matchSelect").onchange = (e) => { $("loading").hidden = false; send({ cmd: "select_match", match_id: e.target.value }); };
  $("teamTabs").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.teamTab = b.dataset.team;
    document.querySelectorAll("#teamTabs button").forEach((x) => x.classList.toggle("active", x === b));
    if (S.stats) renderTable();
  };
  $("playersTable").querySelector("thead").onclick = (e) => {
    const th = e.target.closest("th"); if (!th) return;
    S.sortKey = th.dataset.sort;
    document.querySelectorAll("#playersTable th").forEach((x) => x.classList.toggle("sorted", x === th));
    if (S.stats) renderTable();
  };
  function selectPlayer(i) {
    S.selected = i;
    send({ cmd: "select_player", player: i });
    if (i !== null && S.players[i]) {
      S.teamTab = S.players[i].team;
      document.querySelectorAll("#teamTabs button").forEach((x) => x.classList.toggle("active", x.dataset.team === S.teamTab));
    } else $("heatCard").hidden = true;
    if (S.stats) renderTable();
  }
  $("playersTable").querySelector("tbody").onclick = (e) => {
    const tr = e.target.closest("tr"); if (tr) selectPlayer(Number(tr.dataset.i));
  };
  $("heatClose").onclick = () => selectPlayer(null);
  canvas.addEventListener("click", (e) => {
    const r = canvas.getBoundingClientRect();
    const mx = (e.clientX - r.left - geom.padX) / geom.scale;
    const my = W - (e.clientY - r.top - geom.padY) / geom.scale;
    const snap = interpolatedPositions(); if (!snap) return;
    let best = null, bd = 3.0;
    snap.pos.forEach((p, i) => { if (!p) return; const d = Math.hypot(p[0] - mx, p[1] - my); if (d < bd) { bd = d; best = i; } });
    selectPlayer(best);
  });
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && e.target === document.body) { e.preventDefault(); send({ cmd: S.playing ? "pause" : "play" }); }
  });
  window.addEventListener("resize", resize);

  resize();
  requestAnimationFrame(render);
  const params = new URLSearchParams(location.search);
  connect(params.get("match"));
})();
