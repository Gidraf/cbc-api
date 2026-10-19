/*
 * Devcast: a developer's screen, narrated — VS Code (Dark+), a terminal, and
 * Word / Excel windows for the result. The frame at time t is a pure function
 * of t, so `window.__seek(t)` (headless capture) and live play draw the same.
 * Timing is whiteboard.js's: a 0.3 s lead-in, each scene its voice plus a
 * 0.4 s gap, 0.6 s on the last frame — services/whiteboard._starts agrees.
 *
 * Expects: window.DC_DATA = {scenes, durations?, audio?, size, brand, badge, repo}.
 */
(function () {
  "use strict";
  const data = window.DC_DATA || {};
  const scenes = data.scenes || [];
  const W = (data.size || [1080, 1080])[0];
  const brand = data.brand || {};
  const repo = data.repo || "cbc-api";
  const LEAD = 0.3, GAP = 0.4, TAIL = 0.6, TYPE_SHARE = 0.72;

  const durations = scenes.map((s, i) => {
    const given = (data.durations || [])[i];
    if (given) return given + GAP;
    const words = String(s.say || "").split(/\s+/).filter(Boolean).length;
    return Math.max(2.4, words / 2.6) + GAP;
  });
  const starts = [];
  let total = LEAD;
  durations.forEach((d) => { starts.push(total); total += d; });
  total += TAIL;

  const $ = (id) => document.getElementById(id);
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const ease = (x) => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ESC[c]);
  const mmss = (s) => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

  // ── syntax colouring (Dark+) ──
  const KW = {
    js: "async await break case catch class const continue default delete do else export extends finally for from function if import in instanceof let new of return static super switch this throw try typeof var void while yield true false null undefined interface type enum as",
    py: "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield true false none self",
    vba: "as boolean byref byval call case const dim do each else elseif end err exit false for function if in is long loop me new next not nothing object on optional or private public redim resume select set string sub then to true variant wend while with",
    bash: "if then else fi for do done case esac function in export local return",
    json: "true false null",
    xml: "",
  };
  const CONTROL = new Set("if else elif elseif for while do loop next wend return await try catch except finally throw raise import export from switch select case break continue exit yield with then fi done".split(" "));
  const KWS = {};
  Object.keys(KW).forEach((k) => { KWS[k] = new Set(KW[k].split(" ").filter(Boolean)); });
  const LANG = { js: "JavaScript", ts: "TypeScript", py: "Python", vba: "VBA", bash: "Shell", json: "JSON", xml: "XML", gs: "Apps Script" };
  const ALIAS = { ts: "js", gs: "js", sh: "bash", html: "xml" };
  const lang = (l) => ALIAS[l] || (KW[l] !== undefined ? l : "js");

  const RX = {};
  function rx(l) {
    if (RX[l]) return RX[l];
    const comment = { py: "#.*", bash: "#.*", vba: "'.*", json: "(?!)", xml: "<!--.*?-->" }[l] || "\\/\\/.*";
    const str = l === "vba" ? '"(?:[^"]|"")*"?'
      : String.raw`"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?` + (l === "js" ? "|`(?:\\\\.|[^`\\\\])*`?" : "");
    return (RX[l] = new RegExp(`(${comment})|(${str})|(\\b\\d+(?:\\.\\d+)?\\b)|([A-Za-z_$][\\w$]*)|(\\s+)|([\\s\\S])`, "g"));
  }
  function tokens(line, l) {
    const out = [], re = rx(l), kws = KWS[l];
    let m, punct = "";
    re.lastIndex = 0;
    while (re.lastIndex < line.length && (m = re.exec(line))) {
      const [all, com, str, num, word, ws] = m;
      const after = line.slice(re.lastIndex);
      let cls = "";
      if (com) cls = "cm";
      else if (str) cls = l === "json" && /^\s*:/.test(after) ? "pr" : "st";
      else if (num) cls = "nu";
      else if (word) {
        const w = word.toLowerCase();
        if (l === "xml" && /<\/?$/.test(punct)) cls = "tg";
        else if (kws.has(l === "js" || l === "bash" ? word : w)) cls = CONTROL.has(w) ? "kc" : "kw";
        else if (/^\s*\(/.test(after)) cls = "fn";
        else if (punct.endsWith(".")) cls = "pr";
        else if (l !== "vba" && /^[A-Z]/.test(word)) cls = "ty";
        else cls = "id";
      } else if (!ws) cls = "pu";
      out.push([cls, all]);
      if (!ws) punct = cls === "pu" ? punct + all : "";
    }
    return out;
  }
  function slice(toks, n) {
    let out = "", left = n;
    for (const [cls, text] of toks) {
      if (left <= 0) break;
      const part = text.slice(0, left);
      left -= part.length;
      out += cls ? `<span class="${cls}">${esc(part)}</span>` : esc(part);
    }
    return out;
  }

  // ── per-scene preparation ──
  const lastCode = [], filesUpTo = [];
  const CODE = {};
  const seenFiles = [];
  let lc = -1;
  scenes.forEach((s, i) => {
    if (s.scene === "code") {
      lc = i;
      const f = String(s.file || "untitled");
      const k = seenFiles.indexOf(f);
      if (k >= 0) seenFiles.splice(k, 1);
      seenFiles.push(f);
    }
    lastCode.push(lc);
    filesUpTo.push(seenFiles.slice(-4));
  });
  const allFiles = [], fileLang = {};
  scenes.forEach((s) => {
    if (s.scene !== "code") return;
    const f = String(s.file || "untitled");
    if (!allFiles.includes(f)) allFiles.push(f);
    fileLang[f] = lang(s.lang);
  });

  function prepCode(i) {
    if (CODE[i]) return CODE[i];
    const s = scenes[i], l = lang(s.lang);
    const raw = String(s.code || "").replace(/\t/g, "  ").replace(/\s+$/, "").split("\n");
    const lens = raw.map((x) => x.length);
    const longest = Math.max(20, ...lens);
    const editor = $("dc-editor");
    const room = (editor ? editor.clientWidth : W - 60) - 110;
    const fs = clamp(Math.floor(room / (longest * 0.61)), 15, 26);
    const lh = Math.round(fs * 1.55);
    const pre = raw.slice(0, Math.max(0, s.prefilled || 0)).reduce((a, x) => a + x.length + 1, 0);
    const totalChars = lens.reduce((a, x) => a + x, 0) + Math.max(0, raw.length - 1);
    return (CODE[i] = { lines: raw.map((x) => tokens(x, l)), lens, fs, lh, pre: Math.min(pre, totalChars),
      total: totalChars, hl: new Set((s.highlight || []).map(Number)), label: LANG[s.lang] || LANG[l] || "Plain Text",
      typed: s.typed !== false });
  }

  function phrases(text) {
    const words = String(text || "").split(/\s+/).filter(Boolean), out = [];
    let cur = [];
    words.forEach((w) => {
      cur.push(w);
      if (cur.length >= 8 || (cur.length >= 3 && /[.,;:?!]$/.test(w))) { out.push(cur); cur = []; }
    });
    if (cur.length) out.push(cur);
    return out;
  }
  const PHRASES = scenes.map((s) => phrases(s.say));

  // ── drawing ──
  function sceneAt(t) { let i = 0; while (i + 1 < scenes.length && t >= starts[i + 1]) i++; return i; }

  function drawTabs(i, ci) {
    const active = ci >= 0 ? String(scenes[ci].file || "untitled") : "";
    const files = filesUpTo[i];
    $("dc-tabs").innerHTML = files.length
      ? files.map((f) => `<div class="tab${f === active ? " on" : ""}"><i class="dot ${esc(fileLang[f])}"></i>${esc(f.split("/").pop())}</div>`).join("")
      : `<div class="tab on"><i class="dot vs"></i>Welcome</div>`;
    $("dc-crumbs").innerHTML = active ? [repo, ...active.split("/")].map(esc).join(' <b>›</b> ') : "";
    $("dc-wt").textContent = `${active ? active.split("/").pop() + " — " : ""}${repo} — Visual Studio Code`;
    const side = $("dc-files");
    if (side) side.innerHTML = allFiles.map((f) => `<div class="file${f === active ? " on" : ""}"><i class="dot ${esc(fileLang[f])}"></i>${esc(f)}</div>`).join("");
  }

  function drawEditor(ci, p, t) {
    const editor = $("dc-editor");
    if (ci < 0) {
      editor.innerHTML = `<div class="welcome"><div class="logo">${esc(repo)}</div><div>Show All Commands <kbd>⇧⌘P</kbd></div><div>Go to File <kbd>⌘P</kbd></div></div>`;
      $("dc-pos").textContent = "";
      $("dc-lang").textContent = "";
      return;
    }
    const c = prepCode(ci);
    const q = c.typed ? clamp(p / TYPE_SHARE, 0, 1) : 1;
    const chars = Math.round(c.pre + (c.total - c.pre) * q);
    let left = chars, line = 0;
    while (line < c.lines.length - 1 && left > c.lens[line]) { left -= c.lens[line] + 1; line++; }
    const col = Math.min(left, c.lens[line]);
    const done = q >= 1;
    // Measured each frame: the terminal panel takes half the editor away.
    const rows = Math.max(6, Math.floor((editor.clientHeight - 16) / c.lh));
    let first = Math.max(0, line - rows + 3);
    if (done && c.hl.size) first = clamp(Math.min(...c.hl) - 3, 0, Math.max(0, c.lines.length - rows));
    const last = Math.min(c.lines.length, first + rows);
    const caret = !done || Math.floor(t * 1.8) % 2 === 0;
    let g = "", h = "";
    for (let n = first; n < last; n++) {
      if (n > line) { g += '<div class="ln"></div>'; h += '<div class="line"></div>'; continue; }
      const shown = n < line ? c.lens[n] : col;
      g += `<div class="ln${n === line ? " cur" : ""}">${n + 1}</div>`;
      h += `<div class="line${done && c.hl.has(n + 1) ? " hl" : ""}">${slice(c.lines[n], shown)}${n === line && caret ? '<span class="caret"></span>' : ""}</div>`;
    }
    editor.style.setProperty("--fs", c.fs + "px");
    editor.style.setProperty("--lh", c.lh + "px");
    editor.innerHTML = `<div class="gutter">${g}</div><div class="code">${h}</div>`;
    $("dc-pos").textContent = `Ln ${line + 1}, Col ${col + 1}`;
    $("dc-lang").textContent = c.label;
  }

  const PROMPT = '<span class="pa">➜</span>  <span class="pc">' + esc(repo) + '</span> <span class="pb">git:(</span><span class="pg">main</span><span class="pb">)</span> ';
  function outLine(text) {
    const s = String(text);
    if (/^\s*[{}\[\]"]/.test(s)) return slice(tokens(s, "json"), s.length);
    if (/^\s*(✓|✔|PASS|passed|OK\b|200\b)/.test(s)) return `<span class="ok">${esc(s)}</span>`;
    if (/^\s*(✗|✘|FAIL|Error|error|ERR)/.test(s)) return `<span class="bad">${esc(s)}</span>`;
    return esc(s);
  }
  function drawPanel(s, p, t, full) {
    const panel = $("dc-panel");
    if (!s) { panel.style.display = "none"; return; }
    panel.style.display = "flex";
    panel.classList.toggle("full", !!full);
    const cmd = String(s.cmd || "");
    const typed = cmd.slice(0, Math.round(cmd.length * clamp(p / 0.3, 0, 1)));
    const out = s.output || [];
    const shown = p < 0.35 ? 0 : Math.ceil(out.length * clamp((p - 0.35) / 0.5, 0, 1));
    const blink = Math.floor(t * 1.8) % 2 === 0 ? '<span class="caret"></span>' : "";
    const lines = [PROMPT + esc(typed) + (p < 0.35 ? '<span class="caret"></span>' : "")]
      .concat(out.slice(0, shown).map(outLine));
    if (shown === out.length && p >= 0.9) lines.push(PROMPT + blink);
    const term = $("dc-term");
    const rows = Math.max(4, Math.floor((term.clientHeight - 12) / 34));
    term.innerHTML = lines.slice(-rows).map((x) => `<div>${x}</div>`).join("");
  }

  function wordWindow(s, p) {
    const blocks = s.doc || [];
    const reveal = s.reveal === false ? blocks.length : clamp(p / 0.8, 0, 1) * blocks.length;
    const body = blocks.map((b, k) => {
      if (k >= Math.ceil(reveal)) return "";
      const o = k < Math.floor(reveal) ? 1 : reveal - k;
      let inner;
      if (b.h) inner = `<h1>${esc(b.h)}</h1>`;
      else if (b.eq) inner = `<div class="eq">${esc(b.eq)}</div>`;
      else if (b.q) inner = `<div class="q"><b>${esc(b.n || "")}</b> ${esc(b.q)}${b.marks ? ` <span class="mk">(${esc(b.marks)} mark${b.marks == 1 ? "" : "s"})</span>` : ""}</div>`;
      else if (b.opts) inner = `<ol class="opts" type="A">${b.opts.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>`;
      else if (b.box !== undefined) inner = `<div class="cc${b.locked ? " locked" : ""}"><span class="cct">${b.locked ? "🔒 " : ""}Answer</span>${esc(b.box) || '<i>Click or tap here to enter text.</i>'}</div>`;
      else if (b.table) inner = `<table>${b.table.map((r, n) => `<tr>${r.map((c) => n ? `<td>${esc(c)}</td>` : `<th>${esc(c)}</th>`).join("")}</tr>`).join("")}</table>`;
      else if (b.result) inner = `<div class="res">${esc(b.result)}</div>`;
      else if (b.img) inner = `<div class="img">🖼 ${esc(b.img)}</div>`;
      else inner = `<p>${esc(b.p || "")}</p>`;
      return `<div class="blk" style="opacity:${o.toFixed(3)}">${inner}</div>`;
    }).join("");
    const pn = s.pane;
    let pane = "";
    if (pn) {
      const timer = Array.isArray(pn.timer) ? pn.timer[0] + (pn.timer[1] - pn.timer[0]) * p : null;
      pane = `<div class="pane"><div class="ph">${esc(pn.title || "Add-in")}</div>
        ${(pn.fields || []).map(([k, v]) => `<label>${esc(k)}</label><div class="in">${esc(v)}</div>`).join("")}
        ${timer !== null ? `<div class="timer${timer <= 10 ? " low" : ""}">⏱ ${mmss(timer)}</div>` : ""}
        ${pn.progress ? `<div class="prog"><i style="width:${(100 * pn.progress[0] / pn.progress[1]).toFixed(1)}%"></i></div><div class="pl">Question ${esc(pn.progress[0])} of ${esc(pn.progress[1])}</div>` : ""}
        ${(pn.lines || []).map((x) => `<p>${esc(x)}</p>`).join("")}
        ${pn.button ? `<div class="btn">${esc(pn.button)}</div>` : ""}</div>`;
    }
    const tabs = ["File", "Home", "Insert", "Draw", "Design", "Layout", "References", "Review", "View"];
    return `<div class="win word"><div class="wtb"><span class="lights"><i></i><i></i><i></i></span>${esc(s.file || "Document.docx")} — Word</div>
      <div class="ribbon">${tabs.map((x) => `<span${x === "Home" ? ' class="on"' : ""}>${x}</span>`).join("")}${pn ? `<span class="addin">${esc(pn.title || "Add-in")}</span>` : ""}</div>
      <div class="wbody"><div class="pagewrap"><div class="page">${body}</div></div>${pane}</div></div>`;
  }

  function excelWindow(s, p) {
    const rows = s.rows || [];
    const cols = Math.max(1, ...rows.map((r) => r.length));
    const reveal = s.reveal === false ? rows.length : Math.ceil(rows.length * clamp(p / 0.7, 0, 1));
    const letters = Array.from({ length: cols }, (_, k) => String.fromCharCode(65 + k));
    const sel = String(s.select || "").toUpperCase();
    const widths = s.widths || [];
    const head = `<tr><th class="corner"></th>${letters.map((c, k) => `<th style="width:${widths[k] || Math.floor(100 / cols)}%">${c}</th>`).join("")}</tr>`;
    const body = rows.map((r, n) => `<tr><th>${n + 1}</th>${letters.map((c, k) => {
      const v = n < reveal ? String(r[k] == null ? "" : r[k]) : "";
      const cls = [n === 0 && s.header !== false ? "hd" : "", /^✓/.test(v) ? "ok" : "", /^✗/.test(v) ? "bad" : "", sel === `${c}${n + 1}` && p > 0.2 ? "sel" : ""].filter(Boolean).join(" ");
      return `<td${cls ? ` class="${cls}"` : ""}>${esc(v)}</td>`;
    }).join("")}</tr>`).join("");
    const tabs = ["File", "Home", "Insert", "Page Layout", "Formulas", "Data", "Review", "View", "Developer"];
    return `<div class="win excel"><div class="wtb"><span class="lights"><i></i><i></i><i></i></span>${esc(s.file || "Book1.xlsm")} — Excel</div>
      <div class="ribbon">${tabs.map((x) => `<span${x === "Home" ? ' class="on"' : ""}>${x}</span>`).join("")}</div>
      <div class="fbar"><span class="nm">${esc(sel || "A1")}</span><span class="fx">ƒx</span><span class="fv">${p > 0.15 ? esc(s.formula || "") : ""}</span></div>
      <div class="grid"><table>${head}${body}</table></div>
      <div class="sheets"><span class="on">${esc(s.sheet || "Game")}</span><span>Scores</span><span>+</span></div></div>`;
  }

  function drawApp(s, p, local) {
    const app = $("dc-app");
    if (s.scene !== "word" && s.scene !== "excel") { app.style.display = "none"; return; }
    const a = ease(local / 0.35);
    app.style.display = "block";
    app.style.opacity = a.toFixed(3);
    app.style.transform = `scale(${(0.96 + 0.04 * a).toFixed(4)})`;
    app.innerHTML = s.scene === "word" ? wordWindow(s, p) : excelWindow(s, p);
  }

  function drawStage(s, p, local) {
    const stage = $("dc-stage");
    if (!["title", "points", "outro"].includes(s.scene)) { stage.style.display = "none"; return; }
    stage.style.display = "flex";
    const a = ease(local / 0.5);
    const rise = `style="opacity:${a.toFixed(3)};transform:translateY(${((1 - a) * 24).toFixed(1)}px)"`;
    if (s.scene === "title") {
      stage.innerHTML = `<div class="st" ${rise}><div class="kick">${esc(s.kicker || "")}</div><h1>${esc(s.text || "")}<span class="caret"></span></h1>${s.sub ? `<div class="sub">${esc(s.sub)}</div>` : ""}</div>`;
    } else if (s.scene === "points") {
      const items = s.items || [];
      const shown = p <= 0 ? 0 : Math.max(1, Math.ceil(items.length * clamp(p / 0.85, 0, 1)));
      stage.innerHTML = `<div class="st md" ${rise}><div class="mdh"># ${esc(s.title || "")}</div><ul>${items.map((x, k) => `<li class="${k < shown ? "on" : ""}"><span class="bul">${k + 1}.</span>${esc(x)}</li>`).join("")}</ul></div>`;
    } else {
      stage.innerHTML = `<div class="st out" ${rise}><h1>${esc(s.text || "")}</h1>${s.cta ? `<div class="cta">${esc(s.cta)}</div>` : ""}<div class="who">${esc(s.handle || brand.handle || "")}</div><div class="web">${esc(s.website || brand.website || "")}</div></div>`;
    }
  }

  function drawCaption(i, p) {
    const ph = PHRASES[i] || [];
    const cap = $("dc-cap");
    if (!ph.length) { cap.innerHTML = ""; return; }
    const sizes = ph.map((x) => x.length), all = sizes.reduce((a, b) => a + b, 0);
    let k = 0, acc = sizes[0];
    while (k + 1 < ph.length && acc / all <= p) { k++; acc += sizes[k]; }
    cap.innerHTML = `<span>${esc(ph[k].join(" "))}</span>`;
  }

  function draw(t) {
    if (!scenes.length) return;
    const i = sceneAt(t), s = scenes[i];
    const local = t - starts[i];
    const p = clamp(local / Math.max(0.5, durations[i] - GAP), 0, 1);
    const ci = lastCode[i];
    drawTabs(i, ci);
    drawPanel(s.scene === "terminal" ? s : null, p, t, ci < 0);
    drawEditor(ci, ci === i ? p : 1, t);
    drawApp(s, p, local);
    drawStage(s, p, local);
    drawCaption(i, p);
    window.__scene = i;
  }

  // ── live: the server's voice, scene by scene ──
  let playing = false, now = 0, t0 = 0, voiced = -1, clip = null;
  function stopAudio() { if (clip) { clip.pause(); clip = null; } }
  function tick() {
    if (!playing) return;
    now = (performance.now() - t0) / 1000;
    if (now >= total) { now = total; playing = false; }
    const i = sceneAt(now);
    if (i !== voiced && now >= starts[i]) {
      voiced = i;
      stopAudio();
      const src = (data.audio || [])[i];
      if (src) { clip = new Audio(src); clip.play().catch(() => {}); }
    }
    draw(now);
    ui();
    if (playing) requestAnimationFrame(tick);
  }
  function ui() {
    const b = $("dc-play"), c = $("dc-count");
    if (b) b.textContent = playing ? "❚❚ Pause" : "▶ Play";
    if (c) c.textContent = `${sceneAt(now) + 1}/${scenes.length}`;
  }
  function jump(i) { stopAudio(); now = i < scenes.length ? starts[i] : 0; voiced = playing ? -1 : i; t0 = performance.now() - now * 1000; draw(now); ui(); }
  window.__dc = {
    play() { if (now >= total) now = 0; t0 = performance.now() - now * 1000; voiced = -1; playing = true; requestAnimationFrame(tick); },
    pause() { playing = false; stopAudio(); ui(); },
    toggle() { playing ? this.pause() : this.play(); },
    next() { jump(Math.min(scenes.length - 1, sceneAt(now) + 1)); },
    prev() { jump(Math.max(0, sceneAt(now) - 1)); },
  };

  // ── render: seek frame by frame ──
  window.__seek = (t) => { draw(t); return true; };
  window.__starts = starts;
  window.__total = total;
  const fonts = document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve();
  window.__ready = Promise.race([fonts, new Promise((r) => setTimeout(r, 2500))]).then(() => { draw(0); ui(); return total; });
})();
