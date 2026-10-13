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
    const lean = (-(1 - Math.max(0, Math.min(1, x / W))) * 14 + 4) * (hand._photo ? 0.4 : 1);
    hand.setAttribute("transform", `translate(${x.toFixed(1)},${y.toFixed(1)})`);
    hand._tilt.setAttribute("transform", `rotate(${(lean + (tilt || 0)).toFixed(2)})`);
  }

  // ── marks ──
  let page = el("g", {});
  const pages = [page];
  let clipN = 0;

  function text(x, y, str, opt) {
    opt = opt || {};
    const t = el("text", { x, y, "font-size": opt.size || 34, fill: opt.color || INK.black,
      "font-family": FONT, "text-anchor": "start" }, page);
    t.textContent = str;
    const id = `c${clipN++}`;
    const cp = el("clipPath", { id }, defs);
    const r = el("rect", { x: x - 4, y: y - (opt.size || 34) * 1.1, width: 0, height: (opt.size || 34) * 1.5 }, cp);
    t.setAttribute("clip-path", `url(#${id})`);
    t._clip = r;
    return t;
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
      const lines = wrap(s.text, 46).slice(0, 5);
      const ctx = s.context ? wrap(s.context, 60).slice(0, 2) : [];
      const per = (dur * 0.8) / Math.max(1, lines.length + ctx.length);
      let y = 120;
      for (const c of ctx) { at = write(text(LEFT, y, c, { size: 26, color: INK.grey }), at, per); y += 40; }
      if (ctx.length) y += 10;
      for (const l of lines) { at = write(text(LEFT, y, l, { size: 40 }), at, per); y += 58; }
      cursorY = y + 20;
      return { at, y };
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
      const words = `Answer: ${s.option ? s.option + ".  " : ""}${plain(s.text)}`;
      let t;
      if (cursorY + 120 > H - 40) {
        // A full board keeps its working: the answer goes in the top corner.
        const probe = text(0, -100, words, { size: 46 });
        const w = probe.getBBox().width;
        probe.remove();
        t = text(W - w - 80, 92, words, { size: 46, color: INK.green });
      } else {
        t = text(LEFT, cursorY + 20, words, { size: 46, color: INK.green });
        cursorY += 110;
      }
      at = write(t, at, dur * 0.45);
      const bb = t.getBBox();
      at = draw(sketchBox(bb.x - 18, bb.y - 10, bb.width + 36, bb.height + 20), at, dur * 0.25);
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
  };
  const wb = {};

  // ── durations and the timeline ──
  const GAP = 0.4;
  const durations = scenes.map((s, i) => {
    const given = (data.durations || [])[i];
    if (given) return given + GAP;
    const words = String(s.say || "").split(/\s+/).length;
    return Math.max(2.4, words / 2.6) + GAP;
  });

  function build() {
    let at = 0.3;
    const starts = [];
    scenes.forEach((s, i) => {
      starts.push(at);
      tl.addLabel(`s${i}`, at);
      const fn = builders[s.scene];
      if (fn) {
        try { fn(s, at, durations[i] - GAP); } catch (e) { console.warn("scene", i, s.scene, e); }
      }
      at += durations[i];
    });
    tl.to({}, { duration: 0.6 }, at);   // a beat on the finished board
    const end = tl.duration(), clock = { t: 0 };
    track.sort((a, b) => a.t0 - b.t0);
    tl.fromTo(clock, { t: 0 }, { t: end, duration: end, ease: "none", onUpdate() { const p = handAt(clock.t); pose(p.x, p.y, p.tilt); } }, 0);
    pose(OFF.x, OFF.y, 0);
    window.__starts = starts;
    window.__total = tl.duration();
  }

  // ── live: the device's voice, scene by scene ──
  let current = -1, playing = false;
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
    let spoken = !("speechSynthesis" in window);
    const advance = () => { if (!playing) return; if (spoken && (tl.paused() || tl.time() >= end - 0.06)) playScene(i + 1); else setTimeout(advance, 150); };
    if (!spoken) {
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
    pause() { playing = false; tl.pause(); if ("speechSynthesis" in window) speechSynthesis.cancel(); status(); },
    toggle() { playing ? this.pause() : this.play(); },
    next() { this.pause(); current = Math.min(scenes.length - 1, current + 1); tl.seek(i2t(current + 1) - 0.01); status(); },
    prev() { this.pause(); current = Math.max(0, current - 1); tl.seek(i2t(current + 1) - 0.01); status(); },
  };
  function i2t(i) { return i < scenes.length ? window.__starts[i] : window.__total; }

  // ── render: seek frame by frame ──
  window.__seek = (t) => { tl.pause(); tl.seek(t, false); return true; };

  const fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  window.__ready = Promise.race([fonts, new Promise((r) => setTimeout(r, 2500))]).then(() => { build(); tl.seek(0); status(); return window.__total; });
})();
