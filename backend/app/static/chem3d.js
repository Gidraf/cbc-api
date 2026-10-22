/* Chemistry in 3D. Atoms, ionic and covalent bonding happen in an "atomic
 * world" — a dark space with drifting dust, glowing electrons each in their
 * element's own colour, a camera that dives into the nucleus and follows an
 * electron across, the pull of each nucleus shown, titles on screen and a
 * sound at every beat (sfx.js) — while keeping the diagrams exactly as the
 * exam draws them: concentric shells, electrons at N, E, S, W in pairs,
 * dot-and-cross overlaps. The lab bench and the separations (lab3d.js) are
 * drawn through the same canvas, over the white board.
 *
 * Like the whiteboard and the teacher, everything is a function of time:
 * the server photographs the page frame by frame with window.__seek(t), so
 * each frame is worked out from the scene and its moment alone. Without
 * WebGL it does nothing, and the board draws its flat versions instead.
 *
 * Expects THREE (r128), window.WB_DATA, window.__starts / __total from the
 * whiteboard engine, and calls from it through window.__onChem3d(t).
 */
(function () {
  "use strict";
  const data = window.WB_DATA || {};
  const scenes = data.scenes || [];
  // The lab bench and the separations are drawn by lab3d.js, through this canvas.
  const KINDS = { chem_atom: 1, chem_ionic: 1, chem_covalent: 1, chem_atoms: 1, chem_lab: 1, chem_separation: 1 };
  const CINE = { chem_atom: 1, chem_ionic: 1, chem_covalent: 1, chem_atoms: 1 };
  if (typeof THREE === "undefined" || !scenes.some((s) => KINDS[s.scene])) return;
  const root = document.getElementById("wb");
  if (!root) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  } catch (e) {
    console.warn("chem3d: no WebGL", e);
    return;
  }
  window.__chem3d = true;                        // the board leaves the atoms to us
  root.style.position = "relative";
  const canvas = renderer.domElement;
  canvas.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;display:none;z-index:2";
  root.appendChild(canvas);
  renderer.setClearColor(0x000000, 0);
  renderer.autoClear = false;

  const scene3 = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.1, 200);
  const ambient = new THREE.AmbientLight(0xffffff, 0.55);
  scene3.add(ambient);
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(6, 10, 12);
  scene3.add(key);
  const rim = new THREE.DirectionalLight(0x9cc8ff, 0.35);
  rim.position.set(-8, -4, 6);
  scene3.add(rim);
  const world = new THREE.Group();
  scene3.add(world);
  // Titles on screen, laid over the 3D in board pixels (1280 × 720).
  const hudScene = new THREE.Scene();
  const hudCam = new THREE.OrthographicCamera(0, 1280, 0, -720, -10, 10);

  function size() {
    const w = root.clientWidth || 1280, h = root.clientWidth ? root.clientWidth * 9 / 16 : 720;
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h, false);
    canvas.style.height = h + "px";
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  size();
  window.addEventListener("resize", size);

  // ── materials and little helpers ──
  const mats = {};
  function mat(colour, opts) {
    const k = colour + JSON.stringify(opts || {});
    if (!mats[k]) mats[k] = new THREE.MeshPhongMaterial({ color: new THREE.Color(colour), shininess: 80, ...(opts || {}) });
    return mats[k];
  }
  const sphereGeo = new THREE.SphereGeometry(1, 24, 18);
  const electronMat = new THREE.MeshPhongMaterial({ color: 0x2563eb, emissive: 0x1d4ed8, emissiveIntensity: 0.6, shininess: 120 });
  const movingMat = new THREE.MeshPhongMaterial({ color: 0xf97316, emissive: 0xea580c, emissiveIntensity: 0.8, shininess: 120 });
  function ball(r, material) { const m = new THREE.Mesh(sphereGeo, material); m.scale.setScalar(r); return m; }
  const ringGeos = {}, ringMats = {};
  function ring(r, colour, opacity, width) {
    const rk = r.toFixed(2) + ":" + (width || 0.025), op = Math.round((opacity == null ? 0.7 : opacity) * 20) / 20, mk = `${colour || 0x6b7280}:${op}`;
    if (!ringGeos[rk]) ringGeos[rk] = new THREE.TorusGeometry(r, width || 0.025, 8, 96);
    if (!ringMats[mk]) ringMats[mk] = new THREE.MeshBasicMaterial({ color: colour || 0x6b7280, transparent: true, opacity: op, depthWrite: false });
    return new THREE.Mesh(ringGeos[rk], ringMats[mk]);
  }
  const labels = {};
  const sup = (q) => (q > 1 ? "⁰¹²³⁴⁵⁶⁷⁸⁹"[q] : "");   // Al³⁺, O²⁻
  function label(text, colour, px) {
    const k = text + colour + px;
    if (!labels[k]) {
      const c = document.createElement("canvas"), x = c.getContext("2d");
      c.width = 256; c.height = 128;
      x.font = `bold ${px || 64}px 'Patrick Hand', 'Comic Sans MS', sans-serif`;
      x.textAlign = "center"; x.textBaseline = "middle"; x.fillStyle = colour || "#1b1f2a";
      x.fillText(text, 128, 64);
      labels[k] = new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false });
    }
    const s = new THREE.Sprite(labels[k]);
    s.scale.set(1.6, 0.8, 1);
    return s;
  }
  const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const lerp = (a, b, f) => a + (b - a) * f;
  const span = (t, a, b) => clamp01((t - a) / Math.max(0.001, b - a));
  function rand(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  const cap = (x) => (x ? x.charAt(0).toUpperCase() + x.slice(1) : x);
  const V3 = (x, y, z) => new THREE.Vector3(x, y, z || 0);

  // ── the atomic world: deep space, dust, glow ──
  const bgTex = (() => {
    const c = document.createElement("canvas"); c.width = 1024; c.height = 576;
    const x = c.getContext("2d"), g = x.createRadialGradient(560, 260, 40, 560, 300, 720);
    g.addColorStop(0, "#1b2f5c"); g.addColorStop(0.45, "#0d1730"); g.addColorStop(1, "#04060d");
    x.fillStyle = g; x.fillRect(0, 0, 1024, 576);
    return new THREE.CanvasTexture(c);
  })();
  const fog = new THREE.FogExp2(0x070b16, 0.018);
  const dust = (() => {
    const n = 900, pos = new Float32Array(n * 3), r = rand(99);
    for (let i = 0; i < n; i++) { pos[i * 3] = (r() - 0.5) * 60; pos[i * 3 + 1] = (r() - 0.5) * 34; pos[i * 3 + 2] = -30 + r() * 38; }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    return new THREE.Points(g, new THREE.PointsMaterial({ color: 0x9cc8ff, size: 0.07, transparent: true, opacity: 0.55, depthWrite: false }));
  })();
  const glowTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const x = c.getContext("2d"), g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.25, "rgba(255,255,255,0.55)"); g.addColorStop(1, "rgba(255,255,255,0)");
    x.fillStyle = g; x.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();
  const glowMats = {};
  function glow(hex, size, op) {
    const o = Math.round(clamp01(op) * 20) / 20;
    if (o <= 0) return null;
    const k = hex + o;
    if (!glowMats[k]) glowMats[k] = new THREE.SpriteMaterial({ map: glowTex, color: new THREE.Color(hex), transparent: true, opacity: o,
                                                              blending: THREE.AdditiveBlending, depthWrite: false });
    const s = new THREE.Sprite(glowMats[k]); s.scale.set(size, size, 1); return s;
  }
  const eMats = {};
  const eMat = (hex) => eMats[hex] || (eMats[hex] = new THREE.MeshBasicMaterial({ color: new THREE.Color(hex) }));
  // Each element's electrons keep their colour, wherever they go.
  const WARM = "#fbbf24", COOL = "#22d3ee", ONE = "#38bdf8", SHELL = 0x7dd3fc, SHARED = "#4ade80";

  // ── titles: clean type on screen, typed on or faded in ──
  const hudTex = {};
  function hud(str, x, y, o) {
    o = o || {};
    if (!str) return;
    const alpha = o.alpha == null ? 1 : o.alpha;
    if (alpha <= 0.02) return;
    const n = o.reveal == null ? str.length : Math.ceil(str.length * clamp01(o.reveal));
    if (n <= 0) return;
    const shown = str.slice(0, n), size = o.size || 32, weight = o.weight || 700, colour = o.colour || "#ffffff";
    const k = `${shown}|${size}|${weight}|${colour}|${o.box || ""}`;
    let e = hudTex[k];
    if (!e) {
      const c = document.createElement("canvas"), g = c.getContext("2d");
      const font = `${weight} ${size * 2}px "Inter", "Segoe UI", "Helvetica Neue", Arial, sans-serif`;
      g.font = font;
      const pad = o.box ? 30 : 14, w = Math.ceil(g.measureText(shown).width) + pad * 2, h = Math.ceil(size * 2 * 1.45);
      c.width = w; c.height = h; g.font = font; g.textBaseline = "middle";
      if (o.box) { g.fillStyle = o.box; const r = h / 2.4; g.beginPath(); g.moveTo(r, 0); g.arcTo(w, 0, w, h, r); g.arcTo(w, h, 0, h, r); g.arcTo(0, h, 0, 0, r); g.arcTo(0, 0, w, 0, r); g.fill(); }
      g.shadowColor = "rgba(0,0,0,0.65)"; g.shadowBlur = 10; g.fillStyle = colour; g.fillText(shown, pad, h / 2 + 2);
      const tex = new THREE.CanvasTexture(c); tex.minFilter = THREE.LinearFilter;
      e = hudTex[k] = { mat: new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }), w: w / 2, h: h / 2 };
    }
    const sp = new THREE.Sprite(e.mat);
    sp.material.opacity = alpha;
    const sc = o.scale || 1;
    sp.scale.set(e.w * sc, e.h * sc, 1);
    const left = o.align === "center" ? x - (e.w * sc) / 2 : o.align === "right" ? x - e.w * sc : x;
    sp.position.set(left + (e.w * sc) / 2, -y, 0);
    hudScene.add(sp);
  }
  // A caption at the foot of the frame, in and out with its moment.
  function caption(str, t, a, b, colour) {
    const f = Math.min(span(t, a, a + 0.35), 1 - span(t, b - 0.3, b));
    if (f > 0) hud(str, 640, 650, { size: 25, align: "center", alpha: f, box: "rgba(6,12,28,0.72)", colour: colour || "#e2e8f0", weight: 600 });
  }

  // ── one atom, as the dot-and-cross diagrams draw it ──
  // The shells are circles round the nucleus, in one plane, evenly spaced;
  // the electrons sit at the four places (N, E, S, W) — one at each first,
  // then in pairs — and the first shell's two opposite each other. The
  // nucleus is a tight ball of protons (red) and neutrons (grey), mixed.
  const SHELL_R = (k) => 1.1 + k * 0.85;
  const SLOTS = [Math.PI / 2, 0, -Math.PI / 2, Math.PI];          // N, E, S, W
  function slotAngles(n, k, r) {
    if (k === 0) return n === 1 ? [SLOTS[0]] : [SLOTS[0], SLOTS[2]];
    const off = 0.17 / r, out = [];
    for (let e = 0; e < n; e++) {
      const place = e % 4, paired = n > place + 4;
      out.push(SLOTS[place] + (paired ? (e < 4 ? off : -off) : 0));
    }
    return out;
  }
  // The electrons sway a little about their places, never far from N, E, S, W.
  const sway = (t, k) => Math.sin(t * 0.7 + k * 1.3) * 0.12;
  const NUC_R = 0.15, nuclei = {};
  function nucleusLayout(p, n) {
    const key2 = p + ":" + n;
    if (nuclei[key2]) return nuclei[key2];
    const N = Math.max(1, p + n), rnd = rand(p * 131 + n * 7 + 1), pts = [];
    if (N === 1) return (nuclei[key2] = [{ v: new THREE.Vector3(), proton: p > 0 }]);
    for (let i = 0; i < N; i++) {
      const y = 1 - ((i + 0.5) / N) * 2, rr = Math.sqrt(1 - y * y), th = i * 2.399963;
      const d = NUC_R * 1.7 * Math.cbrt(N) * Math.cbrt((i + 0.5) / N);
      pts.push(new THREE.Vector3(Math.cos(th) * rr * d, y * d, Math.sin(th) * rr * d));
    }
    // Neighbours push apart, everything pulls in: a packed ball, worked out once.
    const want = 2 * NUC_R * 0.97;
    for (let it = 0; it < 90; it++) {
      for (let i = 0; i < N; i++) {
        pts[i].multiplyScalar(0.985);
        for (let j = i + 1; j < N; j++) {
          const dv = pts[i].clone().sub(pts[j]), dist = dv.length() || 1e-3;
          if (dist < want) { dv.multiplyScalar(((want - dist) / dist) * 0.5); pts[i].add(dv); pts[j].sub(dv); }
        }
      }
    }
    // Which are protons: chosen evenly through the ball, so the colours mix.
    const idx = pts.map((_, i) => i);
    for (let i = idx.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [idx[i], idx[j]] = [idx[j], idx[i]]; }
    const proton = new Set(idx.slice(0, p));
    return (nuclei[key2] = pts.map((v, i) => ({ v, proton: proton.has(i) })));
  }
  function buildAtom(a, opts) {
    // opts: built 0..1 (electrons arrived so far), t (seconds), spin, shells
    // (to draw an ion), gained (the last n outer electrons came from another
    // atom: drawn in gainedColour), bare (no outer electrons: a diagram
    // places them), colour (its electrons), fly (arriving electrons fly in
    // from afar), wobble (the outer electrons tug outwards: weakly held),
    // shield (the inner shells glow: they screen the outer electrons).
    const g = new THREE.Group();
    for (const nu of nucleusLayout(a.protons || 1, a.neutrons || 0)) {
      const b = ball(NUC_R, nu.proton ? mat("#ef4444", { emissive: 0x7f1d1d, emissiveIntensity: 0.5 }) : mat("#b6bdc8"));
      b.position.copy(nu.v); g.add(b);
    }
    const halo = glow("#ff8a65", 1.4 + Math.cbrt((a.protons || 1) + (a.neutrons || 0)) * 0.25, opts.cine ? 0.35 : 0);
    if (halo) g.add(halo);
    const shells = (opts.shells || a.shells || []).slice();
    const total = shells.reduce((x, y) => x + y, 0);
    const built = opts.built == null ? 1 : opts.built;
    const colour = opts.colour || ONE;
    const rnd = rand((a.Z || a.protons || 1) * 31 + 5);
    let count = 0;
    shells.forEach((n, k) => {
      const r = SHELL_R(k), last = k === shells.length - 1;
      const shown = clamp01(built * total - count + 1);
      const shieldGlow = !last && opts.shield ? opts.shield : 0;
      if (shown > 0) g.add(ring(r, shieldGlow > 0.05 ? 0xfacc15 : opts.cine ? SHELL : 0x6b7280, (opts.cine ? 0.25 : 0.3) + 0.4 * shown + 0.3 * shieldGlow, shieldGlow > 0.05 ? 0.045 : 0.025));
      const angs = slotAngles(n, k, r), turn = sway(opts.t || 0, k) * (opts.spin == null ? 1 : opts.spin);
      for (let e = 0; e < n; e++) {
        count++;
        const dirA = rnd() * Math.PI * 2, far = 7 + rnd() * 4, zr = rnd();   // drawn first, so they never shift
        if (last && opts.bare) continue;
        const arrived = clamp01(built * total - (count - 1));
        if (arrived <= 0) continue;
        const foreign = last && e >= n - (opts.gained || 0);
        const hex = foreign ? opts.gainedColour || "#f97316" : colour;
        const wob = last && opts.wobble ? opts.wobble * (0.5 + 0.5 * Math.sin((opts.t || 0) * 9 + e)) : 0;
        const rr = r + wob * 0.35;
        const slot = V3(Math.cos(angs[e] + turn) * rr, Math.sin(angs[e] + turn) * rr, 0.02);
        const p = opts.fly && arrived < 1
          ? V3(Math.cos(dirA) * far, Math.sin(dirA) * far * 0.6, 3 + zr).lerp(slot, ease(arrived)) : slot;
        const el = ball(0.12 * (0.5 + 0.5 * ease(arrived)), opts.cine ? eMat(hex) : foreign ? movingMat : electronMat);
        el.position.copy(p); g.add(el);
        if (opts.cine) { const gl = glow(hex, 0.75 + wob * 0.6, 0.85); gl.position.copy(p); g.add(gl); }
      }
    });
    return g;
  }
  function outerPoint(a, slot, of, t, centre, scaleK) {
    // Where electron `slot` of `of` on the outer shell is, in world space.
    const k = (a.shells || [1]).length - 1, r = SHELL_R(k);
    const ang = slotAngles(of, k, r)[Math.max(0, Math.min(of - 1, slot))] + sway(t, k);
    return V3(Math.cos(ang) * r, Math.sin(ang) * r, 0).multiplyScalar(scaleK || 1).add(centre);
  }
  // The symbol on the nucleus, dark with a white edge, so it reads over red and grey.
  const tags = {};
  function tag(text) {
    if (!tags[text]) {
      const c = document.createElement("canvas"), x = c.getContext("2d");
      c.width = 256; c.height = 128;
      x.font = "bold 76px 'Inter', 'Segoe UI', Arial, sans-serif";
      x.textAlign = "center"; x.textBaseline = "middle";
      x.lineWidth = 14; x.strokeStyle = "rgba(255,255,255,0.92)"; x.lineJoin = "round";
      x.strokeText(text, 128, 66); x.fillStyle = "#111827"; x.fillText(text, 128, 66);
      tags[text] = new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false });
    }
    const sp = new THREE.Sprite(tags[text]);
    sp.scale.set(0.9, 0.45, 1);
    return sp;
  }
  function look(pos, target) { camera.position.copy(pos); camera.lookAt(target); }
  // A ring of light spreading from a point: an atom becoming an ion.
  function shockwave(at, t0, t, colour) {
    const f = span(t, t0, t0 + 0.9);
    if (f <= 0 || f >= 1) return;
    const r = ring(0.6 + f * 3.2, new THREE.Color(colour).getHex(), 0.85 * (1 - f), 0.05);
    r.position.copy(at); world.add(r);
  }
  // Lines of pull from a nucleus: strong ones bright and thick, a weak one thin and dim.
  function pull(from, to, strength, t) {
    const n = 7;
    for (let k = 0; k <= n; k++) {
      const f = ((k / n) + t * 0.6 * strength) % 1;                 // light running inwards along it
      const p = to.clone().lerp(from, f);
      const gl = glow(strength > 0.6 ? COOL : "#f87171", 0.22 + 0.25 * strength, 0.25 + 0.6 * strength);
      if (gl) { gl.position.copy(p); world.add(gl); }
    }
  }

  // ── the scenes ──
  function atomScene(s, i, t, dur) {
    const prev = s.short && s.slot === 1 ? scenes[i - 1] : null;
    if (s.short) {
      // A pair before it bonds: each built as the voice counts.
      const both = [prev, s].filter(Boolean);
      const built = span(t, dur * 0.08, dur * 0.7);
      both.forEach((a, j) => {
        const isNow = a === s, x = both.length > 1 ? (j === 0 ? -4.2 : 4.2) : -4.2;
        const g = buildAtom(a, { built: isNow ? built : 1, t: t + j * 3, cine: true, fly: isNow, colour: j === 0 ? WARM : COOL });
        g.position.set(x, 0.3, 0); g.scale.setScalar(0.85 * Math.min(1, 2.95 / SHELL_R(a.shells.length - 1)));
        g.rotation.set(0.1, Math.sin(t * 0.5 + j) * 0.3, 0); world.add(g);
        const tg = tag(a.symbol); tg.position.copy(g.position).add(V3(0, 0, 1.2)); world.add(tg);
        const px = 640 + (x / 7.6) * 640;
        hud(`${cap(a.name)}  ${a.arrangement}`, px, 620, { size: 30, align: "center", colour: j === 0 ? WARM : COOL,
                                                        alpha: isNow ? span(t, dur * 0.55, dur * 0.7) : 1 });
      });
      look(V3(Math.sin(t * 0.2) * 0.8, 0.8, 15.5 - span(t, 0, dur) * 1.5), V3(0, 0.2, 0));
      return;
    }
    // One atom: the camera starts in the nucleus and pulls back as the shells fill.
    const ax = -2.6;
    const g = buildAtom(s, { built: span(t, dur * 0.12, dur * 0.67), t, cine: true, fly: true, colour: ONE,
                             wobble: 0, shield: 0 });
    g.position.set(ax, 0, 0); g.scale.setScalar(1.05 * Math.min(1, 2.95 / SHELL_R(s.shells.length - 1)));
    g.rotation.set(0.12, Math.sin(t * 0.4) * 0.35, 0); world.add(g);
    const out = ease(span(t, dur * 0.05, dur * 0.34)), orbit = Math.sin(t * 0.3) * 0.35 * out;
    if (out > 0.55) { const tg = tag(s.symbol); tg.position.set(ax, 0, 1.2); world.add(tg); }   // not over the close-up of the nucleus
    const target = V3(lerp(ax, -1.0, out), 0, 0);
    look(V3(target.x + Math.sin(orbit) * lerp(3.2, 15, out) + lerp(0.5, 0, out), lerp(0.4, 0.6, out), Math.cos(orbit) * lerp(3.2, 15, out)), target);
    const p = t / dur;
    caption(`The nucleus: ${s.protons} protons (red) and ${s.neutrons} neutrons (grey)`, t, 0.2, dur * 0.2);
    const fade = span(t, dur * 0.2, dur * 0.3);
    hud(cap(s.name), 770, 190, { size: 58, alpha: fade, colour: "#ffffff" });
    hud(`${s.protons} protons`, 772, 270, { size: 28, alpha: fade, colour: "#fca5a5", weight: 600 });
    hud(`${s.neutrons} neutrons`, 772, 312, { size: 28, alpha: fade, colour: "#cbd5e1", weight: 600 });
    // The electrons counted as they arrive, and the arrangement built shell by shell.
    const total = s.shells.reduce((x, y) => x + y, 0), got = Math.min(total, Math.floor(span(t, dur * 0.12, dur * 0.67) * total + 1e-6));
    hud(`${got} electron${got === 1 ? "" : "s"}`, 772, 354, { size: 28, alpha: fade, colour: ONE, weight: 600 });
    let left = got;
    const parts = s.shells.map((n) => { const k = Math.min(n, Math.max(0, left)); left -= k; return k; }).filter((k, j, all) => k > 0 || j === 0);
    hud(parts.join("."), 772, 450, { size: 64, alpha: span(t, dur * 0.14, dur * 0.2), colour: p > 0.67 ? "#4ade80" : "#e0f2fe" });
    hud("electron arrangement", 776, 505, { size: 22, alpha: span(t, dur * 0.14, dur * 0.2), colour: "#94a3b8", weight: 500 });
    if (s.group) hud(`Group ${s.group} · Period ${s.period}`, 776, 560, { size: 26, alpha: span(t, dur * 0.72, dur * 0.8), colour: "#fde68a", weight: 600 });
  }

  function ionicScene(s, i, t, dur) {
    const nm = Math.min(3, s.counts[s.metal.symbol] || 1), nn = Math.min(3, s.counts[s.nonmetal.symbol] || 1);
    const moves = s.moves || [];
    const T = timesIonic(s, dur);
    const Rm = SHELL_R(s.metal.shells.length - 1), Rn = SHELL_R(s.nonmetal.shells.length - 1);
    const k = Math.min(0.8, 7.0 / (nm * 2 * Rm * 1.08), 7.0 / (nn * 2 * Rn * 1.08));
    const close = ease(span(t, T.attract, T.attract + dur * 0.08));           // the ions drawn together
    const xm = lerp(-4.2, -2.4, close), xn = lerp(4.2, 2.6, close);
    const mPos = Array.from({ length: nm }, (_, j) => V3(xm, (j - (nm - 1) / 2) * 2 * Rm * 1.08 * k, 0));
    const nPos = Array.from({ length: nn }, (_, j) => V3(xn, (j - (nn - 1) / 2) * 2 * Rn * 1.08 * k, 0));
    const qm = Math.abs(s.metal.ion_charge || 1), qn = Math.abs(s.nonmetal.ion_charge || 1);
    const toLattice = ease(span(t, T.lattice, T.lattice + 1.6));
    const given = mPos.map(() => 0), taken = nPos.map(() => 0);
    const flying = [];
    moves.forEach((mv, n) => {
      const f = span(t, T.move(n), T.move(n) + T.per * 0.85);
      const im = Math.min(mv.from, nm - 1), jn = Math.min(mv.to, nn - 1);
      if (f >= 1) { given[im]++; taken[jn]++; }
      else if (f > 0) flying.push({ im, jn, f, n, slotM: given[im], slotN: taken[jn] });
    });
    const outerM = s.metal.shells[s.metal.shells.length - 1], outerN = s.nonmetal.shells[s.nonmetal.shells.length - 1];
    const innerM = s.metal.shells.slice(0, -1).reduce((x, y) => x + y, 0);
    const weak = span(t, T.weak, T.weak + 0.4) * (1 - span(t, T.strong, T.strong + 0.3));
    const strong = span(t, T.strong, T.strong + 0.4) * (1 - span(t, T.move(0), T.move(0) + 0.4));
    const appear = ease(span(t, 0, dur * 0.08));
    if (toLattice < 1) {
      mPos.forEach((p, j) => {
        const shells = s.metal.shells.slice();
        shells[shells.length - 1] -= given[j] + flying.filter((x) => x.im === j).length;
        const ion = given[j] >= qm;
        const g = buildAtom(s.metal, { built: 1, t, cine: true, colour: WARM, wobble: weak * 1.0, shield: weak,
                                       shells: shells[shells.length - 1] > 0 ? shells : shells.slice(0, -1) });
        g.position.copy(p); g.scale.setScalar(k * (ion ? 0.9 : 1) * appear * (1 - toLattice)); world.add(g);
        if (weak > 0.05 && j === 0) outerPointsOf(s.metal, outerM, t, p, k).forEach((q) => pull(p, q, 0.25 * weak, t));
        if (toLattice < 0.4) {
          const l = ion ? label(`${s.metal.symbol}${sup(qm)}⁺`, WARM, 64) : tag(s.metal.symbol);
          l.position.copy(p).add(V3(ion ? -Rm * k - 0.9 : 0, 0, 1.3)); world.add(l);
        }
        if (ion) shockwave(p, T.ionOf(moves, "from", j, qm, nm - 1), t, WARM);
      });
      nPos.forEach((p, j) => {
        const shells = s.nonmetal.shells.slice();
        shells[shells.length - 1] += taken[j];
        const ion = taken[j] >= qn;
        const g = buildAtom(s.nonmetal, { built: 1, t: t + 2, cine: true, colour: COOL, shells, gained: taken[j], gainedColour: WARM });
        g.position.copy(p); g.scale.setScalar(k * (ion ? 1.05 : 1) * appear * (1 - toLattice)); world.add(g);
        if (strong > 0.05 && j === 0) {
          // The pull on the gap in its outer shell, reaching towards the metal.
          for (let q = 0; q < 3; q++) pull(p, p.clone().add(V3(-2.4 - q * 0.5, (q - 1) * 1.1, 0.5)), 0.9 * strong, t + q);
        }
        if (toLattice < 0.4) {
          const l = ion ? label(`${s.nonmetal.symbol}${sup(qn)}⁻`, COOL, 64) : tag(s.nonmetal.symbol);
          l.position.copy(p).add(V3(ion ? Rn * k + 0.9 : 0, 0, 1.3)); world.add(l);
        }
        if (ion) shockwave(p, T.ionOf(moves, "to", j, qn, nn - 1), t, COOL);
      });
      // Opposite charges pull together: a glow across the gap.
      const att = span(t, T.attract, T.attract + 0.6) * (1 - toLattice);
      if (att > 0) for (let q = 0; q <= 8; q++) { const gl = glow("#f0abfc", 0.35, 0.5 * att); if (gl) { gl.position.copy(V3(lerp(xm + Rm * k, xn - Rn * k, q / 8), Math.sin(t * 6 + q) * 0.05, 0.3)); world.add(gl); } }
      // The electrons in flight: an arc, the metal's colour kept, a comet's tail.
      flying.forEach((fl) => {
        const from = outerPoint(s.metal, outerM - 1 - fl.slotM, outerM, t, mPos[fl.im], k);
        const to = outerPoint(s.nonmetal, outerN + fl.slotN, 8, t + 2, nPos[fl.jn], k);
        const mid = from.clone().add(to).multiplyScalar(0.5).add(V3(0, 2.0, 1.6));
        const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
        const e = ease(fl.f), p = curve.getPoint(e);
        const el = ball(0.17, eMat(WARM)); el.position.copy(p); world.add(el);
        const gl = glow(WARM, 1.3, 1); gl.position.copy(p); world.add(gl);
        for (let tr = 1; tr <= 10; tr++) {
          const qp = curve.getPoint(Math.max(0, e - tr * 0.025));
          const gh = glow(WARM, 0.7 * (1 - tr / 12), 0.7 * (1 - tr / 11)); if (gh) { gh.position.copy(qp); world.add(gh); }
        }
      });
    }
    if (toLattice > 0) world.add(lattice(s, nm, nn, t, toLattice, span(t, T.lattice, dur * 0.97)));
    // The camera: wide, then in to the metal, across to the non-metal, riding the electron, out to the lattice.
    const wide = { pos: V3(Math.sin(t * 0.2) * 1.2, 1.2, 17), at: V3(0, 0.2, 0) };
    let cam = wide;
    const m0 = mPos[0], n0 = nPos[0];
    if (weak > 0.01) cam = mixCam(wide, { pos: m0.clone().add(V3(1.4, 0.8, 8.5)), at: m0.clone() }, ease(weak));
    if (strong > 0.01) cam = mixCam(wide, { pos: n0.clone().add(V3(-1.6, 0.8, 8.5)), at: n0.clone() }, ease(strong));
    if (flying.length) {
      const fl = flying[0];
      const from = outerPoint(s.metal, outerM - 1 - fl.slotM, outerM, t, mPos[fl.im], k), to = outerPoint(s.nonmetal, outerN + fl.slotN, 8, t + 2, nPos[fl.jn], k);
      const mid = from.clone().add(to).multiplyScalar(0.5).add(V3(0, 2.0, 1.6));
      const p = new THREE.QuadraticBezierCurve3(from, mid, to).getPoint(ease(fl.f));
      const ride = Math.sin(Math.PI * fl.f);
      cam = mixCam({ pos: V3(0, 1.0, 14), at: V3(0, 0.6, 0) }, { pos: p.clone().add(V3(0, 0.9, 6.5)), at: p.clone() }, ease(ride) * 0.85);
    }
    if (toLattice > 0) {
      // Round the lattice from where the camera is — on an arc, never through the ions.
      const a = (t - T.lattice) * 0.35;
      cam = mixCam(cam, { pos: V3(Math.sin(a) * 13, 3.2, Math.cos(a) * 13), at: V3(0, 0, 0) }, toLattice);
    }
    look(cam.pos, cam.at);
    // The words.
    const M = cap(s.metal.name), N = cap(s.nonmetal.name);
    hud(`${M} gives · ${N} takes`, 48, 52, { size: 30, reveal: span(t, 0.2, 1.4), colour: "#e2e8f0" });
    caption(`${M}: ${outerM} outer electron${outerM > 1 ? "s" : ""}, far from the nucleus, shielded by ${innerM} inner electrons — held weakly`, t, T.weak, T.strong, "#fde68a");
    caption(`${N}: ${outerN} outer electrons, needs ${8 - outerN} more for a full shell — it pulls strongly`, t, T.strong, T.move(0), "#a5f3fc");
    caption(`${moves.length} electron${moves.length > 1 ? "s" : ""} move${moves.length > 1 ? "" : "s"} across`, t, T.move(0), T.ions);
    caption(`${s.metal.symbol}${sup(qm)}⁺  (${ionArr(s.metal.shells, -qm)})     ${s.nonmetal.symbol}${sup(qn)}⁻  (${ionArr(s.nonmetal.shells, qn)})`, t, T.ions, T.attract, "#ffffff");
    caption("Opposite charges attract: the ionic bond", t, T.attract, T.lattice, "#f5d0fe");
    const fz = span(t, T.lattice + 0.6, T.lattice + 1.2);
    hud(s.formula, 640, 600, { size: 66, align: "center", alpha: fz, colour: "#4ade80" });
    hud(`${nm} ${s.metal.symbol}${sup(qm)}⁺ : ${nn} ${s.nonmetal.symbol}${sup(qn)}⁻ — the charges cancel`, 640, 668, { size: 24, align: "center", alpha: fz, colour: "#cbd5e1", weight: 500 });
  }
  function outerPointsOf(a, n, t, centre, k) { return Array.from({ length: n }, (_, e) => outerPoint(a, e, n, t, centre, k)); }
  function mixCam(a, b, f) { return { pos: a.pos.clone().lerp(b.pos, f), at: a.at.clone().lerp(b.at, f) }; }
  function ionArr(shells, delta) {
    const s = shells.slice();
    if (delta < 0) { s[s.length - 1] += delta; if (s[s.length - 1] <= 0) s.pop(); } else s[s.length - 1] += delta;
    return s.join(".");
  }
  // When each beat of the ionic scene falls (shared with the sounds).
  function timesIonic(s, dur) {
    const n = Math.max(1, (s.moves || []).length);
    const move0 = dur * 0.34, per = Math.min(1.6, (dur * 0.26) / n);
    const ions = move0 + per * n + 0.2;
    const attract = Math.max(ions + 0.8, dur * 0.72), lattice = Math.max(attract + 1.0, dur * 0.82);
    return {
      weak: dur * 0.13, strong: dur * 0.24, per, ions, attract, lattice, move: (k) => move0 + k * per,
      ionOf(moves, side, j, q, last) {              // the moment atom j has given/taken all q
        let c = 0;
        for (let m = 0; m < moves.length; m++) if (Math.min(moves[m][side], last) === j && ++c === q) return move0 + m * per + per * 0.85;
        return ions;
      },
    };
  }
  function lattice(s, nm, nn, t, grow, build) {
    // A cube of alternating ions (1:1, like NaCl), or the formula's ions
    // round the scarcer kind; they pop in one by one from the middle.
    const grp = new THREE.Group();
    const mR = 0.5, nR = 0.82;
    const items = [];
    if (nm === nn) {
      for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
        const metal = (x + y + z + 3) % 2 === 0;
        items.push({ metal, p: V3(x * 1.55, y * 1.55, z * 1.55) });
      }
    } else {
      const fewMetal = nm <= nn, few = fewMetal ? nm : nn, more = fewMetal ? nn : nm;
      for (let j = 0; j < few; j++) items.push({ metal: fewMetal, p: V3(few > 1 ? (j - (few - 1) / 2) * 1.5 : 0, 0, 0) });
      for (let j = 0; j < more; j++) { const a = (j / more) * Math.PI * 2 + 0.3; items.push({ metal: !fewMetal, p: V3(Math.cos(a) * 2.3, Math.sin(a) * 1.6, Math.sin(a + 1) * 1.2) }); }
    }
    items.sort((a, b) => a.p.length() - b.p.length());
    items.forEach((it, j) => {
      const f = ease(clamp01(build * items.length * 1.15 - j));
      if (f <= 0) return;
      const b = ball((it.metal ? mR : nR) * f, mat(it.metal ? WARM : COOL, { emissive: it.metal ? 0x7c4a03 : 0x0e5f6e, emissiveIntensity: 0.6, shininess: 120 }));
      b.position.copy(it.p); grp.add(b);
      const gl = glow(it.metal ? WARM : COOL, (it.metal ? 1.4 : 2.2) * f, 0.3); if (gl) { gl.position.copy(it.p); grp.add(gl); }
    });
    grp.scale.setScalar(0.4 + 0.6 * grow);
    grp.rotation.set(0.45, t * 0.25, 0);
    return grp;
  }

  // The real shapes: CH4 a tetrahedron, NH3 a pyramid, H2O bent, CO2 and diatomics straight.
  const SHAPES = {
    1: [[1, 0, 0]],
    2: { linear: [[1, 0, 0], [-1, 0, 0]], bent: [[0.8, -0.6, 0], [-0.8, -0.6, 0]] },
    3: [[0, -0.33, 0.94], [0.82, -0.33, -0.47], [-0.82, -0.33, -0.47]],
    4: [[0, 1, 0], [0.94, -0.33, 0], [-0.47, -0.33, 0.82], [-0.47, -0.33, -0.82]],
  };
  // Space-filling sizes (relative van der Waals radii) for the real shape.
  const VDW = { H: 0.55, C: 0.85, N: 0.8, O: 0.78, F: 0.72, Cl: 0.95, S: 0.98, P: 0.98, Br: 1.05, I: 1.15 };
  function covalentShape(s) {
    const [A, B] = s.atoms, centre = A.symbol === s.centre ? A : B, outer = centre === A ? B : A;
    const same = A.symbol === B.symbol, n = same ? 1 : Math.min(4, s.counts[outer.symbol] || 1);
    const order = same ? (centre.valency || 1) : (outer.valency || 1);
    const bent = n === 2 && centre.shells[centre.shells.length - 1] - 2 * order > 0;
    const name = same || n === 1 ? "linear" : n === 2 ? (bent ? "bent (104.5°)" : "linear (180°)") : n === 3 ? "pyramidal (107°)" : "tetrahedral (109.5°)";
    return { centre, outer, same, n, order, bent, name };
  }
  function timesCovalent(s, dur) {
    const sh = covalentShape(s), nb = sh.same ? 1 : sh.n;
    return { come: dur * 0.18, pair: (j) => dur * (0.2 + (0.3 * j) / nb), pairLen: (dur * 0.3) / nb, hold: dur * 0.5, model: dur * 0.64, nb };
  }
  function covalentScene(s, i, t, dur) {
    // The dot-and-cross diagram as the exam draws it — outer shells
    // overlapping, each shared pair in the overlap (each electron keeping its
    // atom's colour, a green glow round the pair), lone pairs in place — then
    // the molecule in its real shape, turning.
    const { centre, outer, same, n, order, bent, name } = covalentShape(s);
    const T = timesCovalent(s, dur);
    const come = ease(span(t, 0, T.come));
    const toModel = ease(span(t, T.model, T.model + 1.4));
    const dirOf = (si) => V3(Math.cos(SLOTS[si]), Math.sin(SLOTS[si]));
    const bonded = same ? [1] : { 1: [1], 2: [3, 1], 3: [3, 1, 2], 4: [0, 1, 2, 3] }[n];
    const Rc = SHELL_R(centre.shells.length - 1), Ro = SHELL_R(outer.shells.length - 1);
    const overlap = Math.min(Rc, Ro) * 0.5, d = Rc + Ro - overlap;
    const extX = same ? d / 2 + Ro : d + Ro, extY = bonded.some((k) => k === 0 || k === 2) ? d + Ro : Math.max(Rc, Ro);
    const fit = Math.min(1, 6.0 / (2 * extY), 12 / (2 * extX));
    const cC = same ? WARM : COOL, cO = same ? COOL : WARM;
    let firstPair = null;
    if (toModel < 1) {
      const flat = new THREE.Group();
      const cPos = same ? V3(-d / 2, 0) : V3(0, 0);
      const dot = (p, hex) => { const el = ball(0.12, eMat(hex)); el.position.copy(p); flat.add(el); const gl = glow(hex, 0.7, 0.8); gl.position.copy(p); flat.add(gl); };
      const lone = (pos, R, count, slots, hex) => {
        for (let e = 0; e < count; e++) {
          const si = slots[Math.floor(e / 2) % slots.length], paired = count - Math.floor(e / 2) * 2 >= 2;
          const ang = SLOTS[si] + (paired ? (e % 2 ? -1 : 1) * (0.17 / R) : 0);
          dot(pos.clone().add(V3(Math.cos(ang) * R, Math.sin(ang) * R)), hex);
        }
      };
      const loneSlots = (facing, pairs) => {
        const far = (facing + 2) % 4, perp = [(facing + 1) % 4, (facing + 3) % 4];
        return pairs === 1 ? [far, ...perp] : [...perp, far];
      };
      const atom = (a, pos) => {
        const g = buildAtom(a, { built: 1, t: 0, spin: 0, bare: true, cine: true, colour: a === centre ? cC : cO }); g.position.copy(pos); flat.add(g);
        const tg = tag(a.symbol); tg.position.copy(pos).setZ(1.2); flat.add(tg);
      };
      atom(centre, cPos);
      const cOuter = centre.shells[centre.shells.length - 1], cLone = Math.max(0, cOuter - bonded.length * order);
      const cSlots = same ? loneSlots(1, cLone / 2) : [0, 1, 2, 3].filter((k) => !bonded.includes(k));
      lone(cPos, Rc, cLone, cSlots.length ? cSlots : [0], cC);
      bonded.forEach((si, j) => {
        const dir = dirOf(si), perp = V3(-dir.y, dir.x);
        const oPos = same ? V3(d / 2 + (1 - come) * 3, 0) : dir.clone().multiplyScalar(d + (1 - come) * 4);
        atom(outer, oPos);
        const oOuter = outer.shells[outer.shells.length - 1], oLone = Math.max(0, oOuter - order), facing = (si + 2) % 4;
        lone(oPos, Ro, oLone, loneSlots(facing, oLone / 2), cO);
        const share = ease(span(t, T.pair(j), T.pair(j) + T.pairLen));
        const mid = cPos.clone().add(dir.clone().multiplyScalar(Rc - overlap / 2));
        if (!firstPair) firstPair = mid.clone();
        for (let p = 0; p < order; p++) {
          const off = perp.clone().multiplyScalar((p - (order - 1) / 2) * 0.36);
          const tilt = (p - (order - 1) / 2) * (0.36 / Rc);
          const fromC = cPos.clone().add(V3(Math.cos(SLOTS[si] + tilt) * Rc, Math.sin(SLOTS[si] + tilt) * Rc));
          const fromO = oPos.clone().add(V3(Math.cos(SLOTS[facing] - tilt) * Ro, Math.sin(SLOTS[facing] - tilt) * Ro));
          const toC = mid.clone().add(off).add(dir.clone().multiplyScalar(-0.13)), toO = mid.clone().add(off).add(dir.clone().multiplyScalar(0.13));
          dot(fromC.lerp(toC, share), cC); dot(fromO.lerp(toO, share), cO);
          if (share > 0.95) { const h = glow(SHARED, 1.1 + 0.15 * Math.sin(t * 5 + j), 0.75); h.position.copy(mid.clone().add(off)); flat.add(h); }
        }
      });
      flat.scale.setScalar(fit * (1 - toModel));
      flat.position.set(0, 0.35, 0);
      flat.rotation.y = Math.sin(t * 0.35) * 0.18;
      world.add(flat);
    }
    if (toModel > 0) {
      const mol = new THREE.Group();
      const rc = VDW[centre.symbol] || 0.9, ro = VDW[outer.symbol] || 0.9;
      const tint = (a) => mat(a.symbol === "H" ? "#f1f5f9" : a.colour || "#999999", { shininess: 110 });
      if (same) {
        const L = rc * 1.5 * (1 - 0.07 * (order - 1));
        [-1, 1].forEach((sg) => { const b = ball(rc, tint(centre)); b.position.x = (sg * L) / 2; mol.add(b); });
      } else {
        mol.add(ball(rc, tint(centre)));
        let dirs = SHAPES[n] || SHAPES[1];
        if (n === 2) dirs = bent ? SHAPES[2].bent : SHAPES[2].linear;
        dirs.forEach((dv) => { const b = ball(ro, tint(outer)); b.position.copy(new THREE.Vector3(...dv).normalize().multiplyScalar((rc + ro) * 0.8 * (1 - 0.05 * (order - 1)))); mol.add(b); });
      }
      const gl = glow("#93c5fd", 6, 0.25 * toModel); if (gl) mol.add(gl);
      mol.scale.setScalar(1.7 * toModel);
      mol.rotation.set(0.35, t * 0.6, 0);
      mol.position.set(0, 0.35, 0);
      world.add(mol);
    }
    // The camera: wide as they meet, in on a shared pair, round the molecule.
    let cam = { pos: V3(Math.sin(t * 0.25) * 1.0, 0.8, 16.5 - come * 1.0), at: V3(0, 0.3, 0) };
    const push = span(t, T.hold, T.hold + 0.6) * (1 - span(t, T.model - 0.2, T.model + 0.4));
    if (firstPair && push > 0) { const fp = firstPair.clone().multiplyScalar(fit).add(V3(0, 0.35, 0)); cam = mixCam(cam, { pos: fp.clone().add(V3(0.8, 0.6, 9)), at: fp.clone().multiplyScalar(0.6) }, ease(push)); }
    if (toModel > 0) { const a = (t - T.model) * 0.4; cam = mixCam(cam, { pos: V3(Math.sin(a) * 4, 1.5, 12.5), at: V3(0, 0.35, 0) }, toModel); }
    look(cam.pos, cam.at);
    const need = (a) => (a.symbol === "H" ? 2 : 8) - a.shells[a.shells.length - 1];
    const C = cap(centre.name), O = cap(outer.name);
    caption(same ? `${C}: ${centre.shells[centre.shells.length - 1]} outer electrons, needs ${need(centre)} more — two atoms share`
                 : `${C} needs ${need(centre)} more · ${O} needs ${need(outer)} more — so they share`, t, 0.2, T.pair(0) + 0.4, "#e2e8f0");
    const pairs = bonded.reduce((acc, si, j) => acc + (span(t, T.pair(j), T.pair(j) + T.pairLen) > 0.95 ? order : 0), 0);
    hud(`shared pairs: ${pairs}`, 48, 52, { size: 30, alpha: span(t, T.pair(0), T.pair(0) + 0.3) * (1 - toModel * 0.6), colour: SHARED });
    caption("Each shared pair is a covalent bond — now every atom has a full outer shell", t, T.hold, T.model, "#bbf7d0");
    hud(s.formula, 640, 600, { size: 66, align: "center", alpha: span(t, T.model + 0.8, T.model + 1.4), colour: "#4ade80" });
    hud(name, 640, 664, { size: 26, align: "center", alpha: span(t, T.model + 1.1, T.model + 1.7), colour: "#cbd5e1", weight: 500 });
  }

  // ── a reaction, atom by atom ──
  // The balanced equation's particles: each species built by the engine
  // (molecules round a centre, a salt's ions side by side), copied as many
  // times as its number in the equation. Their bonds break; every atom —
  // keeping its colour — flies to its place in a product particle; the new
  // bonds form. The count of each kind of atom is the same before and after.
  const stickGeo = new THREE.CylinderGeometry(1, 1, 1, 8);
  const stickMat = new THREE.MeshPhongMaterial({ color: 0xe2e8f0, emissive: 0x334155, shininess: 80 });
  function stick(a, b, r) {
    const m = new THREE.Mesh(stickGeo, stickMat);
    m.scale.set(r, a.distanceTo(b), r);
    m.position.copy(a).add(b).multiplyScalar(0.5);
    m.quaternion.setFromUnitVectors(V3(0, 1, 0), b.clone().sub(a).normalize());
    return m;
  }
  function atomsLayout(s) {
    // Where every particle sits (reactants left, products right) and every atom in it.
    const place = (side, x0, x1) => {
      const inst = [];
      side.forEach((sp, si) => { for (let c = 0; c < sp.count; c++) inst.push({ sp, si, c }); });
      const n = inst.length, ext = Math.max(0.6, ...side.map((sp) => Math.max(...sp.atoms.map((a) => Math.hypot(a.pos[0], a.pos[1], a.pos[2]))) + 0.5));
      const cols = Math.max(1, Math.ceil(Math.sqrt(n * 1.3))), rows = Math.ceil(n / cols);
      const cell = Math.min((x1 - x0) / cols, 5.6 / rows), k = Math.min(1.5, (cell * 0.55) / ext);
      inst.forEach((it, j) => {
        const r = Math.floor(j / cols), c = j % cols, inRow = Math.min(cols, n - r * cols);
        it.centre = V3(x0 + (x1 - x0) / 2 + (c - (inRow - 1) / 2) * cell, 0.4 + ((rows - 1) / 2 - r) * cell, ((j * 37) % 5 - 2) * 0.25);
        it.k = k;
        it.atoms = it.sp.atoms.map((a) => ({ el: a.el, to: a.to, ion: a.ion, at: it.centre.clone().add(V3(a.pos[0], a.pos[1], a.pos[2]).multiplyScalar(k)) }));
      });
      return inst;
    };
    const L = place(s.left2, -7.2, -0.9), R = place(s.right2, 0.9, 7.2);
    // Each product atom takes the next reactant atom of its element: the equation balances, so there is always one.
    const pool = {};
    L.forEach((it) => it.atoms.forEach((a) => { (pool[a.el] = pool[a.el] || []).push(a); }));
    const used = {};
    R.forEach((it) => it.atoms.forEach((a) => { const q = pool[a.el] || []; const n = (used[a.el] = (used[a.el] || 0) + 1) - 1; a.from = q[n] || null; }));
    return { L, R };
  }
  const layouts = new WeakMap();
  function timesAtoms(dur) { return { show: dur * 0.02, brk: dur * 0.3, go: dur * 0.38, land: dur * 0.74, tally: dur * 0.82 }; }
  function atomsScene(s, i, t, dur) {
    let lay = layouts.get(s);
    if (!lay) { lay = atomsLayout(s); layouts.set(s, lay); }
    const T = timesAtoms(dur);
    const breakF = span(t, T.brk, T.go);                       // the old bonds go
    const ball2 = (el, p, size) => {
      const b = ball((s.radii[el] || 0.5) * size, mat(s.colours[el] || "#999999", { emissive: 0x111111, shininess: 110 }));
      b.position.copy(p); world.add(b);
      const gl = glow(s.colours[el] === "#3a3a3a" ? "#9ca3af" : s.colours[el] || "#ffffff", (s.radii[el] || 0.5) * size * 2.6, 0.22);
      if (gl) { gl.position.copy(p); world.add(gl); }
    };
    if (t < T.go) {
      // The reactant particles, whole; then shaking loose.
      lay.L.forEach((it, j) => {
        const pop = ease(span(t, T.show + j * 0.06, T.show + j * 0.06 + 0.5));
        if (pop <= 0) return;
        it.atoms.forEach((a, q) => {
          const jit = breakF > 0 ? V3(Math.sin(t * 40 + q), Math.cos(t * 37 + q * 2), Math.sin(t * 31 + q)).multiplyScalar(0.06 * breakF) : V3(0, 0, 0);
          const out = a.at.clone().sub(it.centre).multiplyScalar(1 + 0.35 * breakF).add(it.centre).add(jit);
          ball2(a.el, out, it.k * pop);
          if (a.to >= 0 && breakF < 0.9) world.add(stick(out, it.atoms[a.to].at.clone().sub(it.centre).multiplyScalar(1 + 0.35 * breakF).add(it.centre), 0.11 * it.k * (1 - breakF)));
          if (breakF > 0.05 && breakF < 0.9 && a.to >= 0) { const f = glow("#fde68a", 0.8 * it.k, 0.7 * Math.sin(Math.PI * breakF)); if (f) { f.position.copy(out); world.add(f); } }
        });
      });
    } else {
      // Every atom on its way to its new partners, then the new bonds.
      const formed = span(t, T.land, T.land + 0.8);
      let idx = 0;
      lay.R.forEach((it) => {
        it.atoms.forEach((a) => {
          const from = a.from ? a.from.at.clone() : a.at.clone().add(V3(-8, 0, 0));
          const startAt = from.clone();
          const f = ease(span(t, T.go + (idx % 12) * 0.05, T.land - 0.15 + (idx % 12) * 0.03));
          idx++;
          const mid = startAt.clone().add(a.at).multiplyScalar(0.5).add(V3(0, 1.6 + (idx % 3) * 0.5, 1.2));
          const curve = new THREE.QuadraticBezierCurve3(startAt, mid, a.at);
          const p = curve.getPoint(f);
          const kk = lerp(a.from ? lay.L.find((x) => x.atoms.includes(a.from)).k : it.k, it.k, f);
          ball2(a.el, p, kk);
          if (f > 0 && f < 1) for (let tr = 1; tr <= 5; tr++) {
            const g = glow(s.colours[a.el] || "#fff", 0.35 * (1 - tr / 6), 0.5 * (1 - tr / 6));
            if (g) { g.position.copy(curve.getPoint(Math.max(0, f - tr * 0.03))); world.add(g); }
          }
          if (a.to >= 0 && formed > 0) world.add(stick(a.at, it.atoms[a.to].at, 0.11 * it.k * formed));
        });
        if (formed > 0 && formed < 1) { const g = glow("#bbf7d0", 2.2 * it.k, 0.6 * (1 - formed)); if (g) { g.position.copy(it.centre); world.add(g); } }
      });
    }
    const orbit = Math.sin(t * 0.25) * 0.25;
    look(V3(Math.sin(orbit) * 16, 1.6 + Math.sin(t * 0.2) * 0.4, Math.cos(orbit) * 16 - span(t, T.go, T.land) * 1.5), V3(0, 0.3, 0));
    // The words: what goes in, what comes out, the count.
    const sideText = (xs) => xs.map((sp) => (sp.count > 1 ? sp.count + " " : "") + sp.pretty).join(" + ");
    hud("Inside the reaction — atom by atom", 48, 52, { size: 30, reveal: span(t, 0.2, 1.4), colour: "#e2e8f0" });
    hud(sideText(s.left2), 320, 610, { size: 30, align: "center", alpha: span(t, 0.4, 1.0), colour: "#fde68a" });
    hud("→", 640, 610, { size: 34, align: "center", alpha: span(t, T.go, T.go + 0.5), colour: "#ffffff" });
    hud(sideText(s.right2), 960, 610, { size: 30, align: "center", alpha: span(t, T.land, T.land + 0.6), colour: "#a7f3d0" });
    caption("The bonds break…", t, T.brk, T.go + 0.4, "#fde68a");
    caption("…every atom finds new partners", t, T.go + 0.4, T.land + 0.3, "#e2e8f0");
    const keys = Object.keys(s.tally || {}).sort((a, b) => (s.tally[b] - s.tally[a]));
    const count = keys.map((e) => `${s.tally[e]} ${e}`).join(" · ");
    const ft = span(t, T.tally, T.tally + 0.6);
    hud(`Atoms in: ${count}   =   Atoms out: ${count}`, 640, 668, { size: 23, align: "center", alpha: ft, colour: "#4ade80", weight: 600 });
    hud(s.equation, 640, 120, { size: 40, align: "center", alpha: span(t, T.tally + 0.4, T.tally + 1.0), colour: "#ffffff" });
    // A key to the colours.
    let kx = 1230;
    keys.slice().reverse().forEach((e) => { hud(`● ${e}`, kx, 52, { size: 24, align: "right", colour: s.colours[e] === "#3a3a3a" ? "#9ca3af" : s.colours[e], alpha: span(t, 0.3, 1.0) }); kx -= 26 + e.length * 15; });
  }

  // ── the sounds: the same beats, placed on the board's clock (sfx.js) ──
  function sounds(starts, total) {
    if (!window.sfxAt) return;
    scenes.forEach((s, i) => {
      if (!CINE[s.scene]) return;
      const at = starts[i], dur = (i + 1 < starts.length ? starts[i + 1] : total) - at;
      const S = (t, kind, gain, pitch) => window.sfxAt(at + t, kind, gain, pitch);
      if (s.scene === "chem_atom") {
        const total2 = s.shells.reduce((x, y) => x + y, 0);
        const a = s.short ? dur * 0.08 : dur * 0.12, b = s.short ? dur * 0.7 : dur * 0.67;
        if (!s.short) { S(0.05, "riser", 0.5); S(dur * 0.06, "whoosh", 0.6, 0.8); }
        let c = 0;
        s.shells.forEach((n, k) => { for (let e = 0; e < n; e++) { c++; S(a + (b - a) * (c / total2) - 0.02, "pop", 0.45, 1.35 - 0.12 * k); } });
        S(b + 0.1, "chime", s.short ? 0.4 : 0.6);
      } else if (s.scene === "chem_ionic") {
        const T = timesIonic(s, dur);
        S(0.1, "riser", 0.4); S(T.weak, "whoosh", 0.55, 0.9); S(T.strong, "whoosh", 0.55, 1.1);
        (s.moves || []).forEach((_, n) => { S(T.move(n), "whoosh", 0.8, 1.25); S(T.move(n) + T.per * 0.85, "ding", 0.55, 1 + n * 0.06); });
        S(T.ions - 0.1, "zap", 0.6); S(T.attract + 0.55, "snap", 0.8); S(T.lattice, "riser", 0.45);
        for (let j = 0; j < 8; j++) S(T.lattice + 0.4 + j * ((dur * 0.97 - T.lattice) / 10), "pop", 0.3, 0.8 + j * 0.06);
        S(T.lattice + 0.7, "chime", 0.6);
      } else if (s.scene === "chem_atoms") {
        const T = timesAtoms(dur);
        S(0.05, "whoosh", 0.5, 0.8);
        S(T.brk, "zap", 0.55); S(T.brk + 0.25, "snap", 0.5);
        S(T.go, "whoosh", 0.8, 1.15); S(T.go + 0.6, "whoosh", 0.5, 1.35);
        const n = (s.right2 || []).reduce((a, sp) => a + sp.count, 0);
        for (let j = 0; j < Math.min(8, n); j++) S(T.land + j * 0.09, "pop", 0.45, 0.9 + j * 0.07);
        S(T.tally, "chime", 0.6);
      } else {
        const T = timesCovalent(s, dur);
        S(0.05, "whoosh", 0.6, 0.85);
        for (let j = 0; j < T.nb; j++) { S(T.pair(j) + T.pairLen * 0.95, "click", 0.7); S(T.pair(j) + T.pairLen, "ding", 0.4, 1 + j * 0.1); }
        S(T.model - 1.2, "riser", 0.5); S(T.model + 0.6, "chime", 0.6);
      }
    });
  }
  window.__sfx3d = sounds;

  // ── the clock: which scene, how far into it ──
  let shown = false;
  function frame(time) {
    const starts = window.__starts || [];
    let i = -1;
    for (let k = 0; k < starts.length; k++) if (starts[k] <= time) i = k;
    const s = scenes[i];
    if (!s || !KINDS[s.scene]) {
      if (shown) { canvas.style.display = "none"; shown = false; }
      return;
    }
    if (!shown) { canvas.style.display = "block"; shown = true; size(); }
    const t = time - starts[i], dur = (i + 1 < starts.length ? starts[i + 1] : window.__total || time + 5) - starts[i];
    while (world.children.length) world.remove(world.children[0]);
    while (hudScene.children.length) hudScene.remove(hudScene.children[0]);
    const cine = !!CINE[s.scene];
    scene3.background = cine ? bgTex : null;
    scene3.fog = cine ? fog : null;
    ambient.intensity = cine ? 0.4 : 0.55; key.intensity = cine ? 1.0 : 0.85; rim.intensity = cine ? 0.7 : 0.35;
    if (cine) { dust.rotation.y = time * 0.01; dust.position.x = Math.sin(time * 0.05) * 1.5; world.add(dust); }
    if (s.scene === "chem_atom") atomScene(s, i, t, dur);
    else if (s.scene === "chem_ionic") ionicScene(s, i, t, dur);
    else if (s.scene === "chem_covalent") covalentScene(s, i, t, dur);
    else if (s.scene === "chem_atoms") atomsScene(s, i, t, dur);
    else if (window.__lab3d && window.__lab3d[s.scene]) window.__lab3d[s.scene](s, t, dur);
    renderer.clear();
    renderer.render(scene3, camera);
    if (hudScene.children.length) { renderer.clearDepth(); renderer.render(hudScene, hudCam); }
  }
  window.__onChem3d = frame;
  window.__chem3dKit = { THREE, world, camera, data, mat, ball, label, rand };
})();
