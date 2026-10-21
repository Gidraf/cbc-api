/* The whiteboard: a teacher's marker on a white board, timed to the narration.
 *
 * One GSAP timeline holds the whole walkthrough. Every scene is a labelled
 * segment whose length is the narration's (from the voice file when a video
 * is rendered, estimated from the words when it plays live), and every mark
 * — a line written, a number circled, an arc drawn — is a tween inside it.
 * Because the timeline is seekable, the same page plays live in a browser
 * and renders frame by frame on the server: `window.__seek(t)`.
 *
 * Expects: window.WB_DATA = {scenes, durations?, seed, voice} and gsap.
 */
(function () {
  "use strict";
  const W = 1280, H = 720, NS = "http://www.w3.org/2000/svg";
  const FONT = "'Patrick Hand', 'Comic Neue', 'Comic Sans MS', 'Segoe Print', cursive";
  const INK = { black: "#1b1f2a", blue: "#1d4ed8", red: "#c2410c", green: "#15803d", grey: "#6b7280" };
  const data = window.WB_DATA || { scenes: [] };
  const scenes = data.scenes || [];

  // Deterministic wobble: the same item draws the same way every time, so a
  // re-render produces the same video.
  let seed = 0;
  for (const ch of String(data.seed || "wb")) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
  function rnd() { seed = (seed + 0x6d2b79f5) >>> 0; let t = seed; t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }
  const jit = (a) => (rnd() - 0.5) * 2 * a;

  // ── the board ──
  const root = document.getElementById("wb");
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", "100%");
  svg.style.display = "block";
  root.appendChild(svg);
  const defs = el("defs", {}, svg);
  el("rect", { x: 0, y: 0, width: W, height: H, fill: "#fdfdfb" }, svg);
  // A faint frame, as a board has.
  el("rect", { x: 14, y: 14, width: W - 28, height: H - 28, rx: 6, fill: "none", stroke: "#d6d3cb", "stroke-width": 3 }, svg);
  const ink = el("g", {}, svg);
  const hand = buildHand();
  if (data.no_hand) hand.style.display = "none";   // a developer's video: the work speaks, no hand

  function el(tag, attrs, parent) {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    (parent || ink).appendChild(node);
    return node;
  }

  function buildHand() {
    // A teacher's right hand holding a marker, seen from the board's side:
    // the back of the hand, the index finger along the top of the marker,
    // the thumb pinching it from below, the other fingers curled under, and
    // a shirt cuff at the wrist. Two frames: the marker's (tip at 0,0, along
    // +x) for what touches it, and the arm's, turned 18° from it, for the
    // rest — a marker is held steeper than the forearm.
    const g = document.createElementNS(NS, "g");
    const photo = data.hand;
    if (photo && photo.src) {
      // An uploaded photograph of a real hand, its pen's tip on (0,0).
      const k = photo.width / photo.w, w = photo.width, h = photo.h * k;
      g.innerHTML = `<defs><filter id="wbShadow" x="-30%" y="-30%" width="160%" height="160%">
        <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .22 0"/>
        <feGaussianBlur stdDeviation="8"/></filter></defs>
        <g class="tilt">
          <image href="${photo.src}" x="${-photo.tip_x * k + 14}" y="${-photo.tip_y * k + 18}" width="${w}" height="${h}" filter="url(#wbShadow)"/>
          <image href="${photo.src}" x="${-photo.tip_x * k}" y="${-photo.tip_y * k}" width="${w}" height="${h}"/>
        </g>`;
      g._tilt = g.querySelector(".tilt");
      g._photo = true;
      // The emoji writes on a desk, its hand above the line; turned, it
      // reaches up from below as a hand at a board does, and covers nothing
      // already written.
      g._turn = photo.emoji ? 80 : 0;
      svg.appendChild(g);
      return g;
    }
    g.innerHTML = `<defs>
      <linearGradient id="wbSkin" gradientUnits="userSpaceOnUse" x1="118" y1="0" x2="342" y2="0">
        <stop offset="0" stop-color="#4f2d1f"/><stop offset=".32" stop-color="#7a4a33"/>
        <stop offset=".68" stop-color="#6a3f2a"/><stop offset="1" stop-color="#3b2117"/></linearGradient>
      <linearGradient id="wbIndex" gradientUnits="userSpaceOnUse" x1="0" y1="84" x2="0" y2="154">
        <stop offset="0" stop-color="#8d5b41"/><stop offset=".55" stop-color="#704430"/><stop offset="1" stop-color="#4c2b1d"/></linearGradient>
      <linearGradient id="wbThumb" gradientUnits="userSpaceOnUse" x1="120" y1="0" x2="164" y2="0">
        <stop offset="0" stop-color="#4a2a1c"/><stop offset=".6" stop-color="#6c412c"/><stop offset="1" stop-color="#5a3423"/></linearGradient>
      <radialGradient id="wbSheen" gradientUnits="userSpaceOnUse" cx="230" cy="150" r="120">
        <stop offset="0" stop-color="#ffd8bf" stop-opacity=".2"/><stop offset="1" stop-color="#ffd8bf" stop-opacity="0"/></radialGradient>
      <linearGradient id="wbPen" gradientUnits="userSpaceOnUse" x1="0" y1="-8" x2="0" y2="8">
        <stop offset="0" stop-color="#6b7280"/><stop offset=".35" stop-color="#1f2430"/><stop offset="1" stop-color="#07090e"/></linearGradient>
      <linearGradient id="wbChrome" gradientUnits="userSpaceOnUse" x1="0" y1="-8" x2="0" y2="8">
        <stop offset="0" stop-color="#f1f5f9"/><stop offset=".5" stop-color="#94a3b8"/><stop offset="1" stop-color="#475569"/></linearGradient>
      <filter id="wbShadow" x="-30%" y="-30%" width="160%" height="160%">
        <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .22 0"/>
        <feGaussianBlur stdDeviation="8"/></filter>
    </defs>
    <g class="tilt"><g transform="scale(.85) translate(-130,-95)">
      <use href="#wbHandBody" transform="translate(16,20)" filter="url(#wbShadow)"/>
      <g id="wbHandBody">
        <!-- the fist, the wrist and the forearm, in one outline -->
        <path d="M136,104 C132,96 140,90 152,89 C178,86 206,80 234,80 C262,82 290,100 308,126 C322,146 326,176 320,206
                 C316,240 312,280 316,320 C326,420 350,700 380,1500 L180,1500 C210,700 214,420 196,330
                 C178,292 156,252 140,214 C128,186 120,158 126,136 C128,124 132,112 136,104 Z" fill="url(#wbSkin)"/>
        <path d="M136,104 C132,96 140,90 152,89 C178,86 206,80 234,80 C262,82 290,100 308,126 C322,146 326,176 320,206
                 C316,240 312,280 316,320 L196,330 C178,292 156,252 140,214 C128,186 120,158 126,136 Z" fill="url(#wbSheen)"/>
        <!-- knuckles of the curled fingers down the right edge, the palm's crease, the wrist -->
        <path d="M304,146 c-7,10 -9,22 -5,34 M314,190 c-6,10 -7,22 -3,32 M312,234 c-5,9 -6,19 -3,28" fill="none" stroke="#2a150c" stroke-opacity=".35" stroke-width="2.2" stroke-linecap="round"/>
        <path d="M232,170 C250,176 268,188 282,204" fill="none" stroke="#2a150c" stroke-opacity=".3" stroke-width="2"/>
        <path d="M150,196 C168,232 188,264 212,302" fill="none" stroke="#2a150c" stroke-opacity=".28" stroke-width="2.4"/>
        <path d="M206,334 C240,326 284,322 316,326" fill="none" stroke="#2a150c" stroke-opacity=".18" stroke-width="2"/>
        <path d="M296,340 C306,420 320,560 336,800" fill="none" stroke="#ffd8bf" stroke-opacity=".12" stroke-width="12" stroke-linecap="round"/>
        <path d="M244,120 C268,128 292,140 312,160" fill="none" stroke="#ffd8bf" stroke-opacity=".12" stroke-width="8" stroke-linecap="round"/>
        <!-- the pen, resting against the curled middle finger -->
        <g transform="translate(130,95) rotate(49.5)">
          <polygon points="0,0 14,-3.6 14,3.6" fill="#a1a1aa"/>
          <rect x="13" y="-5.5" width="11" height="11" rx="2" fill="url(#wbChrome)"/>
          <rect x="23" y="-8" width="150" height="16" rx="5" fill="url(#wbPen)"/>
          <rect x="126" y="-8.5" width="9" height="17" rx="1.5" fill="url(#wbChrome)"/>
          <rect x="168" y="-7" width="16" height="14" rx="6" fill="#111827"/>
          <rect x="30" y="-6" width="90" height="2.5" rx="1.2" fill="#fff" fill-opacity=".18"/>
        </g>
        <!-- the thumb, pinching the pen from the left -->
        <path d="M126,140 C124,126 132,116 143,118 C154,120 162,132 164,146 C166,164 160,182 150,194 C140,198 131,186 128,170 Z" fill="url(#wbThumb)"/>
        <path d="M150,194 C160,182 166,164 164,146 C162,132 154,121 144,118" fill="none" stroke="#1f0f08" stroke-opacity=".45" stroke-width="2.4" stroke-linecap="round"/>
        <path d="M128,126 C130,121 135,118 140,119" fill="none" stroke="#c9a08c" stroke-width="3" stroke-linecap="round" stroke-opacity=".8"/>
        <!-- the index finger, arched over the pen -->
        <path d="M136,104 C132,96 140,90 152,89 C178,86 206,80 234,80 C262,82 290,100 308,126 C300,140 290,150 280,153
                 C262,140 244,132 224,128 C200,124 178,124 160,124 C148,122 140,115 136,104 Z" fill="url(#wbIndex)"/>
        <path d="M150,90 C178,86 206,81 234,81 C256,83 280,98 298,116" fill="none" stroke="#ffd8bf" stroke-opacity=".18" stroke-width="4" stroke-linecap="round"/>
        <path d="M152,122 C180,125 206,125 226,129 C248,134 266,142 284,154" fill="none" stroke="#1f0f08" stroke-opacity=".6" stroke-width="3" stroke-linecap="round"/>
        <path d="M156,128 C182,131 208,132 228,136 C248,141 264,149 280,160" fill="none" stroke="#1f0f08" stroke-opacity=".18" stroke-width="7" stroke-linecap="round"/>
        <path d="M184,86 C189,98 189,112 185,124 M232,82 c6,8 7,19 3,30 M241,84 c5,7 6,15 3,23" fill="none" stroke="#2a150c" stroke-opacity=".32" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M140,99 C141,93 147,90 155,90 C160,90 163,93 162,97 C158,100 148,101 140,99 Z" fill="#c69a86"/>
        <path d="M144,95 C147,92 152,91 156,92" fill="none" stroke="#fff" stroke-opacity=".5" stroke-width="1.6" stroke-linecap="round"/>
      </g>
    </g></g>`;
    g._tilt = g.querySelector(".tilt");
    svg.appendChild(g);
    return g;
  }

  // Where the marker's tip is, and how the hand leans. Set directly (not
  // through gsap transforms) so a seek always lands the same pose.
  function pose(x, y, tilt) {
    // The forearm hangs nearly straight down, as in a photograph of a hand
    // at a board; writing on the left, it reaches across from the right.
    // A photograph leans less: rotating a photo far from how it was taken
    // shows that it is one.
    const lean = (-(1 - Math.max(0, Math.min(1, x / W))) * 14 + 4) * (hand._photo ? 0.4 : 1) + (hand._turn || 0);
    hand.setAttribute("transform", `translate(${x.toFixed(1)},${y.toFixed(1)})`);
    hand._tilt.setAttribute("transform", `rotate(${(lean + (tilt || 0)).toFixed(2)})`);
  }

  // ── marks ──
  let page = el("g", {});
  const pages = [page];
  let clipN = 0;

  // On a phone the board is a third of the screen: its writing is a fifth
  // bigger in the social cut.
  const ZOOM = data.social ? 1.4 : 1;

  // Powers and indices drawn raised or lowered, small — not as the font's
  // superscript characters, which a handwriting font draws as tick marks.
  const SUPS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ", SUPN = "0123456789+-=()ni";
  const SUBS = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎", SUBN = "0123456789+-=()";
  function setRich(node, str) {
    const re = new RegExp(`([${SUPS}]+)|([${SUBS}]+)`, "g");
    let last = 0, m;
    const plainRun = (s) => { if (s) node.appendChild(document.createTextNode(s)); };
    while ((m = re.exec(str))) {
      plainRun(str.slice(last, m.index));
      const sup = !!m[1], run = m[1] || m[2];
      const span = document.createElementNS(NS, "tspan");
      span.textContent = [...run].map((ch) => (sup ? SUPN[SUPS.indexOf(ch)] : SUBN[SUBS.indexOf(ch)])).join("");
      span.setAttribute("font-size", "62%");
      span.setAttribute("dy", sup ? "-0.55em" : "0.3em");
      node.appendChild(span);
      // Back to the line for what follows.
      const back = document.createElementNS(NS, "tspan");
      back.setAttribute("dy", sup ? "0.341em" : "-0.186em");  // the same distance, at full size
      back.textContent = "\u200b";
      node.appendChild(back);
      last = m.index + run.length;
    }
    plainRun(str.slice(last));
  }

  function text(x, y, str, opt) {
    opt = opt || {};
    const t = el("text", { x, y, "font-size": Math.round((opt.size || 34) * ZOOM), fill: opt.color || INK.black,
      "font-family": FONT, "text-anchor": "start" }, page);
    setRich(t, str);
    const id = `c${clipN++}`;
    const cp = el("clipPath", { id }, defs);
    const r = el("rect", { x: x - 4, y: y - (opt.size || 34) * ZOOM * 1.1, width: 0, height: (opt.size || 34) * ZOOM * 1.5 }, cp);
    t.setAttribute("clip-path", `url(#${id})`);
    t._clip = r;
    return t;
  }

  function centered(y, str, opt) {
    const probe = text(0, -200, str, opt);
    const w = probe.getBBox().width;
    probe.remove();
    return text((W - w) / 2, y, str, opt);
  }

  function path(d, color, width) {
    return el("path", { d, fill: "none", stroke: color || INK.black, "stroke-width": width || 4,
      "stroke-linecap": "round", "stroke-linejoin": "round" }, page);
  }

  function sketchLine(x1, y1, x2, y2, color, width) {
    // A hand-drawn line: slightly curved, slightly off.
    const mx = (x1 + x2) / 2 + jit(4), my = (y1 + y2) / 2 + jit(4);
    return path(`M${x1 + jit(2)},${y1 + jit(2)} Q${mx},${my} ${x2 + jit(2)},${y2 + jit(2)}`, color, width);
  }

  function sketchEllipse(cx, cy, rx, ry, color) {
    let d = "";
    const n = 28, turns = 1.12;
    for (let i = 0; i <= n; i++) {
      const a = -Math.PI / 2 + (i / n) * Math.PI * 2 * turns;
      const k = 1 + jit(0.04);
      d += `${i ? "L" : "M"}${(cx + Math.cos(a) * rx * k).toFixed(1)},${(cy + Math.sin(a) * ry * k).toFixed(1)} `;
    }
    return path(d, color || INK.red, 3.5);
  }

  function sketchBox(x, y, w, h, color) {
    return path(`M${x + jit(3)},${y + jit(3)} L${x + w + jit(3)},${y + jit(3)} L${x + w + jit(3)},${y + h + jit(3)} L${x + jit(3)},${y + h + jit(3)} Z`, color || INK.green, 4);
  }

  // ── tweens ──
  const tl = gsap.timeline({ paused: true });
  // The hand's track: every write and every stroke adds a segment that
  // knows where the tip is at each moment. One tween reads the track, so
  // the hand is a function of time — live or rendered, it moves the same.
  const track = [];
  const ease = gsap.parseEase("power1.inOut");

  function write(t, at, dur) {
    const bb = t.getBBox();
    const r = t._clip;
    // A short reach to the line's start, then the letters.
    const reach = Math.min(0.28, dur * 0.2);
    tl.to(r, { attr: { width: bb.width + 8 }, duration: dur - reach, ease: "none" }, at + reach);
    const letters = Math.max(1, t.textContent.replace(/\s/g, "").length);
    const h = bb.height, base = bb.y + h * 0.78;
    track.push({ t0: at + reach, t1: at + dur, at(p) {
      // Up and down once a letter, leaning into each stroke, as a hand writes.
      const ph = p * letters * Math.PI;
      return { x: bb.x + p * bb.width, y: base - Math.abs(Math.sin(ph)) * h * 0.42, tilt: Math.sin(ph * 2) * 3 };
    } });
    return at + dur;
  }

  function draw(p, at, dur) {
    const len = p.getTotalLength();
    p.style.strokeDasharray = `${len} ${len}`;
    p.style.strokeDashoffset = `${len}`;
    // A round cap on an empty dash still shows a dot: hidden until drawn.
    p.style.opacity = 0;
    tl.set(p, { opacity: 1 }, at);
    const o = { t: 0 };
    tl.to(o, { t: 1, duration: dur, ease: "power1.inOut",
      onUpdate() { p.style.strokeDashoffset = `${len * (1 - o.t)}`; } }, at);
    track.push({ t0: at, t1: at + dur, at(q) { const pt = p.getPointAtLength(len * ease(q)); return { x: pt.x, y: pt.y, tilt: 0 }; } });
    return at + dur;
  }

  const OFF = { x: W + 160, y: H + 260, tilt: 0 };
  function rest(pt) { return { x: Math.min(W + 40, pt.x + 90), y: Math.min(H + 60, pt.y + 150), tilt: -4 }; }
  function mix(a, b, k) { k = ease(Math.max(0, Math.min(1, k))); return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, tilt: a.tilt + (b.tilt - a.tilt) * k }; }

  function handAt(time) {
    // Inside a segment: that segment. Between two: glide across if the gap
    // is short, or lift away from the board and come back if the narrator
    // is talking — so the hand never sits on what was just written.
    let prev = null, next = null, active = null;
    for (const seg of track) {
      if (seg.t0 <= time && time <= seg.t1) { if (!active || seg.t0 >= active.t0) active = seg; }
      if (seg.t1 < time && (!prev || seg.t1 > prev.t1)) prev = seg;
      if (seg.t0 > time && (!next || seg.t0 < next.t0)) next = seg;
    }
    if (active) return active.at((time - active.t0) / Math.max(0.001, active.t1 - active.t0));
    const from = prev ? prev.at(1) : OFF, to = next ? next.at(0) : OFF;
    const t0 = prev ? prev.t1 : 0, t1 = next ? next.t0 : t0 + 1;
    const gap = t1 - t0;
    if (!prev || !next || gap > 0.9) {
      const away = !next ? OFF : !prev ? OFF : rest(from);
      const out = Math.min(0.45, gap / 2), back = Math.min(0.45, gap / 2);
      if (time - t0 < out) return mix(from, away, (time - t0) / out);
      if (t1 - time < back) return mix(away, to, 1 - (t1 - time) / back);
      return away;
    }
    return mix(from, to, (time - t0) / gap);
  }

  function show(node, at, dur) { tl.fromTo(node, { opacity: 0 }, { opacity: 1, duration: dur || 0.3 }, at); return at + (dur || 0.3); }

  function newPage(at) {
    // The eraser: the old page fades, the hand leaves, a fresh one begins.
    const old = page;
    tl.to(old, { opacity: 0, duration: 0.45 }, at);
    page = el("g", {});
    pages.push(page);
    return at + 0.5;
  }

  // ── reading the item's text ──
  function plain(s) {
    return String(s || "").replace(/\$([^$]*)\$/g, "$1").replace(/\\times/g, "×").replace(/\\div/g, "÷")
      .replace(/\\left|\\right/g, "").replace(/\\[dt]?frac\{([^{}]+)\}\{([^{}]+)\}/g, "$1/$2")
      .replace(/\^\\circ/g, "°").replace(/\\[a-zA-Z]+/g, "").replace(/[{}]/g, "").replace(/\s+/g, " ").trim();
  }
  function wrap(s, max) {
    const words = plain(s).split(" "), lines = [];
    let line = "";
    for (const w of words) { if ((line + " " + w).trim().length > max) { lines.push(line.trim()); line = w; } else line += " " + w; }
    if (line.trim()) lines.push(line.trim());
    return lines;
  }

  // ── scenes ──
  // Each builder lays its marks on the current page between `at` and
  // `at + dur`, spending ~80% of the time drawing and holding the rest.
  let cursorY = 110;
  const LEFT = 70, MARGIN = 780;

  function room(need, at) {
    if (cursorY + need > H - 40) { at = newPage(at); cursorY = 110; }
    return at;
  }

  const builders = {
    title(s, at, dur) {
      // The whole question, never a heading: the writing shrinks for a long
      // question, and one longer than a board carries on to the next.
      const fit = (size) => {
        const width = Math.round((46 * 40) / (size * ZOOM));
        const lines = wrap(s.text, width);
        const ctx = s.context ? wrap(s.context, Math.round(width * 1.45)) : [];
        const height = ctx.length * 40 * ZOOM * (size / 40) + lines.length * size * 1.45 * ZOOM;
        return { lines, ctx, height };
      };
      let size = 40, laid = fit(size);
      while (laid.height > H - 170 && size > 28) { size -= 4; laid = fit(size); }
      const { lines, ctx } = laid;
      const per = (dur * 0.85) / Math.max(1, lines.length + ctx.length);
      let y = 120;
      const next = (step) => {
        y += step;
        if (y > H - 50) { at = newPage(at); y = 110; }
      };
      for (const c of ctx) { at = write(text(LEFT, y, c, { size: Math.round(size * 0.68), color: INK.grey }), at, per); next(40 * ZOOM * (size / 40)); }
      if (ctx.length) next(10);
      for (const l of lines) { at = write(text(LEFT, y, l, { size }), at, per); next(size * 1.45 * ZOOM); }
      cursorY = y + 20;
      return { at, y };
    },
    arch(s, at, dur) {
      // An architecture: the parts as boxes, left to right in the order data
      // reaches them, the arrows drawn between, then the data itself — dots
      // running along each arrow in turn, again and again while it is said.
      at = newPage(at); cursorY = H;
      const nodes = (s.nodes || []).slice(0, 9), edges = (s.edges || []).filter((e) => e && e.from && e.to).slice(0, 14);
      if (!nodes.length) return at + dur;
      const col = {};
      nodes.forEach((n) => { col[n.id] = 0; });
      for (let pass = 0; pass < nodes.length; pass++) {
        for (const e of edges) if (e.from in col && e.to in col && col[e.to] < col[e.from] + 1 && col[e.from] + 1 < nodes.length) col[e.to] = col[e.from] + 1;
      }
      const cols = Math.max(...Object.values(col)) + 1, byCol = {};
      nodes.forEach((n) => { (byCol[col[n.id]] = byCol[col[n.id]] || []).push(n); });
      const top = s.title ? 120 : 70, bw = Math.min(230, (W - 120) / cols - 40), bh = 78, pos = {};
      if (s.title) at = write(centered(70, String(s.title), { size: 34, color: INK.blue }), at, Math.min(1, dur * 0.12));
      Object.entries(byCol).forEach(([c, list]) => {
        const x = 60 + (Number(c) + 0.5) * ((W - 120) / cols) - bw / 2;
        list.forEach((n, r) => { pos[n.id] = { x, y: top + (r + 0.5) * ((H - top - 40) / list.length) - bh / 2, n }; });
      });
      const COLORS = { ui: INK.blue, user: INK.green, api: INK.red, data: "#7c3aed", logic: INK.black, external: INK.grey };
      const per = (dur * 0.45) / (nodes.length + edges.length);
      for (const id in pos) {
        const p = pos[id], color = COLORS[p.n.kind] || INK.black;
        at = draw(sketchBox(p.x, p.y, bw, bh, color), at, per * 0.6);
        const words = wrap(p.n.label || id, Math.round(bw / 13));
        words.slice(0, 2).forEach((line, k) => {
          const t = text(0, -200, line, { size: 22, color });
          const w = t.getBBox().width; t.remove();
          at = write(text(p.x + (bw - w) / 2, p.y + (words.length > 1 ? 32 + k * 30 : 48), line, { size: 22, color }), at, per * 0.4 / Math.min(2, words.length));
        });
      }
      const paths = [];
      for (const e of edges) {
        const a = pos[e.from], b = pos[e.to];
        if (!a || !b) continue;
        const x1 = a.x + bw, y1 = a.y + bh / 2, x2 = b.x, y2 = b.y + bh / 2;
        const back = x2 <= x1;
        const sx = back ? a.x + bw / 2 : x1, sy = back ? (a.y < b.y ? a.y + bh : a.y) : y1;
        const ex = back ? b.x + bw / 2 : x2 - 6, ey = back ? (a.y < b.y ? b.y : b.y + bh) : y2;
        const line = sketchLine(sx, sy, ex, ey, INK.grey, 3);
        at = draw(line, at, per * 0.7);
        const ang = Math.atan2(ey - sy, ex - sx);
        const head = path(`M${ex - 16 * Math.cos(ang - 0.45)},${ey - 16 * Math.sin(ang - 0.45)} L${ex},${ey} L${ex - 16 * Math.cos(ang + 0.45)},${ey - 16 * Math.sin(ang + 0.45)}`, INK.grey, 3);
        show(head, at - 0.1, 0.15);
        if (e.label) {
          const t = text((sx + ex) / 2 - 40, (sy + ey) / 2 - 10, String(e.label).slice(0, 18), { size: 16, color: INK.grey });
          show(t, at, 0.2);
          t._clip.setAttribute("width", 400);
        }
        paths.push(line);
      }
      // The data, moving.
      const end = at + Math.max(1, dur * 0.5) - 0.2;
      let k = 0, t0 = at;
      while (paths.length && t0 < end) {
        const p = paths[k % paths.length], len = p.getTotalLength();
        const dot = el("circle", { r: 9, fill: INK.red, opacity: 0 }, page);
        const o = { t: 0 };
        tl.set(dot, { opacity: 1 }, t0);
        tl.to(o, { t: 1, duration: 0.7, ease: "none", onUpdate() { const pt = p.getPointAtLength(len * o.t); dot.setAttribute("cx", pt.x); dot.setAttribute("cy", pt.y); } }, t0);
        tl.set(dot, { opacity: 0 }, t0 + 0.72);
        t0 += 0.55; k++;
      }
      return Math.max(at, end) + 0.2;
    },

    code(s, at, dur) {
      // An editor: a dark page, the file's name, the code typed line by line.
      at = newPage(at); cursorY = H;
      // The editor's frame and gutter: drawn now, there from this scene on.
      const frame = el("g", { opacity: 0 }, page);
      tl.to(frame, { opacity: 1, duration: 0.3 }, at);
      el("rect", { x: 20, y: 20, width: W - 40, height: H - 40, rx: 14, fill: "#0f172a" }, frame);
      el("rect", { x: 20, y: 20, width: W - 40, height: 46, rx: 14, fill: "#1e293b" }, frame);
      ["#ef4444", "#f59e0b", "#22c55e"].forEach((c, k) => el("circle", { cx: 50 + k * 24, cy: 43, r: 7, fill: c }, frame));
      const mono = "'JetBrains Mono', 'Fira Code', Menlo, Consolas, monospace";
      const name = text(130, 52, String(s.file || ""), { size: 15, color: "#94a3b8" });
      name.setAttribute("font-family", mono); name._clip.setAttribute("width", 900);
      frame.appendChild(name);
      const lines = String(s.code || "").replace(/\t/g, "  ").split("\n").slice(0, 16);
      const size = 15, lh = Math.min(38, (H - 110) / Math.max(8, lines.length));
      const light = new Set((s.highlight || []).map(Number));
      const typed = lines.reduce((a, l) => a + Math.max(1, l.trim().length), 0) || 1;
      const budget = dur * 0.85;
      lines.forEach((line, k) => {
        const y = 100 + k * lh;
        const comment = /^\s*(\/\/|#|\/\*|\*|<!--)/.test(line);
        el("text", { x: 34, y, "font-size": Math.round(size * ZOOM * 0.8), fill: "#475569", "font-family": mono }, frame).textContent = String(k + 1);
        if (light.has(k + 1)) el("rect", { x: 22, y: y - lh * 0.72, width: W - 44, height: lh, fill: "rgba(250,204,21,.13)" }, frame);
        if (!line.trim()) return;
        const t = text(80, y, line, { size, color: comment ? "#64748b" : light.has(k + 1) ? "#fde68a" : "#e2e8f0" });
        t.setAttribute("font-family", mono);
        t.style.whiteSpace = "pre";
        at = write(t, at, budget * Math.max(1, line.trim().length) / typed);
      });
      return at + dur * 0.1;
    },

    screen(s, at, dur) {
      // A screen of the app, the whole board: it slides in, then the hand
      // goes to what to press and rings it, as a teacher shows a projector.
      at = newPage(at); cursorY = H;
      const src = String(s.img || "");
      if (!/^data:image\/(png|jpeg|webp);base64,/.test(src)) return at;
      const g = el("g", {}, page);
      const img = el("image", { href: src, x: 0, y: 0, width: W, height: H, preserveAspectRatio: "xMidYMid meet" }, g);
      tl.fromTo(img, { opacity: 0 }, { opacity: 1, duration: 0.35 }, at);
      const b = Array.isArray(s.box) ? s.box.map(Number) : [];
      if (b.length === 4 && b[2] > 0 && b[3] > 0) {
        const cx = b[0] + b[2] / 2, cy = b[1] + b[3] / 2;
        const ring = sketchEllipse(cx, cy, b[2] / 2 + 26, b[3] / 2 + 18, INK.red);
        g.appendChild(ring);
        ring.setAttribute("stroke-width", 6);
        const ringAt = at + Math.min(1.2, dur * 0.25), ringDur = Math.min(1.1, dur * 0.25);
        draw(ring, ringAt, ringDur);
        // Then closer: a phone shows the board small, so the screen grows
        // round what was ringed (never past its own edges).
        const k = Math.max(1, Math.min(2.1, W / (b[2] + 560)));
        const tx = Math.min(0, Math.max(W - W * k, W / 2 - cx * k)), ty = Math.min(0, Math.max(H - H * k, H / 2 - cy * k));
        const z = { k: 1, x: 0, y: 0 };
        const zoomAt = ringAt + ringDur + 0.35;
        if (k > 1.05 && zoomAt < at + dur - 0.8) {
          tl.to(z, { k, x: tx, y: ty, duration: Math.min(1.2, at + dur - zoomAt - 0.4), ease: "power2.inOut",
                     onUpdate() { g.setAttribute("transform", `translate(${z.x} ${z.y}) scale(${z.k})`); } }, zoomAt);
        }
      }
      return at + dur;
    },

    figure(s, at, dur) {
      // The item's own figure, drawn by the marker: every line traced as a
      // teacher would draw it, then the shading and the labels. It sits at
      // the top of a fresh page and stays there while the working is
      // written underneath.
      const parsed = new DOMParser().parseFromString(String(s.svg || ""), "image/svg+xml");
      const src = parsed.documentElement;
      if (!src || src.nodeName.toLowerCase() !== "svg" || parsed.getElementsByTagName("parsererror").length) return { at };
      // A drawing only: nothing that runs, nothing fetched from outside.
      src.querySelectorAll("script, foreignObject, iframe").forEach((n) => n.remove());
      for (const n of [src, ...src.querySelectorAll("*")]) {
        for (const a of [...n.attributes]) {
          const v = a.value.trim().toLowerCase();
          if (/^on/i.test(a.name) || (/href$/i.test(a.name) && !(v.startsWith("#") || v.startsWith("data:image/")))) n.removeAttribute(a.name);
        }
      }
      at = newPage(at); cursorY = 110;
      const fig = document.importNode(src, true);
      // Ids made unique, so two figures (or the board's own defs) never clash.
      const tag = `f${clipN++}_`;
      for (const n of fig.querySelectorAll("[id]")) n.id = tag + n.id;
      for (const n of [fig, ...fig.querySelectorAll("*")]) {
        for (const a of [...n.attributes]) {
          if (a.value.includes("url(#")) n.setAttribute(a.name, a.value.replace(/url\(#/g, `url(#${tag}`));
          else if (/href$/i.test(a.name) && a.value.startsWith("#")) n.setAttribute(a.name, "#" + tag + a.value.slice(1));
        }
      }
      let vb = (fig.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
      if (vb.length !== 4 || vb.some((v) => !isFinite(v)) || vb[2] <= 0 || vb[3] <= 0) {
        const w = parseFloat(fig.getAttribute("width")) || 600, h = parseFloat(fig.getAttribute("height")) || 400;
        vb = [0, 0, w, h];
        fig.setAttribute("viewBox", vb.join(" "));
      }
      const boxW = W - 2 * LEFT, boxH = 470, top = 80;
      const k = Math.min(boxW / vb[2], boxH / vb[3]);
      const fw = vb[2] * k, fh = vb[3] * k;
      fig.setAttribute("x", (W - fw) / 2); fig.setAttribute("y", top);
      fig.setAttribute("width", fw); fig.setAttribute("height", fh);
      fig.setAttribute("preserveAspectRatio", "xMidYMid meet");
      fig.removeAttribute("style");
      page.appendChild(fig);

      // Where a point of the figure is on the board, for the hand.
      const toBoard = (node) => {
        const own = node.getScreenCTM(), board = svg.getScreenCTM();
        const m = own && board ? board.inverse().multiply(own) : new DOMMatrix();
        return (x, y) => { const p = new DOMPoint(x, y).matrixTransform(m); return { x: p.x, y: p.y, tilt: 0 }; };
      };
      const hidden = "defs, clipPath, marker, pattern, mask, symbol, linearGradient, radialGradient, filter";
      const marks = [...fig.querySelectorAll("path, line, polyline, polygon, rect, circle, ellipse, text, image")]
        .filter((n) => !n.closest(hidden) && !(n.parentNode && n.parentNode.closest && n.parentNode.closest("text")));
      const area = vb[2] * vb[3];
      const jobs = [];
      for (const n of marks) {
        const cs = getComputedStyle(n);
        if (cs.display === "none" || cs.visibility === "hidden") continue;
        const name = n.nodeName.toLowerCase();
        if (name === "rect") {
          // The figure's own background: there from the start, not drawn.
          const b = n.getBBox();
          if (b.width * b.height >= area * 0.8) {
            if (/^rgb\(255, 255, 255\)$/.test(cs.fill)) n.style.fill = "transparent";  // the board shows through
            continue;
          }
        }
        const stroked = cs.stroke !== "none" && parseFloat(cs.strokeWidth) > 0 && name !== "text" && name !== "image";
        const dashed = cs.strokeDasharray && cs.strokeDasharray !== "none";
        let len = 0;
        if (stroked && !dashed && typeof n.getTotalLength === "function") { try { len = n.getTotalLength(); } catch (e) { len = 0; } }
        const filled = cs.fill !== "none" && name !== "line" && parseFloat(cs.fillOpacity) > 0;
        jobs.push({ n, name, len, filled, fillOpacity: cs.fillOpacity, weight: len > 0 ? Math.max(0.12, Math.sqrt(len * k) / 22) : 0.18 });
      }
      // Long figures are drawn quicker, never past the narration.
      const budget = dur * 0.85, total = jobs.reduce((a, j) => a + j.weight, 0) || 1;
      const scale = Math.min(1, budget / total);
      for (const j of jobs) {
        const d = j.weight * scale, n = j.n;
        if (j.len > 0) {
          const len = j.len, map = toBoard(n);
          n.style.strokeDasharray = `${len} ${len}`;
          n.style.strokeDashoffset = `${len}`;
          n.style.opacity = 0;
          tl.set(n, { opacity: 1 }, at);
          if (j.filled) n.style.fillOpacity = 0;
          const o = { t: 0 };
          tl.to(o, { t: 1, duration: d, ease: "power1.inOut", onUpdate() { n.style.strokeDashoffset = `${len * (1 - o.t)}`; } }, at);
          track.push({ t0: at, t1: at + d, at(q) { const p = n.getPointAtLength(len * ease(q)); return map(p.x, p.y); } });
          if (j.filled) {
            const f = { v: 0 }, to = parseFloat(j.fillOpacity) || 1;
            tl.to(f, { v: to, duration: 0.25, onUpdate() { n.style.fillOpacity = f.v; } }, at + d * 0.7);
          }
        } else {
          // A label, a shaded shape or a dashed line: the hand goes to it and it appears.
          let b; try { b = n.getBBox(); } catch (e) { b = { x: 0, y: 0, width: 0, height: 0 }; }
          const map = toBoard(n), a = map(b.x, b.y + b.height * 0.8), z = map(b.x + b.width, b.y + b.height * 0.8);
          track.push({ t0: at, t1: at + d, at(q) { return { x: a.x + (z.x - a.x) * q, y: a.y + (z.y - a.y) * q, tilt: 0 }; } });
          show(n, at, Math.max(0.12, d));
        }
        at += d;
      }
      cursorY = top + fh + 56;
      return { at };
    },
    working(s, at, dur) {
      // A line of the item's own solution, written as the voice reads it.
      const lines = wrap(s.text, Math.round(54 / ZOOM)).slice(0, 4);
      at = room(lines.length * 46 * ZOOM + 16, at);
      const per = (dur * 0.85) / Math.max(1, lines.length);
      for (const l of lines) { at = write(text(LEFT, cursorY, l, { size: 34, color: INK.blue }), at, per); cursorY += 48 * ZOOM; }
      cursorY += 16;
      return { at };
    },
    setup(s, at, dur) {
      at = newPage(at); cursorY = 110;
      at = write(text(LEFT, cursorY, "As one calculation:", { size: 28, color: INK.blue }), at, dur * 0.3);
      cursorY += 62;
      at = write(text(LEFT, cursorY, plain(s.expression), { size: 46 }), at, dur * 0.5);
      cursorY += 70;
      return { at };
    },
    rewrite(s, at, dur) {
      at = room(130, at);
      const st = s.step;
      // The margin first: the side calculation, circled — what a teacher
      // works out before writing the next line.
      const neg = (v) => (String(v).startsWith("-") ? `(${v})` : `${v}`);
      const side = text(MARGIN, cursorY - 10, `${st.left} ${st.op} ${neg(st.right)} = ${st.result}`, { size: 34, color: INK.red });
      at = write(side, at, dur * 0.3);
      const bb = side.getBBox();
      at = draw(sketchEllipse(bb.x + bb.width / 2, bb.y + bb.height / 2, bb.width / 2 + 16, bb.height / 2 + 5), at, dur * 0.12);
      const why = text(MARGIN, cursorY + 36, st.why, { size: 22, color: INK.blue });
      at = write(why, at, dur * 0.18);
      const line = text(LEFT, cursorY, `= ${plain(st.after)}`, { size: 44 });
      at = write(line, at, dur * 0.2);
      cursorY += 90;
      return { at };
    },
    number_line_start(s, at, dur) {
      at = newPage(at); cursorY = 110;
      const sp = s.spec, x0 = 110, x1 = W - 110, y = 520;
      const X = (v) => x0 + ((v - sp.min) * (x1 - x0)) / (sp.max - sp.min);
      wb.nl = { X, y };
      at = draw(sketchLine(x0 - 30, y, x1 + 30, y, INK.black, 5), at, dur * 0.25);
      const ticks = [];
      const every = (sp.max - sp.min) / sp.tick > 30 ? 5 : 1;
      for (let v = sp.min, k = 0; v <= sp.max; v += sp.tick, k++) {
        ticks.push(sketchLine(X(v), y - 12, X(v), y + 12, INK.black, 3));
        if (k % every === 0) { const t = text(X(v) - (String(v).length * 6), y + 48, String(v), { size: 24, color: INK.grey }); show(t, at + 0.02 * k, 0.2); t._clip.setAttribute("width", 400); }
      }
      ticks.forEach((tk, k) => draw(tk, at + (k * dur * 0.3) / ticks.length, 0.12));
      at += dur * 0.35;
      const start = el("circle", { cx: X(sp.start), cy: y, r: 11, fill: INK.green }, page);
      at = show(start, at, 0.3);
      const lab = text(X(sp.start) - 30, y + 92, `start ${sp.start}`, { size: 26, color: INK.green });
      at = write(lab, at, dur * 0.15);
      return { at };
    },
    number_line_jump(s, at, dur) {
      const { X, y } = wb.nl;
      const a = X(s.from), b = X(s.to), m = (a + b) / 2;
      const lift = Math.min(130, 50 + Math.abs(b - a) * 0.35) + (wb.jumps = (wb.jumps || 0) + 1) * 8;
      const arc = path(`M${a},${y - 6} Q${m},${y - lift * 2} ${b},${y - 6}`, s.move > 0 ? INK.blue : INK.red, 4);
      at = draw(arc, at, dur * 0.4);
      const head = path(`M${b - 12 * Math.sign(b - a)},${y - 26} L${b},${y - 8} L${b + 4 * Math.sign(b - a)},${y - 30}`, s.move > 0 ? INK.blue : INK.red, 4);
      at = draw(head, at, 0.25);
      const lab = text(m - 22, y - lift - 6, `${s.move > 0 ? "+" : ""}${s.move}`, { size: 32, color: s.move > 0 ? INK.blue : INK.red });
      at = write(lab, at, dur * 0.15);
      const dot = el("circle", { cx: b, cy: y, r: 9, fill: INK.green }, page);
      at = show(dot, at, 0.25);
      return { at };
    },
    balance_start(s, at, dur) {
      at = newPage(at); cursorY = 110;
      const sp = s.spec;
      wb.bal = { y: 360, n: 0 };
      at = draw(path(`M640,330 L600,420 L680,420 Z`, INK.black, 4), at, dur * 0.12);
      at = draw(sketchLine(330, 330, 950, 330, INK.black, 6), at, dur * 0.15);
      at = draw(sketchBox(340, 230, 260, 90, INK.green), at, dur * 0.1);
      at = draw(sketchBox(680, 230, 260, 90, INK.green), at, dur * 0.1);
      at = write(text(370, 290, plain(sp.left), { size: 44 }), at, dur * 0.15);
      at = write(text(710, 290, plain(sp.right), { size: 44 }), at, dur * 0.15);
      wb.bal.line = 480;
      return { at };
    },
    balance_move(s, at, dur) {
      const sp = s.spec, state = (sp.states || [])[wb.bal.n++];
      let y = wb.bal.line;
      if (y > H - 60) { at = newPage(at); y = 140; }
      const note = text(LEFT, y, `${s.move.op} ${s.move.value}`, { size: 30, color: INK.red });
      at = write(note, at, dur * 0.2);
      at = write(text(LEFT + 150, y, "on both sides →", { size: 26, color: INK.grey }), at, dur * 0.15);
      if (state) at = write(text(LEFT + 380, y, `${plain(state[0])} = ${plain(state[1])}`, { size: 42 }), at, dur * 0.4);
      wb.bal.line = y + 64;
      return { at };
    },
    balance_done(s, at, dur) {
      const t = text(LEFT + 380, wb.bal.line + 10, `${s.spec.variable} = ${s.spec.target}`, { size: 50, color: INK.green });
      at = write(t, at, dur * 0.4);
      const bb = t.getBBox();
      at = draw(sketchBox(bb.x - 16, bb.y - 8, bb.width + 32, bb.height + 16), at, dur * 0.3);
      wb.bal.line += 90;
      cursorY = wb.bal.line;
      return { at };
    },
    fraction_bars(s, at, dur) {
      const sp = s.spec;
      if (s.phase === "start") { at = newPage(at); cursorY = 110; }
      const [a, b] = s.phase === "start" ? sp.first : sp.first_as;
      const [c, d] = s.phase === "start" ? sp.second : sp.second_as;
      const y0 = s.phase === "start" ? 150 : 400;
      const bar = (n, den, y, color) => {
        let t = at;
        t = draw(sketchBox(140, y, 900, 70, INK.black), t, dur * 0.12);
        const w = 900 / den;
        for (let k = 1; k < den; k++) draw(sketchLine(140 + k * w, y, 140 + k * w, y + 70, INK.black, 2.5), t + (k * dur * 0.12) / den, 0.08);
        t += dur * 0.12;
        for (let k = 0; k < n; k++) {
          // Hatching: three strokes per shaded piece.
          for (let h = 0; h < 3; h++) draw(sketchLine(140 + k * w + 6 + h * (w - 12) / 3, y + 64, 140 + k * w + 6 + (h + 1) * (w - 12) / 3, y + 6, color, 3), t + (k * dur * 0.15) / Math.max(1, n), 0.08);
        }
        t += dur * 0.15;
        write(text(1060, y + 48, `${n}/${den}`, { size: 40, color }), t, 0.4);
        return t + 0.4;
      };
      if (s.phase === "result") {
        const t = text(LEFT, 640, `${sp.first_as[0]}/${sp.common} ${sp.op} ${sp.second_as[0]}/${sp.common} = ${sp.result[0]}/${sp.result[1]}`, { size: 46, color: INK.green });
        at = write(t, at, dur * 0.5);
        cursorY = H;   // the board is full: the answer gets a clean page
        return { at };
      }
      if (s.phase === "common") at = write(text(LEFT, 370, `cut both into ${sp.common} equal pieces`, { size: 28, color: INK.blue }), at, dur * 0.15);
      at = bar(a, b, y0, INK.blue);
      at = bar(c, d, y0 + 100, INK.red);
      return { at };
    },
    answer(s, at, dur) {
      // Never over what is written: the answer wraps to the board's width and
      // goes below the working — or, if it does not fit there, on a clean page.
      const words = `Answer: ${s.option ? s.option + ".  " : ""}${plain(s.text)}`;
      const size = 46, lineH = Math.round(62 * ZOOM), maxW = W - LEFT - 90;
      const lines = [];
      let line = "";
      for (const word of words.split(/\s+/)) {
        const probe = text(0, -200, line ? `${line} ${word}` : word, { size });
        const wide = probe.getBBox().width > maxW;
        probe.remove();
        if (wide && line) { lines.push(line); line = word; } else line = line ? `${line} ${word}` : word;
      }
      if (line) lines.push(line);
      const need = lines.length * lineH + 50;
      if (cursorY + need > H - 40) { at = newPage(at); cursorY = 110; }
      let y = cursorY + 20, x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const l of lines) {
        const t = text(LEFT, y, l, { size, color: INK.green });
        at = write(t, at, (dur * 0.45) / lines.length);
        const bb = t.getBBox();
        x0 = Math.min(x0, bb.x); y0 = Math.min(y0, bb.y); x1 = Math.max(x1, bb.x + bb.width); y1 = Math.max(y1, bb.y + bb.height);
        y += lineH;
      }
      cursorY = y + 40;
      at = draw(sketchBox(x0 - 18, y0 - 10, x1 - x0 + 36, y1 - y0 + 20), at, dur * 0.25);
      return { at };
    },
    countdown(s, at, dur) {
      // The board holds the question while the frame counts down; the hand
      // steps back so nothing covers it.
      return { at };
    },
    outro(s, at, dur) {
      at = newPage(at);
      const lines = [[s.name, 64, INK.blue], [s.handle, 52, INK.red], [s.cta, 38, INK.black], [s.website, 32, INK.grey]]
        .filter((l) => l[0]);
      const per = (dur * 0.8) / Math.max(1, lines.length);
      let y = 250 - (lines.length - 2) * 30;
      lines.forEach(([str, size, color], k) => {
        const t = centered(y, String(str), { size, color });
        at = write(t, at, per * (k ? 0.9 : 1.2));
        if (k === 0) {
          const bb = t.getBBox();
          at = draw(path(`M${bb.x},${bb.y + bb.height + 10} Q${bb.x + bb.width / 2},${bb.y + bb.height + 24} ${bb.x + bb.width},${bb.y + bb.height + 6}`, INK.red, 5), at, 0.35);
        }
        y += size * 1.7;
      });
      return { at };
    },
    trap(s, at, dur) {
      at = room(110, at);
      const t = text(LEFT, cursorY, `${s.option}.  ${plain(s.text)}`, { size: 38, color: INK.grey });
      at = write(t, at, dur * 0.25);
      const bb = t.getBBox();
      at = draw(sketchLine(bb.x - 6, bb.y + bb.height * 0.55, bb.x + bb.width + 6, bb.y + bb.height * 0.45, INK.red, 5), at, dur * 0.12);
      const why = wrap(s.say.replace(/^If you chose [A-Z]:\s*/, ""), 60).slice(0, 2);
      let y = cursorY + 40;
      for (const l of why) { at = write(text(LEFT + 40, y, l, { size: 24, color: INK.blue }), at, dur * 0.18); y += 32; }
      cursorY = y + 30;
      return { at };
    },
    // ── chemistry (services/chem_walkthrough.py) ──
    chem_lab(s, at, dur) {
      // The lab bench: the vessel, what goes in, and what you see — the
      // colour changing, bubbles rising, a precipitate falling, a coating
      // growing, a flame — each tween on the one timeline, so it renders.
      const s0 = at;
      at = newPage(at); cursorY = H;
      const lab = s.lab || {}, vessel = lab.vessel || "beaker";
      const names = (s.reactants || []).map((r) => r.formula).join("  +  ");
      at = write(centered(74, names + (s.condition ? `   (${s.condition})` : ""), { size: 36, color: INK.blue }), at, Math.min(1.2, dur * 0.15));
      const cx = data.social ? W / 2 : 470, base = 600;
      const tube = /tube/.test(vessel), jar = /jar|spoon/.test(vessel), wide = /trough/.test(vessel);
      const vw = tube ? 90 : wide ? 360 : jar ? 170 : 230, vh = tube ? 330 : wide ? 150 : 300;
      const left = cx - vw / 2, top = base - vh;
      const outline = tube
        ? `M${left},${top} L${left},${base - vw / 2} A${vw / 2},${vw / 2} 0 0 0 ${left + vw},${base - vw / 2} L${left + vw},${top}`
        : `M${left - 8},${top} L${left},${top + 12} L${left},${base} L${left + vw},${base} L${left + vw},${top + 12} L${left + vw + 8},${top}`;
      const liquidTop = top + vh * (jar ? 0.95 : 0.38);
      let liquid = null;
      if (lab.liquid && !jar && vessel !== "spoon") {
        liquid = el("path", { d: tube
          ? `M${left + 3},${liquidTop} L${left + 3},${base - vw / 2} A${vw / 2 - 3},${vw / 2 - 3} 0 0 0 ${left + vw - 3},${base - vw / 2} L${left + vw - 3},${liquidTop} Z`
          : `M${left + 3},${liquidTop} L${left + 3},${base - 3} L${left + vw - 3},${base - 3} L${left + vw - 3},${liquidTop} Z`,
          fill: lab.liquid, opacity: 0.85 }, page);
        at = show(liquid, at, 0.4);
      }
      if (lab.gas) {
        const g = el("rect", { x: left + 4, y: top + 6, width: vw - 8, height: vh - 10, fill: lab.gas, opacity: 0.55 }, page);
        at = show(g, at, 0.3);
        if (lab.gas_fades) tl.to(g, { opacity: 0.08, duration: dur * 0.5 }, at + dur * 0.25);
      }
      at = draw(path(outline, INK.black, 5), at, Math.min(1, dur * 0.12));
      const t0 = at, span = Math.max(1.5, s0 + dur - at - 0.3);   // what is left of the scene, for the reaction
      // The solid: a strip of metal or a lump, lowered in.
      let solid = null;
      if (lab.solid) {
        const sw = tube ? 26 : 46, sh = tube ? 90 : 110;
        const sx = cx - sw / 2, sy = (lab.solid_moves ? liquidTop - 26 : base - sh - (tube ? vw / 2 : 8));
        solid = el("rect", { x: sx, y: sy, width: sw, height: lab.solid_moves ? 26 : sh, rx: lab.solid_moves ? 13 : 4,
          fill: lab.solid, stroke: "#333", "stroke-width": 2 }, page);
        tl.fromTo(solid, { attr: { y: top - 140 }, opacity: 0 }, { attr: { y: sy }, opacity: 1, duration: 0.8, ease: "power2.in" }, t0);
        if (lab.solid_moves) tl.to(solid, { attr: { x: sx + 70 }, duration: 0.6, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.6)), ease: "sine.inOut" }, t0 + 0.8);
        if (lab.solid_shrinks) tl.to(solid, { attr: { height: 6, y: sy + (lab.solid_moves ? 10 : sh - 6), width: sw * 0.4, x: sx + sw * 0.3 }, duration: span * 0.85, ease: "none" }, t0 + 1);
        if (lab.solid_to) tl.to(solid, { attr: { fill: lab.solid_to }, duration: span * 0.6 }, t0 + 1);
        if (lab.coating) {
          const coat = el("rect", { x: sx - 3, y: sy - 3, width: sw + 6, height: sh + 6, rx: 6, fill: lab.coating, opacity: 0 }, page);
          tl.to(coat, { opacity: 0.85, duration: span * 0.7 }, t0 + 1.2);
        }
      }
      if (liquid && lab.liquid_to) tl.to(liquid, { attr: { fill: lab.liquid_to }, duration: span * 0.75 }, t0 + 1);
      // Drops from a dropper above.
      if (lab.drops) {
        const dropper = path(`M${cx - 10},${top - 120} L${cx - 10},${top - 40} L${cx},${top - 22} L${cx + 10},${top - 40} L${cx + 10},${top - 120}`, INK.grey, 4);
        at = draw(dropper, t0, 0.4);
        for (let k = 0; k < 6; k++) {
          const d = el("circle", { cx, cy: top - 20, r: 7, fill: lab.drop_colour || "#9ad1ff", opacity: 0 }, page);
          const when = t0 + 0.5 + k * (span * 0.45 / 6);
          tl.fromTo(d, { attr: { cy: top - 20 }, opacity: 1 }, { attr: { cy: liquidTop }, opacity: 0, duration: 0.5, ease: "power2.in" }, when);
        }
      }
      // A precipitate: particles that appear as the drops land, then settle.
      if (lab.precipitate) {
        for (let k = 0; k < 40; k++) {
          const px = left + 10 + rnd() * (vw - 20), py = liquidTop + 10 + rnd() * ((base - liquidTop) * 0.6);
          const settle = base - 10 - rnd() * 22 - (tube ? vw / 3 : 0);
          const p = el("circle", { cx: px, cy: py, r: 3 + rnd() * 3, fill: lab.precipitate, stroke: "#999", "stroke-width": 0.6, opacity: 0 }, page);
          const when = t0 + 0.9 + rnd() * span * 0.35;
          tl.to(p, { opacity: 1, duration: 0.3 }, when);
          tl.to(p, { attr: { cy: settle }, duration: span * 0.4, ease: "power1.in" }, when + 0.4);
        }
      }
      // Bubbles of gas, rising again and again while it is said.
      if (lab.bubbles) {
        const n = lab.slow ? 6 : 22;
        for (let k = 0; k < n; k++) {
          const bx = cx - vw / 3 + rnd() * (vw * 2 / 3), r = 3 + rnd() * 5;
          const b = el("circle", { cx: bx, cy: base - 30, r, fill: "none", stroke: "#5b8db8", "stroke-width": 2, opacity: 0 }, page);
          const rise = 0.9 + rnd() * 0.9, start = t0 + 1 + rnd() * 1.2;
          const times = Math.max(1, Math.floor((span - 1.2) / rise));
          tl.fromTo(b, { attr: { cy: base - 30 }, opacity: 0.9 }, { attr: { cy: liquidTop - 6 }, opacity: 0.2, duration: rise, ease: "none", repeat: times - 1 }, start);
        }
        const gas = text(left + vw + 30, liquidTop - 30, `${lab.bubbles === "H2" ? "H₂" : lab.bubbles === "CO2" ? "CO₂" : lab.bubbles} gas`, { size: 26, color: INK.blue });
        write(gas, t0 + 1.4, 0.6);
      }
      // A flame under the vessel (or on the spoon), flickering.
      if (lab.flame || lab.burner) {
        const fy = jar || vessel === "spoon" ? top + vh * 0.55 : base + 70;
        const white = /^#f{6}$|^#fff$/i.test(lab.flame || "");
        const colour = white ? "#fff7c2" : (lab.flame || "#4ea8ff");
        if (white) {
          // A brilliant white flame on a white board: a glow around it, so it is seen.
          const glow = el("circle", { cx, cy: fy - 40, r: 70, fill: "#ffe680", opacity: 0 }, page);
          tl.to(glow, { opacity: 0.55, duration: 0.3 }, t0 + 0.6);
          tl.to(glow, { attr: { r: 90 }, opacity: 0.35, duration: 0.3, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.3)) }, t0 + 0.9);
        }
        const flame = el("path", { d: `M${cx - 22},${fy} Q${cx},${fy - 90} ${cx + 22},${fy} Q${cx},${fy - 20} ${cx - 22},${fy} Z`,
          fill: colour, opacity: 0, stroke: "#e07b00", "stroke-width": 1.5 }, page);
        tl.to(flame, { opacity: 0.9, duration: 0.3 }, t0 + 0.6);
        tl.to(flame, { attr: { d: `M${cx - 18},${fy} Q${cx + 6},${fy - 110} ${cx + 18},${fy} Q${cx},${fy - 24} ${cx - 18},${fy} Z` },
          duration: 0.25, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.25)), ease: "sine.inOut" }, t0 + 0.9);
      }
      if (lab.heat) {
        for (let k = 0; k < 3; k++) {
          const hx = cx - 60 + k * 60, wav = path(`M${hx},${top - 20} q10,-15 0,-30 q-10,-15 0,-30`, INK.red, 3);
          tl.set(wav, { opacity: 0 }, 0);
          tl.to(wav, { opacity: 0.8, duration: 0.4, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.8)) }, t0 + 1.5 + k * 0.2);
        }
      }
      if (lab.limewater) {
        const lx = left + vw + 120, ly = base - 170;
        draw(path(`M${lx},${ly} L${lx},${ly + 120} A22,22 0 0 0 ${lx + 44},${ly + 120} L${lx + 44},${ly}`, INK.black, 4), t0 + 0.8, 0.5);
        const lw = el("rect", { x: lx + 3, y: ly + 50, width: 38, height: 85, fill: "#e8f6ff", opacity: 0.9 }, page);
        tl.set(lw, { opacity: 0 }, 0); tl.to(lw, { opacity: 0.9, duration: 0.3 }, t0 + 1.2);
        tl.to(lw, { attr: { fill: "#f4f4f4" }, duration: span * 0.5 }, t0 + 2);
        write(text(lx - 20, ly - 14, "limewater", { size: 22, color: INK.grey }), t0 + 1.2, 0.5);
      }
      // What is in it, labelled, and what you see written beside it as it happens.
      const rs = s.reactants || [];
      const solidName = rs.find((r) => /^[A-Z][a-z]?$/.test(r.formula));
      const liquidName = rs.find((r) => r !== solidName);
      if (liquidName && liquid) write(text(Math.max(30, left - 250), liquidTop + 40, liquidName.name, { size: 24, color: INK.grey }), t0 + 0.3, 0.6);
      if (solidName && solid) write(text(Math.max(30, left - 250), base - 30, solidName.name, { size: 24, color: INK.grey }), t0 + 0.6, 0.5);
      if (!data.social) {
        const notes = (s.observations || []).slice(0, 3);
        let ny = 220;
        notes.forEach((o, k) => {
          const lines = wrap(o, 30).slice(0, 2);
          lines.forEach((l, j) => { write(text(760, ny, (j ? "   " : "• ") + l, { size: 26, color: INK.blue }), t0 + 1.2 + k * (span * 0.25) + j * 0.3, 0.6); ny += 34; });
          ny += 12;
        });
      }
      if (!s.reacts) write(text(cx - 110, base + 60, "no change", { size: 30, color: INK.grey }), t0 + span * 0.4, 0.6);
      return { at: t0 + Math.max(span, 1.5) };
    },
    chem_series(s, at, dur) {
      // The reactivity series as a ladder, most reactive at the top; the
      // metals of this question circled, an arrow from the higher one.
      at = newPage(at); cursorY = H;
      const list = s.series || [], hi = s.highlight || [];
      at = write(centered(64, "The reactivity series", { size: 36, color: INK.blue }), at, Math.min(0.9, dur * 0.12));
      const cols = data.social ? 1 : 2, per = Math.ceil(list.length / cols), rowH = Math.min(38, (H - 140) / per);
      const colX = (c) => (cols === 1 ? W / 2 - 140 : 330 + c * 360);
      const marks = [];
      const each = (dur * 0.45) / Math.max(1, list.length);
      list.forEach((m, k) => {
        const c = Math.floor(k / per), r = k % per, x = colX(c), y = 120 + r * rowH;
        const on = hi.includes(m.symbol);
        const t = text(x, y + rowH * 0.7, `${m.symbol}  ${m.name}`, { size: on ? 30 : 24, color: on ? INK.red : m.symbol === "H" ? INK.green : INK.black });
        at = write(t, at, each);
        if (on) marks.push(t);
      });
      write(text(cols === 1 ? W / 2 + 160 : 80, 150, "more", { size: 24, color: INK.grey }), at, 0.3);
      write(text(cols === 1 ? W / 2 + 160 : 80, 178, "reactive ↑", { size: 24, color: INK.grey }), at, 0.3);
      for (const t of marks) {
        const bb = t.getBBox();
        at = draw(sketchEllipse(bb.x + bb.width / 2, bb.y + bb.height / 2, bb.width / 2 + 18, bb.height / 2 + 6), at, 0.4);
      }
      return { at };
    },
    chem_word(s, at, dur) {
      at = newPage(at); cursorY = 110;
      at = write(text(LEFT, cursorY, "In words:", { size: 28, color: INK.blue }), at, dur * 0.2);
      cursorY += 56;
      for (const l of wrap(s.text, Math.round(48 / ZOOM)).slice(0, 3)) { at = write(text(LEFT, cursorY, l, { size: 36 }), at, (dur * 0.6) / 2); cursorY += 50 * ZOOM; }
      cursorY += 20;
      return { at };
    },
    chem_equation(s, at, dur) {
      // Symbols, unbalanced; the atoms counted on each side (red where they
      // differ); then the numbers in front, and the counts again, all green.
      at = room(330, at);
      const before = s.atoms.before, after = s.atoms.after;
      const els = [...new Set([...Object.keys(before.left), ...Object.keys(before.right)])];
      at = write(text(LEFT, cursorY, s.unbalanced, { size: 40 }), at, dur * 0.16);
      cursorY += 52;
      const tableTop = cursorY, colL = LEFT + 30, colR = LEFT + 230, rowH = Math.min(34, 160 / Math.max(1, els.length));
      write(text(colL - 30, tableTop, "atom", { size: 22, color: INK.grey }), at, 0.2);
      write(text(colL + 70, tableTop, "left", { size: 22, color: INK.grey }), at + 0.1, 0.2);
      write(text(colR - 30, tableTop, "right", { size: 22, color: INK.grey }), at + 0.2, 0.2);
      const nums = [];
      els.forEach((e, k) => {
        const y = tableTop + 30 + k * rowH, bad = (before.left[e] || 0) !== (before.right[e] || 0);
        const t = text(colL - 30, y, `${e}`, { size: 24 });
        const l = text(colL + 80, y, `${before.left[e] || 0}`, { size: 24, color: bad ? INK.red : INK.black });
        const r = text(colR - 20, y, `${before.right[e] || 0}`, { size: 24, color: bad ? INK.red : INK.black });
        at = write(t, at, 0.12); at = write(l, at, 0.12); at = write(r, at, 0.12);
        nums.push({ e, l, r, y });
      });
      cursorY = tableTop + 40 + els.length * rowH;
      const eq = text(LEFT, cursorY + 20, s.equation, { size: 44, color: INK.green });
      at = write(eq, at, dur * 0.22);
      // The counts become the balanced ones: the old fade out, the new (green)
      // fade in — tweens, so a rendered frame shows them as live does.
      for (const n of nums) {
        tl.to([n.l, n.r], { opacity: 0, duration: 0.25 }, at);
        const l2 = text(colL + 80, n.y, `${after.left[n.e] || 0}`, { size: 24, color: INK.green });
        const r2 = text(colR - 20, n.y, `${after.right[n.e] || 0}`, { size: 24, color: INK.green });
        at = write(l2, at, 0.1); at = write(r2, at, 0.1);
        const tick = text(colR + 40, n.y, "✓", { size: 24, color: INK.green });
        at = write(tick, at, 0.12);
      }
      const bb = eq.getBBox();
      at = draw(sketchBox(bb.x - 14, bb.y - 8, bb.width + 28, bb.height + 18, INK.green), at, 0.5);
      cursorY += 90;
      return { at };
    },
    chem_list(s, at, dur) {
      at = newPage(at); cursorY = 110;
      at = write(text(LEFT, cursorY, `${s.icon || "•"}  ${s.title}`, { size: 36, color: INK.blue }), at, Math.min(0.8, dur * 0.15));
      cursorY += 60;
      const items = (s.items || []).slice(0, 5);
      const per = (dur * 0.7) / Math.max(1, items.length);
      for (const it of items) {
        const lines = wrap(it, Math.round(52 / ZOOM)).slice(0, 2);
        lines.forEach((l, k) => { at = write(text(LEFT + (k ? 30 : 0), cursorY, (k ? "" : "• ") + l, { size: 30 }), at, per / lines.length); cursorY += 42 * ZOOM; });
        cursorY += 8;
        if (cursorY > H - 60) break;
      }
      return { at };
    },
    chem_result(s, at, dur) {
      at = room(200, at);
      at = write(text(LEFT, cursorY, s.title || "", { size: 38, color: s.title === "No reaction" ? INK.red : INK.green }), at, dur * 0.2);
      cursorY += 52;
      for (const l of wrap(s.text, Math.round(52 / ZOOM)).slice(0, 4)) { at = write(text(LEFT, cursorY, l, { size: 30 }), at, (dur * 0.6) / 3); cursorY += 42 * ZOOM; }
      cursorY += 20;
      return { at };
    },
  };
  const wb = {};

  // ── the vertical frame: captions and the countdown ──
  // A function of time, like the hand, so a rendered frame and a live one
  // agree. Captions come a phrase at a time with the spoken word lit.
  const capEl = document.getElementById("sc-caption"), countEl = document.getElementById("sc-count");
  const countN = document.getElementById("sc-n");
  let lastCap = "";
  function overlay(time) {
    if (!capEl) return;
    const starts = window.__starts || [];
    let i = -1;
    for (let k = 0; k < starts.length; k++) if (starts[k] <= time) i = k;
    const sc = scenes[i];
    if (!sc) { if (lastCap) { capEl.innerHTML = ""; lastCap = ""; } countEl.style.display = "none"; return; }
    const into = time - starts[i];
    if (sc.scene === "countdown") {
      countEl.style.display = "block";
      capEl.style.visibility = "hidden";
      countN.textContent = String(Math.max(1, Math.ceil((sc.hold || 5) - into)));
      return;
    }
    countEl.style.display = "none";
    capEl.style.visibility = "visible";
    const words = String(sc.caption || sc.say || "").split(/\s+/).filter(Boolean);
    const speak = Math.max(0.5, durations[i] - GAP);
    const k = Math.min(words.length - 1, Math.floor((into / speak) * words.length));
    const per = 7, c = Math.floor(Math.max(0, k) / per);
    const key = `${i}:${c}:${k}`;
    if (key === lastCap) return;
    lastCap = key;
    capEl.innerHTML = words.slice(c * per, c * per + per).map((w, j) => {
      const n = c * per + j;
      return `<span class="w${n < k ? " past" : n === k ? " on" : ""}">${w.replace(/[<&>]/g, "")}</span>`;
    }).join(" ");
  }

  // ── durations and the timeline ──
  const GAP = 0.4;
  const durations = scenes.map((s, i) => {
    const given = (data.durations || [])[i];
    if (given) return given + GAP;
    const words = String(s.say || "").split(/\s+/).length;
    return Math.max(2.4, words / 2.6) + GAP;
  });

  // ── the working, live: the engine's steps animated with KaTeX ──
  // What a rendered video shows with Manim, in the browser: the part done next
  // ringed, its sum worked under it, then turned into its result in place.
  // Every change is a timeline tween, so play, pause and seeking all work.
  const STEPS = (() => {
    if (!document.body.classList.contains("live") || !window.katex) return null;
    const css = document.createElement("style");
    css.textContent = `
      #wb-steps{position:absolute;inset:0;pointer-events:none;container-type:inline-size;opacity:0;visibility:hidden;
        display:flex;align-items:center;justify-content:center;background:#fdfdfb;font-family:serif;color:#1b1f2a}
      #wb-steps .stage{position:relative;width:100%;height:100%}
      #wb-steps .ln{position:absolute;left:0;right:0;top:30%;text-align:center;font-size:5.4cqw;white-space:nowrap;opacity:0}
      #wb-steps .side{position:absolute;left:0;right:0;top:58%;text-align:center;font-size:3.6cqw;opacity:0}
      #wb-steps .pt{display:inline-block;border-radius:.18em;padding:0 .08em;border:.08em solid transparent}
      #wb-steps .ans{border:.07em solid #15803d;color:#15803d;border-radius:.2em;padding:.05em .35em}
      #wb-steps .blue{color:#1d4ed8}#wb-steps .green{color:#15803d}#wb-steps .red{color:#c2410c}#wb-steps .amber{color:#d97706}`;
    document.head.appendChild(css);
    if (getComputedStyle(root).position === "static") root.style.position = "relative";
    const layer = document.createElement("div");
    layer.id = "wb-steps";
    layer.innerHTML = '<div class="stage"></div>';
    root.appendChild(layer);
    const stage = layer.firstChild;
    const RING = { blue: "#1d4ed8", green: "#15803d", red: "#c2410c", amber: "#d97706" };
    const tex = (t) => { try { return katex.renderToString(String(t || ""), { throwOnError: false }); } catch (e) { return ""; } };
    const make = (cls, html) => { const d = document.createElement("div"); d.className = cls; d.innerHTML = html; stage.appendChild(d); return d; };
    // A piece that starts or ends on an operator keeps its spacing: KaTeX
    // sets "\\times 2" on its own as a sign, "{}\\times 2" as an operation.
    const OPS = /^\s*(\\times|\\div|[-+=])/, OPS_END = /(\\times|\\div|[-+=])\s*$/;
    const spaced = (t) => (OPS.test(t) ? "{}" : "") + t + (OPS_END.test(t) ? "{}" : "");
    const part = (t, cls) => `<span class="pt ${cls || ""}">${tex(spaced(String(t || "")))}</span>`;
    let current = null;            // the line on the board now
    function show(line, at) {
      if (current && current !== line) tl.to(current, { opacity: 0, duration: 0.25 }, at);
      tl.fromTo(line, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.35 }, at);
      current = line;
    }
    return {
      can(s) { return Boolean(s.tex) && !(s.tex.done && !current); },
      enter(at) { tl.set(layer, { autoAlpha: 1 }, at); },
      leave(at) { tl.to(layer, { autoAlpha: 0, duration: 0.3 }, at); current = null; },
      play(s, at, dur) {
        const t = s.tex;
        if (t.line !== undefined) {                       // a setup, an equation, the answer
          const ans = s.scene === "answer";
          const ln = make("ln", ans ? `<span class="pt ans">${tex(t.line)}</span>` : tex(t.line));
          ln.dataset.tex = t.line;
          show(ln, at);
          return;
        }
        if (t.done) {                                     // the unknown alone: boxed
          const box = current && current.querySelector(".katex");
          if (box) tl.to(box.parentElement || box, { boxShadow: "0 0 0 .08em #15803d", borderRadius: ".2em", duration: 0.4 }, at + 0.2);
          return;
        }
        if (t.both) {                                     // the same thing done to both sides
          const c = t.colour;
          const both = make("ln", part(t.both[0]) + part(t.both[1], c) + part("=") + part(t.both[2]) + part(t.both[3], c));
          show(both, at);
          show(make("ln", tex(t.next)), at + Math.min(dur * 0.6, 2.4));
          return;
        }
        // A rewrite: ring the part, work it beside, turn it into its result.
        const c = t.colour, ring = RING[c] || RING.amber;
        if (!t.parts) { show(make("ln", tex(t.before)), at); show(make("ln", tex(t.after)), at + Math.min(dur * 0.6, 2.4)); return; }
        const [pre, mid, post] = t.parts;
        const line = make("ln", (pre.trim() ? part(pre) : "") + `<span class="pt mid">${tex(mid)}</span>`
                                + `<span class="pt res ${c}" style="display:none">${tex(t.res)}</span>` + (post.trim() ? part(post) : ""));
        const midEl = line.querySelector(".mid"), resEl = line.querySelector(".res");
        if (!current || current.dataset.tex !== t.before) show(line, at);
        else { tl.set(current, { opacity: 0 }, at); tl.set(line, { opacity: 1, y: 0 }, at); current = line; }
        line.dataset.tex = t.after;
        const side = make("side", `<span class="${c}">${tex(t.side)}</span>`);
        tl.to(midEl, { borderColor: ring, color: ring, duration: 0.35 }, at + 0.15);
        tl.fromTo(side, { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.4 }, at + 0.6);
        const turn = at + Math.max(1.2, Math.min(dur * 0.6, dur - 0.8));
        tl.to(midEl, { opacity: 0, scale: 0.6, duration: 0.25 }, turn);
        tl.set(midEl, { display: "none" }, turn + 0.25);
        tl.set(resEl, { display: "inline-block", opacity: 0, scale: 1.3 }, turn + 0.25);
        tl.to(resEl, { opacity: 1, scale: 1, duration: 0.35 }, turn + 0.25);
        tl.to(side, { opacity: 0, y: 10, duration: 0.3 }, turn + 0.3);
      },
    };
  })();
  const STEP_KINDS = { setup: 1, rewrite: 1, balance_start: 1, balance_move: 1, balance_done: 1, answer: 1 };

  function build() {
    let at = data.lead || 0.3;      // a social cut opens on its cover first
    let live = false;               // the KaTeX layer is up
    const starts = [];
    scenes.forEach((s, i) => {
      starts.push(at);
      tl.addLabel(`s${i}`, at);
      // A scene Manim animates is laid over the board afterwards: nothing drawn here.
      // Live, the working is animated with KaTeX on a layer over the board.
      const stepped = STEPS && STEP_KINDS[s.scene] && STEPS.can(s) && (s.scene !== "answer" || live);
      if (stepped && !live) { STEPS.enter(at); live = true; }
      if (!stepped && live) { STEPS.leave(at); live = false; }
      if (stepped) {
        try { STEPS.play(s, at, durations[i] - GAP); } catch (e) { console.warn("step", i, s.scene, e); }
        at += durations[i];
        return;
      }
      const fn = s.manim ? null : builders[s.scene];
      if (fn) {
        try { fn(s, at, durations[i] - GAP); } catch (e) { console.warn("scene", i, s.scene, e); }
      }
      at += durations[i];
    });
    tl.to({}, { duration: 0.6 }, at);   // a beat on the finished board
    const end = tl.duration(), clock = { t: 0 };
    track.sort((a, b) => a.t0 - b.t0);
    tl.fromTo(clock, { t: 0 }, { t: end, duration: end, ease: "none", onUpdate() { const p = handAt(clock.t); pose(p.x, p.y, p.tilt); overlay(clock.t); if (window.__onCover) window.__onCover(clock.t); if (window.__onFigure) window.__onFigure(clock.t); if (window.__onTime) window.__onTime(clock.t); } }, 0);
    pose(OFF.x, OFF.y, 0);
    window.__starts = starts;
    window.__total = tl.duration();
  }

  // ── live: the device's voice, scene by scene ──
  let current = -1, playing = false, current_audio = null;
  function stopAudio() { if (current_audio) { current_audio.onended = null; current_audio.pause(); current_audio = null; } }
  function voice() {
    const vs = speechSynthesis.getVoices(), want = data.voice || "en-KE";
    return vs.find((v) => v.lang === want) || vs.find((v) => v.lang.startsWith(want.slice(0, 2))) || null;
  }
  function playScene(i) {
    if (i >= scenes.length) { playing = false; status(); return; }
    current = i; status();
    const start = window.__starts[i], end = i + 1 < scenes.length ? window.__starts[i + 1] : window.__total;
    tl.seek(start); tl.play();
    tl.eventCallback("onUpdate", () => { if (tl.time() >= end - 0.05) tl.pause(); });
    const clip = (data.audio || [])[i];
    let spoken = !clip && !("speechSynthesis" in window);
    const advance = () => { if (!playing) return; if (spoken && (tl.paused() || tl.time() >= end - 0.06)) playScene(i + 1); else setTimeout(advance, 150); };
    if (clip) {
      // The server's voice — the one the MP4 has — not the device's.
      stopAudio();
      const a = new Audio(clip);
      current_audio = a;
      a.onended = () => { spoken = true; advance(); };
      a.onerror = () => { spoken = true; advance(); };
      a.play().catch(() => { spoken = true; advance(); });
    } else if (!spoken) {
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(scenes[i].say);
      const v = voice(); if (v) u.voice = v;
      u.rate = 0.95;
      u.onend = () => { spoken = true; advance(); };
      u.onerror = () => { spoken = true; advance(); };
      speechSynthesis.speak(u);
    } else setTimeout(() => { spoken = true; advance(); }, (end - start) * 1000);
    setTimeout(advance, 300);
  }
  function status() {
    const s = document.getElementById("wb-say"), c = document.getElementById("wb-count"), b = document.getElementById("wb-play");
    if (s) s.textContent = current >= 0 ? scenes[current].say : "";
    if (c) c.textContent = `${Math.max(0, current) + 1}/${scenes.length}`;
    if (b) b.textContent = playing ? "❚❚ Pause" : "▶ Play";
  }
  window.__wb = {
    play() { playing = true; playScene(current < 0 || current >= scenes.length - 1 ? 0 : current); },
    pause() { playing = false; tl.pause(); stopAudio(); if ("speechSynthesis" in window) speechSynthesis.cancel(); status(); },
    toggle() { playing ? this.pause() : this.play(); },
    next() { this.pause(); current = Math.min(scenes.length - 1, current + 1); tl.seek(i2t(current + 1) - 0.01); status(); },
    prev() { this.pause(); current = Math.max(0, current - 1); tl.seek(i2t(current + 1) - 0.01); status(); },
  };
  function i2t(i) { return i < scenes.length ? window.__starts[i] : window.__total; }

  // ── render: seek frame by frame ──
  window.__seek = (t) => { tl.pause(); tl.seek(t, false); return true; };

  const fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  // The teacher's model, if there is one, loads before the first frame is taken.
  window.__ready = Promise.race([fonts, new Promise((r) => setTimeout(r, 2500))])
    .then(() => Promise.race([window.__teacherReady || null, new Promise((r) => setTimeout(r, 20000))]))
    .then(() => Promise.race([window.__coverReady || null, new Promise((r) => setTimeout(r, 3000))]))
    .then(() => { build(); tl.seek(0); status(); return window.__total; });
})();
