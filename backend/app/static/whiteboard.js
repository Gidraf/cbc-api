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
    // A marker held at the tip: the point is at (0,0).
    const g = document.createElementNS(NS, "g");
    g.innerHTML = `<g transform="rotate(-38)">
      <rect x="-7" y="-118" width="14" height="96" rx="4" fill="#2b2f3a"/>
      <rect x="-7" y="-122" width="14" height="14" rx="3" fill="#c2410c"/>
      <rect x="-6" y="-24" width="12" height="18" fill="#9ca3af"/>
      <polygon points="-5,-6 5,-6 1,0 -1,0" fill="#1b1f2a"/></g>`;
    g.style.opacity = 0;
    svg.appendChild(g);
    return g;
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
  const handOn = (at) => tl.set(hand, { opacity: 1 }, at);

  function write(t, at, dur) {
    const bb = t.getBBox();
    const r = t._clip;
    tl.to(r, { attr: { width: bb.width + 8 }, duration: dur, ease: "none" }, at);
    tl.fromTo(hand, { x: bb.x, y: bb.y + bb.height * 0.8 },
      { x: bb.x + bb.width, y: bb.y + bb.height * 0.8, duration: dur, ease: "none" }, at);
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
      onUpdate() { p.style.strokeDashoffset = `${len * (1 - o.t)}`; const pt = p.getPointAtLength(len * o.t); gsap.set(hand, { x: pt.x, y: pt.y }); } }, at);
    return at + dur;
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
    handOn(at);
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
    tl.set(hand, { opacity: 0 }, at - 0.2);
    tl.to({}, { duration: 0.6 }, at);   // a beat on the finished board
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
