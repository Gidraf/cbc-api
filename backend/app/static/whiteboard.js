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

  let quietDraw = false;           // the apparatus is drawn in 3D: the marker draws no lines for it
  function draw(p, at, dur) {
    if (quietDraw) { p.style.display = "none"; return at + dur; }
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

  const sfx = (t, kind, gain, pitch) => { if (window.sfxAt) window.sfxAt(t, kind, gain, pitch); };
  const every = (kind, from, to, step, gain, pitch) => { for (let t = from; t < to; t += step) sfx(t, kind, gain, pitch); };
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
      at = write(centered(74, names + (s.condition ? `   (${s.condition})` : ""), { size: data.social ? 30 : 36, color: INK.blue }), at, Math.min(1.2, dur * 0.15));
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
      {
        // What you would hear at the bench.
        const end = t0 + span;
        if (lab.solid) sfx(t0 + 0.8, "drip", 0.5, 0.55);
        if (lab.bubbles) every("fizz", t0 + 1, end, 1.1, lab.slow ? 0.35 : 0.75);
        if (lab.drops) for (let k = 0; k < 6; k++) sfx(t0 + 1 + k * ((span * 0.45) / 6), "drip", 0.5, 1.1);
        if (lab.precipitate) { sfx(t0 + 1.2, "sparkle", 0.5); sfx(t0 + 1.2 + span * 0.3, "sparkle", 0.35, 0.9); }
        if (lab.flame || lab.burner) { sfx(t0 + 0.55, "whoosh", 0.6, 0.55); every("flame", t0 + 0.8, end, 1.3, 0.55); }
        if (/^#f{3,6}$/i.test(lab.flame || "")) { sfx(t0 + 0.9, "zap", 0.55); sfx(t0 + 1.4, "sparkle", 0.5, 1.2); }
        if (lab.coating) sfx(t0 + span * 0.5, "sparkle", 0.35, 0.8);
        if (lab.limewater) sfx(t0 + 2 + span * 0.5, "chime", 0.4);
        if (!s.reacts) sfx(t0 + span * 0.4, "thud", 0.5);
      }
      s._t0 = t0 - s0; s._span = span;                            // when the 3D bench starts reacting
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
      // The equation written unbalanced; the atoms counted on each side (red
      // where they differ); then the same formulas slide apart, the numbers
      // drop in front of them in green, the counts turn green, and the line
      // is boxed — one line that becomes balanced, not a second one.
      at = room(330, at);
      const before = s.atoms.before, after = s.atoms.after;
      const els = [...new Set([...Object.keys(before.left), ...Object.keys(before.right)])];
      const cr = s.coefficients.reactants, cp = s.coefficients.products;
      const parts = [];                       // {str, coef, op}
      s.reactants.forEach((f, k) => { if (k) parts.push({ str: "+", op: true }); parts.push({ str: f, coef: cr[k] }); });
      parts.push({ str: "→", op: true });
      s.products.forEach((f, k) => { if (k) parts.push({ str: "+", op: true }); parts.push({ str: f, coef: cp[k] }); });
      const measure = (str, size) => {
        const t = text(0, -400, str, { size });
        // A trailing subscript's way back to the line is a zero-width space,
        // which the handwriting font draws wide: not part of the formula.
        if (t.lastChild && t.lastChild.textContent === "\u200b") t.lastChild.remove();
        const w = t.getBBox().width; t.remove(); return w;
      };
      // As big as fits once the numbers are in.
      let size = 44;
      const widths = (sz) => parts.map((q) => ({ w: measure(q.str, sz), c: q.coef > 1 ? measure(String(q.coef), sz) + 4 : 0 }));
      const gap = () => 16 * ZOOM * size / 44;
      let ws = widths(size);
      const total = (sz, ws) => ws.reduce((t, m) => t + m.w + m.c + gap(), 0) - gap();
      const room_ = W - LEFT - 60;
      if (total(size, ws) > room_) { size = Math.max(24, Math.floor(size * room_ / total(size, ws))); ws = widths(size); }
      const y = cursorY + 6;
      const xsBefore = [], xsAfter = [], cx = [];
      let x0 = LEFT, x1 = LEFT;
      parts.forEach((q, k) => {
        xsBefore.push(x0); x0 += ws[k].w + gap();
        cx.push(x1); x1 += ws[k].c; xsAfter.push(x1); x1 += ws[k].w + gap();
      });
      const nodes = parts.map((q, k) => text(xsBefore[k], y, q.str, { size, color: q.op ? INK.grey : INK.black }));
      const per = (dur * 0.16) / parts.length;
      nodes.forEach((n) => { at = write(n, at, Math.max(0.12, per)); });
      cursorY += 58;
      const tableTop = cursorY, colL = LEFT + 30, colR = LEFT + 230, rowH = Math.min(34, 160 / Math.max(1, els.length));
      write(text(colL - 30, tableTop, "atom", { size: 22, color: INK.grey }), at, 0.2);
      write(text(colL + 70, tableTop, "left", { size: 22, color: INK.grey }), at + 0.1, 0.2);
      write(text(colR - 30, tableTop, "right", { size: 22, color: INK.grey }), at + 0.2, 0.2);
      const nums = [];
      els.forEach((e, k) => {
        const ty = tableTop + 30 + k * rowH, bad = (before.left[e] || 0) !== (before.right[e] || 0);
        const t = text(colL - 30, ty, `${e}`, { size: 24 });
        const l = text(colL + 80, ty, `${before.left[e] || 0}`, { size: 24, color: bad ? INK.red : INK.black });
        const r = text(colR - 20, ty, `${before.right[e] || 0}`, { size: 24, color: bad ? INK.red : INK.black });
        at = write(t, at, 0.12); at = write(l, at, 0.12); at = write(r, at, 0.12);
        nums.push({ e, l, r, y: ty });
      });
      cursorY = tableTop + 40 + els.length * rowH;
      // A balance: the side with more atoms dips; it levels as the numbers go in.
      const sum = (o) => Object.values(o).reduce((a, b) => a + b, 0);
      const Lb = sum(before.left), Rb = sum(before.right), La = sum(after.left);
      const tilt = -Math.max(-1, Math.min(1, (Lb - Rb) / Math.max(1, Lb, Rb))) * 16;
      const px = 1010, py = tableTop + 30, half = 150, origin = `${px} ${py}`;
      const stand = el("g", {}, page), beam = el("g", {}, page);
      el("path", { d: `M${px},${py} L${px - 38},${py + 165} L${px + 38},${py + 165} Z`, fill: "#e5e7eb", stroke: INK.black, "stroke-width": 3 }, stand);
      el("line", { x1: px - 75, y1: py + 168, x2: px + 75, y2: py + 168, stroke: INK.black, "stroke-width": 5, "stroke-linecap": "round" }, stand);
      el("line", { x1: px - half, y1: py, x2: px + half, y2: py, stroke: "#8b5e34", "stroke-width": 8, "stroke-linecap": "round" }, beam);
      [-1, 1].forEach((sd) => {
        const ex = px + sd * half;
        el("path", { d: `M${ex},${py} L${ex - 42},${py + 66} M${ex},${py} L${ex + 42},${py + 66}`, stroke: INK.grey, "stroke-width": 2, fill: "none" }, beam);
        el("path", { d: `M${ex - 54},${py + 66} Q${ex},${py + 98} ${ex + 54},${py + 66} Z`, fill: sd < 0 ? "#dbeafe" : "#fde68a", stroke: INK.black, "stroke-width": 2.5 }, beam);
      });
      el("circle", { cx: px, cy: py, r: 8, fill: INK.black }, beam);
      const panL = text(px - half - 44, py + 125, `${Lb} atoms`, { size: 22, color: INK.blue });
      const panR = text(px + half - 44, py + 125, `${Rb} atoms`, { size: 22, color: INK.blue });
      beam.appendChild(panL); beam.appendChild(panR);
      tl.fromTo([stand, beam], { opacity: 0 }, { opacity: 1, duration: 0.4 }, at);
      tl.fromTo(beam, { rotation: 0, svgOrigin: origin }, { rotation: tilt, svgOrigin: origin, duration: 0.8, ease: "power2.out" }, at + 0.2);
      if (tilt) sfx(at + 0.85, "thud", 0.7);
      write(panL, at + 0.3, 0.3); write(panR, at + 0.45, 0.3);
      // The morph: the formulas make room (their clips travel with them), the
      // numbers are written into the gaps.
      const slide = 0.7;
      sfx(at, "whoosh", 0.4, 0.9);
      nodes.forEach((n, k) => {
        const dx = xsAfter[k] - xsBefore[k];
        if (!dx) return;
        tl.to(n, { attr: { x: xsAfter[k] }, duration: slide, ease: "power2.inOut" }, at);
        tl.to(n._clip, { attr: { x: xsAfter[k] - 4 }, duration: slide, ease: "power2.inOut" }, at);
      });
      at += slide;
      const coefs = parts.filter((q) => q.coef > 1).length;
      const coefTime = (dur * 0.18) / Math.max(1, coefs);
      let done = 0;
      parts.forEach((q, k) => {
        if (!(q.coef > 1)) return;
        const c = text(cx[k], y, String(q.coef), { size, color: INK.green });
        tl.fromTo(c, { y: -18 }, { y: 0, duration: 0.3, ease: "bounce.out" }, at);
        sfx(at + 0.2, "pop", 0.6, 1 + done * 0.12);
        at = write(c, at, Math.min(0.5, Math.max(0.2, coefTime)));
        done++;
        if (done < coefs) tl.to(beam, { rotation: tilt * (1 - done / coefs) * 0.6, svgOrigin: origin, duration: 0.35, ease: "power1.out" }, at - 0.1);
      });
      // Level: it swings and settles; both pans now hold the same atoms.
      tl.to(beam, { rotation: 0, svgOrigin: origin, duration: 1.0, ease: "elastic.out(1, 0.4)" }, at);
      tl.to([panL, panR], { opacity: 0, duration: 0.2 }, at);
      const okL = text(px - half - 44, py + 125, `${La} atoms`, { size: 22, color: INK.green });
      const okR = text(px + half - 44, py + 125, `${La} atoms`, { size: 22, color: INK.green });
      beam.appendChild(okL); beam.appendChild(okR);
      write(okL, at + 0.2, 0.3); write(okR, at + 0.35, 0.3);
      sfx(at + 0.25, "ding", 0.6);
      // The counts become the balanced ones: the old fade out, the new (green)
      // fade in — tweens, so a rendered frame shows them as live does.
      for (const n of nums) {
        tl.to([n.l, n.r], { opacity: 0, duration: 0.25 }, at);
        const l2 = text(colL + 80, n.y, `${after.left[n.e] || 0}`, { size: 24, color: INK.green });
        const r2 = text(colR - 20, n.y, `${after.right[n.e] || 0}`, { size: 24, color: INK.green });
        at = write(l2, at, 0.1); at = write(r2, at, 0.1);
        const tick = text(colR + 40, n.y, "✓", { size: 24, color: INK.green });
        sfx(at, "tick", 0.5, 1.2);
        at = write(tick, at, 0.12);
      }
      const bb = nodes[0].getBBox(), right = x1 - gap();
      sfx(at, "chime", 0.55);
      at = draw(sketchBox(LEFT - 14, bb.y - 8, right - LEFT + 28, bb.height + 18, INK.green), at, 0.5);
      cursorY += 40;
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
    chem_hook(s, at, dur) {
      // Two tiles from the periodic table slide in from the sides and meet.
      const s0 = at;
      at = newPage(at); cursorY = H;
      const tiles = (s.tiles || []).slice(0, 2), size = 190, y = 170;
      const drawTile = (t, x) => {
        const holder = el("g", { transform: `translate(${x},${y})` }, page);
        const g = el("g", {}, holder);
        el("rect", { x: 0, y: 0, width: size, height: size, rx: 18, fill: t.colour || "#5b8db8", opacity: 0.18, stroke: t.colour || "#5b8db8", "stroke-width": 5 }, g);
        const z = el("text", { x: 16, y: 38, "font-size": 28, "font-family": FONT, fill: INK.grey }, g); z.textContent = t.Z || "";
        const sy = el("text", { x: size / 2, y: 122, "font-size": (t.symbol || "").length > 3 ? 46 : 84, "font-family": FONT, "text-anchor": "middle", fill: INK.black }, g);
        setRich(sy, t.symbol || "");
        const nm = el("text", { x: size / 2, y: 168, "font-size": 24, "font-family": FONT, "text-anchor": "middle", fill: INK.black }, g); nm.textContent = t.name || "";
        return g;
      };
      const meet = W / 2;
      if (tiles.length === 1) {
        const g = drawTile(tiles[0], meet - size / 2);
        tl.fromTo(g, { opacity: 0 }, { opacity: 1, duration: 0.6 }, at);
      } else if (tiles.length === 2) {
        const a = drawTile(tiles[0], meet - size - 30), b = drawTile(tiles[1], meet + 30);
        tl.fromTo(a, { x: -500, opacity: 0 }, { x: 0, opacity: 1, duration: 0.9, ease: "power2.out" }, at);
        sfx(at, "whoosh", 0.6); sfx(at + 0.88, "snap", 0.7);
        tl.fromTo(b, { x: 500, opacity: 0 }, { x: 0, opacity: 1, duration: 0.9, ease: "power2.out" }, at);
        // The meeting: a spark of lines between them.
        for (let k = 0; k < 10; k++) {
          const ang = (k / 10) * Math.PI * 2, r1 = 18, r2 = 60;
          const line = path(`M${meet + Math.cos(ang) * r1},${y + size / 2 + Math.sin(ang) * r1} L${meet + Math.cos(ang) * r2},${y + size / 2 + Math.sin(ang) * r2}`, "#f59e0b", 5);
          tl.set(line, { opacity: 0 }, 0);
          tl.to(line, { opacity: 1, duration: 0.15 }, at + 0.9);
          tl.to(line, { opacity: 0, duration: 0.5 }, at + 1.3);
        }
      }
      at += 1.2;
      // The writing is a fifth bigger in the social cut: fewer words a line there.
      const lines = wrap(s.question || "", Math.round(40 / ZOOM)).slice(0, 3);
      lines.forEach((l, k) => { at = write(centered(450 + k * 56 * ZOOM, l, { size: 44, color: INK.blue }), at, Math.min(1.4, (dur * 0.5) / lines.length)); });
      return { at: Math.max(at, s0 + dur * 0.9) };
    },
    chem_atom(s, at, dur) {
      // The Bohr model: the nucleus, then each shell drawn and filled with its
      // electrons, one at a time, as the voice counts them.
      // A pair of atoms (before they bond) share one page, side by side.
      const slot = s.short ? (s.slot || 0) : 0;
      if (!s.short || slot === 0) { at = newPage(at); cursorY = H; }
      // In 3D (chem3d.js) the atom has its own world, its titles on screen: the board stays clear.
      if (window.__chem3d) return { at: at + dur };
      const cx = s.short ? (slot ? W * 0.72 : W * 0.28) : W * 0.36, cy = 380;
      const ringGap = s.short ? 42 : 58, nucR = s.short ? 30 : 40;
      const nuc = el("circle", { cx, cy, r: nucR, fill: s.colour || "#999", opacity: 0.85, stroke: INK.black, "stroke-width": 3 }, page);
      at = show(nuc, at, 0.4);
      write(text(cx - nucR * 0.75, cy + 8, `${s.protons}p`, { size: s.short ? 20 : 26, color: "#fff" }), at, 0.3);
      if (!s.short) write(text(cx - 26, cy + 34, `${s.neutrons}n`, { size: 18, color: "#fff" }), at, 0.3);
      const total = (s.shells || []).reduce((a, b) => a + b, 0);
      const per = Math.max(0.12, Math.min(0.5, (dur * 0.55) / Math.max(1, total)));
      (s.shells || []).forEach((n, k) => {
        const r = nucR + ringGap * (k + 1);
        at = draw(path(`M${cx - r},${cy} a${r},${r} 0 1,0 ${2 * r},0 a${r},${r} 0 1,0 ${-2 * r},0`, INK.grey, 2.5), at, 0.35);
        for (let e = 0; e < n; e++) {
          const ang = -Math.PI / 2 + (e / n) * Math.PI * 2;
          const dot = el("circle", { cx: cx + Math.cos(ang) * r, cy: cy + Math.sin(ang) * r, r: s.short ? 7 : 9, fill: INK.blue }, page);
          tl.fromTo(dot, { opacity: 0, attr: { r: 0 } }, { opacity: 1, attr: { r: s.short ? 7 : 9 }, duration: per * 0.8 }, at);
          at += per;
        }
      });
      const label = `${s.symbol}  ${s.arrangement}`;
      at = write(text(s.short ? cx - 70 : W * 0.66, s.short ? 640 : 300, s.short ? label : `${s.name}`, { size: s.short ? 30 : 40, color: INK.blue }), at, 0.6);
      if (!s.short) {
        at = write(text(W * 0.66, 360, `${s.protons} protons, ${s.electrons} electrons`, { size: 28 }), at, 0.6);
        at = write(text(W * 0.66, 410, `${s.neutrons} neutrons`, { size: 28 }), at, 0.4);
        at = write(text(W * 0.66, 480, `Arrangement: ${s.arrangement}`, { size: 34, color: INK.green }), at, 0.7);
      }
      return { at };
    },
    chem_ionic(s, at, dur) {
      // Ionic bonding: the metal's outer electrons travel to the non-metal
      // atoms; then the ions, their charges in brackets, and the formula.
      at = newPage(at); cursorY = H;
      // In 3D (chem3d.js): the electrons fly, the ions form, the lattice builds, titled on screen.
      if (window.__chem3d) { newPage(at); return { at: at + dur }; }
      const nm = Math.min(3, s.counts[s.metal.symbol] || 1), nn = Math.min(3, s.counts[s.nonmetal.symbol] || 1);
      const scale = Math.max(nm, nn) > 1 ? 0.62 : 0.85;
      const atomsAt = (n, x) => Array.from({ length: n }, (_, k) => ({ x, y: 330 + (k - (n - 1) / 2) * (n > 2 ? 190 : 230) * scale }));
      const mPos = atomsAt(nm, W * 0.3), nPos = atomsAt(nn, W * 0.68);
      const drawOne = (a, p, outerFill) => {
        const nucR = 26 * scale, gap = 34 * scale, out = { slots: [], dots: [] };
        el("circle", { cx: p.x, cy: p.y, r: nucR, fill: a.colour, opacity: 0.85, stroke: INK.black, "stroke-width": 2 }, page);
        const lab = el("text", { x: p.x, y: p.y + 8, "font-size": 22 * scale + 4, "font-family": FONT, "text-anchor": "middle", fill: "#fff" }, page); lab.textContent = a.symbol;
        a.shells.forEach((n, k) => {
          const r = nucR + gap * (k + 1), outer = k === a.shells.length - 1;
          el("circle", { cx: p.x, cy: p.y, r, fill: "none", stroke: INK.grey, "stroke-width": 2 }, page);
          const places = outer ? 8 : n;
          for (let e = 0; e < places; e++) {
            const ang = -Math.PI / 2 + (e / places) * Math.PI * 2;
            const pt = { x: p.x + Math.cos(ang) * r, y: p.y + Math.sin(ang) * r };
            if (e < n) {
              const d = el("circle", { cx: pt.x, cy: pt.y, r: 6 * scale + 2, fill: outer ? outerFill : INK.blue }, page);
              if (outer) out.dots.push(d);
            } else if (outer) out.slots.push(pt);
          }
          out.r = r;
        });
        return out;
      };
      const ms = mPos.map((p) => drawOne(s.metal, p, INK.red)), ns = nPos.map((p) => drawOne(s.nonmetal, p, INK.blue));
      tl.fromTo(pages[pages.length - 1], { opacity: 0 }, { opacity: 1, duration: 0.6 }, at);
      at += 0.7;
      // Each electron: from metal atom i's outer shell to a free place on non-metal atom j.
      const used = ns.map(() => 0), taken = ms.map(() => 0);
      const per = Math.max(0.5, Math.min(1.3, (dur * 0.5) / Math.max(1, s.moves.length)));
      for (const mv of s.moves) {
        const i = Math.min(mv.from, ms.length - 1), j = Math.min(mv.to, ns.length - 1);
        const dot = ms[i].dots[taken[i]++], slot = ns[j].slots[used[j]++];
        if (!dot || !slot) continue;
        tl.to(dot, { attr: { cx: slot.x, cy: slot.y }, duration: per * 0.8, ease: "power2.inOut" }, at);
        at += per;
      }
      // The ions: charges in brackets.
      const SUP = { 1: "", 2: "²", 3: "³" };
      const charge = (n, sign) => `${n in SUP ? SUP[n] : n}${sign === "+" ? "⁺" : "⁻"}`;
      const qm = Math.abs(s.metal.ion_charge), qn = Math.abs(s.nonmetal.ion_charge);
      mPos.forEach((p) => { write(text(p.x + 70 * scale + 30, p.y - 80 * scale - 10, `[${s.metal.symbol}]${charge(qm, "+")}`, { size: 30, color: INK.red }), at, 0.5); });
      nPos.forEach((p) => { write(text(p.x + 95 * scale + 30, p.y - 95 * scale - 10, `[${s.nonmetal.symbol}]${charge(qn, "−")}`, { size: 30, color: INK.blue }), at, 0.5); });
      at += 0.8;
      const f = centered(680, `${s.formula}`, { size: 52, color: INK.green });
      at = write(f, at, 0.8);
      const bb = f.getBBox();
      at = draw(sketchBox(bb.x - 18, bb.y - 8, bb.width + 36, bb.height + 18, INK.green), at, 0.5);
      return { at };
    },
    chem_covalent(s, at, dur) {
      // Covalent bonding: the atoms' outer shells overlap and the shared
      // pairs sit where they overlap; the formula follows.
      at = newPage(at); cursorY = H;
      // In 3D (chem3d.js): the dot-and-cross overlap, then the real shape, titled on screen.
      if (window.__chem3d) { newPage(at); return { at: at + dur }; }
      const [A, B] = s.atoms, centre = A.symbol === s.centre ? A : B, outerA = centre === A ? B : A;
      const same = A.symbol === B.symbol;
      const k = same ? 1 : Math.min(4, s.counts[outerA.symbol] || 1);
      const cx = W / 2, cy = 340, rC = 30 + 36 * centre.shells.length, rO = 30 + 36 * outerA.shells.length;
      const drawShells = (a, x, y) => {
        el("circle", { cx: x, cy: y, r: 24, fill: a.colour, opacity: 0.85, stroke: INK.black, "stroke-width": 2 }, page);
        const t = el("text", { x, y: y + 8, "font-size": 22, "font-family": FONT, "text-anchor": "middle", fill: a.symbol === "H" ? INK.black : "#fff" }, page); t.textContent = a.symbol;
        a.shells.forEach((n, i) => el("circle", { cx: x, cy: y, r: 30 + 36 * (i + 1), fill: "none", stroke: INK.grey, "stroke-width": 2 }, page));
      };
      const order = same ? (centre.valency || 1) : (outerA.valency || 1);
      const d = rC + rO - 26;
      const angles = same ? [0] : k === 1 ? [0] : k === 2 ? [0, Math.PI] : k === 3 ? [-Math.PI / 2, Math.PI / 6, Math.PI * 5 / 6] : [-Math.PI / 4, Math.PI / 4, Math.PI * 3 / 4, -Math.PI * 3 / 4];
      const ccx = same ? cx - d / 2 : cx;
      drawShells(centre, ccx, cy);
      const outs = angles.map((a) => ({ a, x: ccx + Math.cos(a) * d, y: cy + Math.sin(a) * d }));
      outs.forEach((o) => drawShells(outerA, o.x, o.y));
      tl.fromTo(pages[pages.length - 1], { opacity: 0 }, { opacity: 1, duration: 0.6 }, at);
      at += 0.8;
      // Shared pairs in each overlap: one electron of each colour per pair.
      const per = Math.max(0.35, Math.min(0.9, (dur * 0.45) / Math.max(1, outs.length * order)));
      outs.forEach((o) => {
        const mx = ccx + Math.cos(o.a) * (rC - 13), my = cy + Math.sin(o.a) * (rC - 13);
        for (let p = 0; p < order; p++) {
          const off = (p - (order - 1) / 2) * 22, nx = -Math.sin(o.a) * off, ny = Math.cos(o.a) * off;
          const e1 = el("circle", { cx: mx + nx - Math.cos(o.a) * 7, cy: my + ny - Math.sin(o.a) * 7, r: 7, fill: INK.red }, page);
          const e2 = el("circle", { cx: mx + nx + Math.cos(o.a) * 7, cy: my + ny + Math.sin(o.a) * 7, r: 7, fill: INK.blue }, page);
          tl.fromTo([e1, e2], { opacity: 0 }, { opacity: 1, duration: per * 0.6 }, at);
          at += per;
        }
      });
      const f = centered(680, `${s.formula}`, { size: 52, color: INK.green });
      at = write(f, at, 0.8);
      write(text(60, 120, `${s.shared_pairs} shared pair${s.shared_pairs > 1 ? "s" : ""} of electrons`, { size: 28, color: INK.blue }), at - 0.6, 0.6);
      return { at };
    },
    chem_particles(s, at, dur) {
      // Balancing as particles: each molecule as its atoms; one of each
      // first (the counts below do not match), then copies appear for the
      // numbers in front until every atom is the same on both sides.
      at = newPage(at); cursorY = H;
      const R = 24;
      const drawMolecule = (m, x, y) => {
        const g = el("g", {}, page);
        let k = 0;
        const atoms = [];
        m.atoms.forEach(([e, n]) => { for (let i = 0; i < n; i++) atoms.push(e); });
        atoms.forEach((e, i) => {
          const ang = i === 0 ? 0 : ((i - 1) / Math.max(1, atoms.length - 1)) * Math.PI * 2;
          const px = i === 0 ? x : x + Math.cos(ang) * R * 1.7, py = i === 0 ? y : y + Math.sin(ang) * R * 1.7;
          el("circle", { cx: px, cy: py, r: R, fill: (s.colours || {})[e] || "#999", stroke: INK.black, "stroke-width": 1.5 }, g);
          const t = el("text", { x: px, y: py + 7, "font-size": 19, "font-family": "sans-serif", "text-anchor": "middle", fill: e === "H" ? INK.black : "#fff" }, g); t.textContent = e;
          k++;
        });
        return g;
      };
      const sides = [{ list: s.left, x0: 80, x1: W / 2 - 70 }, { list: s.right, x0: W / 2 + 70, x1: W - 80 }];
      write(text(W / 2 - 22, 300, "→", { size: 60 }), at, 0.3);
      const copies = [];
      sides.forEach((side) => {
        const colW = (side.x1 - side.x0) / Math.max(1, side.list.length);
        side.list.forEach((m, k) => {
          const x = side.x0 + colW * (k + 0.5);
          write(text(x - 30, 140, m.formula, { size: 30, color: INK.blue }), at, 0.3);
          for (let c = 0; c < m.count; c++) {
            const g = drawMolecule(m, x, 230 + c * Math.min(110, 300 / Math.max(1, m.count)));
            copies.push({ g, first: c === 0 });
          }
          side.label = side.label || [];
          side.label.push({ x: x - 62, count: m.count });
        });
      });
      // Stage 1: one particle of each.
      copies.filter((c) => c.first).forEach((c) => tl.fromTo(c.g, { opacity: 0 }, { opacity: 1, duration: 0.4 }, at));
      copies.filter((c) => !c.first).forEach((c) => tl.set(c.g, { opacity: 0 }, 0));
      at += 0.6;
      const els = [...new Set([...Object.keys(s.atoms.before.left), ...Object.keys(s.atoms.before.right)])];
      const tallyY = 600;
      const tallies = [];
      els.forEach((e, k) => {
        const x = 90 + k * Math.min(200, (W - 180) / Math.max(1, els.length));
        const bad = (s.atoms.before.left[e] || 0) !== (s.atoms.before.right[e] || 0);
        const t1 = text(x, tallyY, `${e}: ${s.atoms.before.left[e] || 0} | ${s.atoms.before.right[e] || 0}`, { size: 26, color: bad ? INK.red : INK.black });
        at = write(t1, at, 0.25);
        tallies.push({ e, x, t1 });
      });
      at += 0.4;
      // Stage 2: the copies, and the numbers in front.
      const extra = copies.filter((c) => !c.first);
      const per = Math.max(0.3, Math.min(0.9, (dur * 0.4) / Math.max(1, extra.length)));
      extra.forEach((c) => { tl.fromTo(c.g, { opacity: 0, scale: 0.4, transformOrigin: "50% 50%" }, { opacity: 1, scale: 1, duration: per * 0.7 }, at); at += per; });
      // The numbers in front, written as the copies appear.
      sides.forEach((side) => (side.label || []).forEach((n) => { if (n.count > 1) write(text(n.x, 140, `${n.count}`, { size: 34, color: INK.green }), at, 0.3); }));
      tallies.forEach((t) => {
        tl.to(t.t1, { opacity: 0, duration: 0.25 }, at);
        write(text(t.x, tallyY, `${t.e}: ${s.atoms.after.left[t.e] || 0} | ${s.atoms.after.right[t.e] || 0} ✓`, { size: 26, color: INK.green }), at + 0.2, 0.3);
      });
      return { at: at + 0.6 };
    },
    chem_separation(s, at, dur) {
      // The apparatus of the method, working: filtering, evaporating,
      // distilling, a magnet, a separating funnel, chromatography, sublimation.
      at = newPage(at); cursorY = H;
      const s0 = at, m = s.method, cx = data.social ? W / 2 : 380;
      // This mixture's names, for the labels (chem_separation's plan).
      const lk = s.look || {}, nm = (o, d) => (o && o.name) || d, names = (a, d) => (a && a.length ? a.map((x) => x.name).join(", ") : d);
      at = write(text(60, 70, s.name, { size: 38, color: INK.blue }), at, 0.6);
      const t0 = at, span = Math.max(2, s0 + dur - at - 0.3);
      s._t0 = t0 - s0; s._span = span;
      {
        const end = t0 + span;
        if (m === "magnet") { sfx(t0 + 0.6, "whoosh", 0.5, 0.8); for (let k = 0; k < 5; k++) sfx(t0 + 1.8 + k * 0.24, "snap", 0.45, 1 + k * 0.05); }
        else if (m === "filtration") every("drip", t0 + 0.8, end, 0.7, 0.45);
        else if (m === "dissolve") every("whoosh", t0 + 0.4, end, 1.4, 0.25, 1.4);
        else if (m === "evaporation" || m === "crystallisation") { sfx(t0 + 0.3, "whoosh", 0.5, 0.55); every("fizz", t0 + 1, end, 1.2, 0.5); sfx(t0 + span * 0.55, "sparkle", 0.45); sfx(t0 + span * 0.8, "sparkle", 0.4, 1.1); }
        else if (m === "distillation" || m === "fractional_distillation") { sfx(t0 + 0.3, "whoosh", 0.5, 0.55); every("fizz", t0 + 0.9, end, 1.2, 0.45); every("drip", t0 + 2, end, 0.8, 0.4, 1.1); }
        else if (m === "separating_funnel") { sfx(t0 + 0.8, "click", 0.7); every("drip", t0 + 0.9, Math.min(end, t0 + 1 + span * 0.6), 0.5, 0.4); sfx(Math.min(end, t0 + 1 + span * 0.6), "click", 0.6); }
        else if (m === "chromatography") { sfx(t0 + 0.5, "riser", 0.35); sfx(t0 + span * 0.55, "sparkle", 0.45); }
        else if (m === "sublimation") { sfx(t0 + 0.3, "whoosh", 0.5, 0.55); every("flame", t0 + 0.6, end, 1.3, 0.4); sfx(t0 + 1.6, "sparkle", 0.4); sfx(t0 + span * 0.6, "sparkle", 0.4, 1.15); }
      }
      const beaker = (x, y, w, h, fill) => {
        const liquid = fill ? el("rect", { x: x + 3, y: y + h * 0.45, width: w - 6, height: h * 0.55 - 3, fill, opacity: 0.85 }, page) : null;
        draw(path(`M${x - 6},${y} L${x},${y + 10} L${x},${y + h} L${x + w},${y + h} L${x + w},${y + 10} L${x + w + 6},${y}`, INK.black, 4), t0, 0.5);
        if (liquid) tl.fromTo(liquid, { opacity: 0 }, { opacity: 0.85, duration: 0.4 }, t0);
        return liquid;
      };
      const flame = (x, y) => {
        const f = el("path", { d: `M${x - 16},${y} Q${x},${y - 70} ${x + 16},${y} Z`, fill: "#4ea8ff", opacity: 0, stroke: "#1d4ed8", "stroke-width": 1.5 }, page);
        tl.to(f, { opacity: 0.9, duration: 0.3 }, t0 + 0.4);
        tl.to(f, { attr: { d: `M${x - 13},${y} Q${x + 5},${y - 84} ${x + 13},${y} Z` }, duration: 0.25, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.25)) }, t0 + 0.7);
      };
      const drops = (x, y1, y2, colour, n) => {
        for (let k = 0; k < n; k++) {
          const d = el("circle", { cx: x, cy: y1, r: 6, fill: colour, opacity: 0 }, page);
          tl.fromTo(d, { attr: { cy: y1 }, opacity: 0.9 }, { attr: { cy: y2 }, opacity: 0, duration: 0.6, ease: "power2.in", repeat: Math.max(0, Math.floor(span / (n * 0.3)) - 1), repeatDelay: n * 0.3 - 0.6 }, t0 + 0.8 + k * 0.3);
        }
      };
      const rising = (x, y, colour, n) => {
        for (let k = 0; k < n; k++) {
          const w = path(`M${x - 30 + k * 30},${y} q10,-15 0,-30 q-10,-15 0,-30`, colour, 3);
          tl.set(w, { opacity: 0 }, 0);
          tl.to(w, { opacity: 0.8, duration: 0.4, yoyo: true, repeat: Math.max(1, Math.floor(span / 0.8)) }, t0 + 1 + k * 0.25);
        }
      };
      if (m === "filtration" || m === "dissolve") {
        if (m === "filtration") {
          draw(path(`M${cx - 90},${250} L${cx},${370} L${cx + 90},${250} Z M${cx - 8},370 L${cx - 8},420 M${cx + 8},370 L${cx + 8},420`, INK.black, 4), t0, 0.6);
          for (let k = 0; k < 16; k++) {
            const r = el("circle", { cx: cx - 40 + rnd() * 80, cy: 270 + rnd() * 50, r: 5, fill: "#b08a5a", opacity: 0 }, page);
            tl.to(r, { opacity: 1, duration: 0.3 }, t0 + 0.8 + rnd() * span * 0.4);
          }
          write(text(cx + 110, 300, `residue: ${names(lk.residue, "solid")}`, { size: 24, color: INK.grey }), t0 + 1, 0.4);
          beaker(cx - 80, 430, 160, 170, "#dff3ff");
          drops(cx, 420, 520, "#7fbfff", 4);
          write(text(cx + 110, 560, `filtrate: ${nm(lk.filtrate, "liquid")}${lk.filtrate && lk.filtrate.in ? " solution" : ""}`, { size: 24, color: INK.grey }), t0 + 1.5, 0.4);
        } else {
          const liq = beaker(cx - 120, 300, 240, 260, "#dff3ff");
          for (let k = 0; k < 24; k++) {
            const dissolves = k % 2 === 0;
            const p = el("circle", { cx: cx - 100 + rnd() * 200, cy: 420 + rnd() * 120, r: 5, fill: dissolves ? "#f5f5f5" : "#b08a5a", stroke: "#999", "stroke-width": 0.6 }, page);
            tl.fromTo(p, { opacity: 0 }, { opacity: 1, duration: 0.3 }, t0 + 0.4);
            if (dissolves) tl.to(p, { opacity: 0, duration: span * 0.5 }, t0 + 1);
            else tl.to(p, { attr: { cy: 545 - rnd() * 10 }, duration: span * 0.5 }, t0 + 1);
          }
          if (liq) tl.to(liq, { attr: { fill: "#eef7ff" }, duration: span * 0.5 }, t0 + 1);
        }
      } else if (m === "evaporation" || m === "crystallisation") {
        const dish = path(`M${cx - 110},380 Q${cx},470 ${cx + 110},380`, INK.black, 4);
        draw(dish, t0, 0.5);
        const liq = el("path", { d: `M${cx - 100},388 Q${cx},460 ${cx + 100},388 Z`, fill: "#bfe3ff", opacity: 0.9 }, page);
        tl.fromTo(liq, { opacity: 0 }, { opacity: 0.9, duration: 0.3 }, t0);
        tl.to(liq, { attr: { d: `M${cx - 50},430 Q${cx},450 ${cx + 50},430 Z` }, duration: span * 0.7 }, t0 + 1);
        draw(path(`M${cx - 120},480 L${cx + 120},480 M${cx - 100},480 L${cx - 130},600 M${cx + 100},480 L${cx + 130},600`, INK.grey, 4), t0 + 0.2, 0.5);
        flame(cx, 590);
        rising(cx, 370, INK.grey, 3);
        for (let k = 0; k < 10; k++) {
          const c = el("rect", { x: cx - 60 + rnd() * 120, y: 425 + rnd() * 20, width: 10, height: 10, fill: "#ffffff", stroke: "#888", "stroke-width": 1, opacity: 0 }, page);
          tl.to(c, { opacity: 1, duration: 0.4 }, t0 + span * 0.5 + rnd() * span * 0.4);
        }
      } else if (m === "distillation" || m === "fractional_distillation") {
        const fx = cx - 120;
        draw(path(`M${fx - 70},420 A70,70 0 1 0 ${fx + 70},420 A70,70 0 1 0 ${fx - 70},420 M${fx - 18},352 L${fx - 18},${m === "fractional_distillation" ? 200 : 290} M${fx + 18},352 L${fx + 18},${m === "fractional_distillation" ? 200 : 290}`, INK.black, 4), t0, 0.6);
        const top = m === "fractional_distillation" ? 200 : 290;
        show(el("rect", { x: fx - 60, y: 430, width: 120, height: 50, rx: 25, fill: "#bfe3ff", opacity: 0.9 }, page), t0, 0.3);
        draw(path(`M${fx + 18},${top + 20} L${fx + 330},${top + 150}`, INK.black, 10), t0 + 0.4, 0.6);
        draw(path(`M${fx + 40},${top + 10} L${fx + 340},${top + 135}`, "#5b8db8", 4), t0 + 0.6, 0.5);
        write(text(fx + 180, top + 40, "condenser", { size: 22, color: INK.grey }), t0 + 0.8, 0.4);
        flame(fx, 560);
        beaker(fx + 300, top + 170, 120, 140, "#dff3ff");
        drops(fx + 335, top + 160, top + 260, "#7fbfff", 3);
        rising(fx, 345, INK.grey, 2);
      } else if (m === "separating_funnel") {
        draw(path(`M${cx - 90},200 Q${cx - 100},380 ${cx - 10},470 L${cx - 10},530 M${cx + 90},200 Q${cx + 100},380 ${cx + 10},470 L${cx + 10},530 M${cx - 90},200 L${cx + 90},200`, INK.black, 4), t0, 0.6);
        const top = el("path", { d: `M${cx - 86},230 L${cx + 86},230 Q${cx + 92},300 ${cx + 70},330 L${cx - 70},330 Q${cx - 92},300 ${cx - 86},230 Z`, fill: "#f6d365", opacity: 0.9 }, page);
        const low = el("path", { d: `M${cx - 70},330 L${cx + 70},330 Q${cx + 60},420 ${cx},468 Q${cx - 60},420 ${cx - 70},330 Z`, fill: "#7fbfff", opacity: 0.9 }, page);
        tl.fromTo([top, low], { opacity: 0 }, { opacity: 0.9, duration: 0.4 }, t0);
        tl.to(low, { attr: { d: `M${cx - 30},440 L${cx + 30},440 Q${cx + 20},460 ${cx},468 Q${cx - 20},460 ${cx - 30},440 Z` }, duration: span * 0.6 }, t0 + 1);
        tl.to(top, { attr: { d: `M${cx - 70},300 L${cx + 70},300 Q${cx + 60},400 ${cx},440 Q${cx - 60},400 ${cx - 70},300 Z` }, duration: span * 0.6 }, t0 + 1);
        beaker(cx - 70, 560, 140, 110, "#7fbfff");
        drops(cx, 530, 610, "#7fbfff", 3);
        write(text(cx + 120, 270, `${nm(lk.top, "oil")} (less dense)`, { size: 22, color: INK.grey }), t0 + 0.8, 0.4);
        write(text(cx + 120, 390, `${nm(lk.bottom, "water")} (denser)`, { size: 22, color: INK.grey }), t0 + 1, 0.4);
      } else if (m === "magnet") {
        draw(path(`M${cx - 200},520 L${cx + 200},520`, INK.grey, 3), t0, 0.4);
        const iron = [];
        for (let k = 0; k < 30; k++) {
          const isIron = k % 2 === 0;
          const p = el("circle", { cx: cx - 160 + rnd() * 320, cy: 500 + rnd() * 14, r: 6, fill: isIron ? "#555" : "#e6c200" }, page);
          tl.fromTo(p, { opacity: 0 }, { opacity: 1, duration: 0.3 }, t0 + 0.2);
          if (isIron) iron.push(p);
        }
        const mag = el("path", { d: `M${cx - 50},220 L${cx - 50},320 A50,50 0 0 0 ${cx + 50},320 L${cx + 50},220`, fill: "none", stroke: "#c2410c", "stroke-width": 22 }, page);
        tl.fromTo(mag, { x: -280, opacity: 0 }, { x: 0, opacity: 1, duration: 1 }, t0 + 0.6);
        iron.forEach((p, k) => tl.to(p, { attr: { cx: cx - 40 + (k % 8) * 11, cy: 380 + Math.floor(k / 8) * 10 }, duration: 0.8, ease: "power2.in" }, t0 + 1.8 + k * 0.05));
      } else if (m === "chromatography") {
        beaker(cx - 100, 250, 200, 360, null);
        const solvent = el("rect", { x: cx - 96, y: 560, width: 192, height: 46, fill: "#dff3ff", opacity: 0.9 }, page);
        tl.fromTo(solvent, { opacity: 0 }, { opacity: 0.9, duration: 0.3 }, t0);
        show(el("rect", { x: cx - 40, y: 230, width: 80, height: 360, fill: "#ffffff", stroke: "#bbb", "stroke-width": 2 }, page), t0, 0.3);
        draw(path(`M${cx - 36},540 L${cx + 36},540`, INK.grey, 2), t0 + 0.3, 0.3);
        const wet = el("rect", { x: cx - 38, y: 588, width: 76, height: 0, fill: "#dff3ff", opacity: 0.8 }, page);
        tl.to(wet, { attr: { y: 260, height: 328 }, duration: span * 0.8, ease: "none" }, t0 + 0.6);
        [["#e8261b", 0.35], ["#1d4ed8", 0.6], ["#e6c200", 0.85]].forEach(([c, f]) => {
          const sp = el("circle", { cx, cy: 540, r: 9, fill: c, opacity: 0.9 }, page);
          tl.to(sp, { attr: { cy: 540 - 280 * f }, duration: span * 0.8, ease: "none" }, t0 + 0.6);
        });
      } else if (m === "sublimation") {
        draw(path(`M${cx - 110},450 Q${cx},520 ${cx + 110},450`, INK.black, 4), t0, 0.5);
        draw(path(`M${cx - 100},430 L${cx},270 L${cx + 100},430 M${cx - 8},270 L${cx - 8},200 M${cx + 8},270 L${cx + 8},200`, INK.black, 4), t0 + 0.2, 0.5);
        for (let k = 0; k < 14; k++) {
          const p = el("circle", { cx: cx - 60 + rnd() * 120, cy: 470 + rnd() * 10, r: 5, fill: k % 2 ? "#6d28d9" : "#b08a5a" }, page);
          tl.fromTo(p, { opacity: 0 }, { opacity: 1, duration: 0.3 }, t0 + 0.3);
          if (k % 2) {
            tl.to(p, { attr: { cy: 330 + rnd() * 60, cx: cx - 50 + rnd() * 100 }, duration: span * 0.5 }, t0 + 1 + rnd());
          }
        }
        flame(cx, 600);
        rising(cx, 440, "#6d28d9", 3);
      }
      // The steps, written beside the apparatus as it works.
      if (!data.social) {
        let y = 200;
        const per = (span * 0.8) / Math.max(1, (s.steps || []).length);
        // A plan's step comes as what happens and why (s.look); older ones as numbered steps.
        const why = Boolean(s.look) && (s.steps || []).length === 2;
        (s.steps || []).slice(0, 4).forEach((st, k) => {
          const lead = why ? (k ? "Why: " : "") : `${k + 1}. `;
          const lines = wrap(st, 34).slice(0, why ? 6 : 3);
          if (y + lines.length * 30 > H - 40) return;
          lines.forEach((l, j) => { write(text(760, y, (j ? (why ? "" : "    ") : lead) + l, { size: 23, color: why && k ? INK.green : INK.blue }), t0 + 0.5 + k * per + j * 0.2, 0.5); y += 30; });
          y += 16;
        });
      }
      return { at: t0 + span };
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
  // The bench and the separations in 3D (lab3d.js): the board keeps only
  // its words — the names, the gas, the labels, the observations, the steps.
  ["chem_lab", "chem_separation"].forEach((k) => {
    const flat = builders[k];
    builders[k] = function (s, at, dur) {
      if (!(window.__chem3d && window.__lab3d)) return flat(s, at, dur);
      quietDraw = true;
      try {
        const out = flat(s, at, dur);
        for (const n of [...page.children]) if (n.tagName !== "text") n.style.display = "none";
        return out;
      } finally { quietDraw = false; }
    };
  });
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
    tl.fromTo(clock, { t: 0 }, { t: end, duration: end, ease: "none", onUpdate() { const p = handAt(clock.t); pose(p.x, p.y, p.tilt); overlay(clock.t); if (window.__onCover) window.__onCover(clock.t); if (window.__onFigure) window.__onFigure(clock.t); if (window.__onTime) window.__onTime(clock.t); if (window.__onChem3d) window.__onChem3d(clock.t); if (window.__sfxTick) window.__sfxTick(clock.t, playing); } }, 0);
    pose(OFF.x, OFF.y, 0);
    window.__starts = starts;
    window.__total = tl.duration();
    if (window.__sfx3d) window.__sfx3d(starts, window.__total);   // the 3D scenes' sounds, on this clock
    (window.__sfx || []).sort((a, b) => a.t - b.t);
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
    play() { if (window.__sfxUnlock) window.__sfxUnlock(); playing = true; playScene(current < 0 || current >= scenes.length - 1 ? 0 : current); },
    pause() { playing = false; tl.pause(); stopAudio(); if ("speechSynthesis" in window) speechSynthesis.cancel(); status(); },
    toggle() { playing ? this.pause() : this.play(); },
    next() { this.pause(); current = Math.min(scenes.length - 1, current + 1); tl.seek(i2t(current + 1) - 0.01); status(); },
    prev() { this.pause(); current = Math.max(0, current - 1); tl.seek(i2t(current + 1) - 0.01); status(); },
  };
  function i2t(i) { return i < scenes.length ? window.__starts[i] : window.__total; }

  // ── render: seek frame by frame ──
  window.__seek = (t) => { tl.pause(); tl.seek(t, false); return true; };

  // Asked for by name: `fonts.ready` alone resolves before a font nothing has
  // drawn with yet is fetched, and the board would be measured in a fallback.
  const fonts = document.fonts && document.fonts.ready
    ? Promise.all([document.fonts.load(`34px ${FONT.split(",")[0]}`).catch(() => null), document.fonts.ready]) : Promise.resolve();
  // The teacher's model, if there is one, loads before the first frame is taken.
  window.__ready = Promise.race([fonts, new Promise((r) => setTimeout(r, 2500))])
    .then(() => Promise.race([window.__teacherReady || null, new Promise((r) => setTimeout(r, 20000))]))
    .then(() => Promise.race([window.__coverReady || null, new Promise((r) => setTimeout(r, 3000))]))
    .then(() => { build(); tl.seek(0); status(); return window.__total; });
})();
