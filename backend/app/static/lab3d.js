/* The lab in 3D: glassware, burners, stands and clamps, and what happens in
 * them — the reaction on the bench (a metal fizzing in acid, a precipitate
 * falling, a coating growing, a lump darting on water, a metal burning on a
 * spoon or in a gas jar, a powder heated in a tube with the gas bubbling
 * through limewater) and the separations (filtering, evaporating and
 * crystallising, distilling, a separating funnel, a magnet, chromatography,
 * sublimation, dissolving).
 *
 * A part of the 3D layer (chem3d.js gives it the renderer and calls it for
 * the chem_lab and chem_separation scenes). Like the rest, every frame is
 * worked out from the scene and its moment alone, so a rendered frame and a
 * live one agree. The board still writes the words — the names, the gas, the
 * observations, the steps — at its own places, and the apparatus here stands
 * where its flat drawing would have been: a board point (x, y in the
 * 1280×720 board) and a point in the scene line up.
 */
(function () {
  "use strict";
  const LAB = (window.__lab3d = {});
  let K, T, M, W;
  const cache = {};
  const once = (k, make) => cache[k] || (cache[k] = make());

  // The camera stands 20 units from the board, a little above its middle,
  // and a board pixel is 1/PX of a unit on the bench.
  const PX = 720 / (2 * 20 * Math.tan((16 * Math.PI) / 180));
  const U = (px) => px / PX, X = (x) => (x - 640) / PX, Y = (y) => (360 - y) / PX;
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
  const q = (x, n) => Math.round(x * (n || 100)) / (n || 100);

  function init() {
    if (M) return;
    K = window.__chem3dKit; T = K.THREE; W = K.world;
    const ph = (o) => new T.MeshPhongMaterial(o);
    M = {
      glass: ph({ color: 0xdcefff, specular: 0xffffff, shininess: 160, transparent: true, opacity: 0.2, side: T.DoubleSide, depthWrite: false }),
      tubeGlass: ph({ color: 0xbcd9ee, specular: 0xffffff, shininess: 160, transparent: true, opacity: 0.55, depthWrite: false }),
      edge: new T.MeshBasicMaterial({ color: 0x55636f, side: T.DoubleSide }),
      metal: ph({ color: 0xaab3bd, specular: 0xffffff, shininess: 110 }),
      dark: ph({ color: 0x3b4350, specular: 0x555555, shininess: 40 }),
      porcelain: ph({ color: 0xf4f4ee, specular: 0x999999, shininess: 60, side: T.DoubleSide }),
      paper: ph({ color: 0xfffdf6, specular: 0x111111, shininess: 4, side: T.DoubleSide, transparent: true, opacity: 0.6, depthWrite: false }),
      sheet: ph({ color: 0xffffff, specular: 0x111111, shininess: 4, side: T.DoubleSide }),
      wood: ph({ color: 0xc8935a, shininess: 25 }),
      // See-through, so the board's words under the apparatus still show.
      bench: ph({ color: 0xe8e2d6, shininess: 8, transparent: true, opacity: 0.55, depthWrite: false }),
      benchEdge: ph({ color: 0xc9bfae, shininess: 8, transparent: true, opacity: 0.7, depthWrite: false }),
      rubber: ph({ color: 0xc0392b, shininess: 70 }),
      cork: ph({ color: 0x9c6b3c, shininess: 15 }),
      magnet: ph({ color: 0xd62828, specular: 0xffffff, shininess: 90 }),
      bubble: ph({ color: 0xffffff, specular: 0xffffff, shininess: 200, transparent: true, opacity: 0.6, depthWrite: false }),
      wool: ph({ color: 0xffffff, shininess: 2 }),
      pencil: new T.MeshBasicMaterial({ color: 0x6b7280, side: T.DoubleSide }),
      mercury: new T.MeshBasicMaterial({ color: 0xdc2626 }),
    };
    M.gauze = ph({ map: gauzeTexture(), transparent: true, side: T.DoubleSide, shininess: 30 });
  }

  // ── textures drawn on a canvas once ──
  function gauzeTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const x = c.getContext("2d");
    x.strokeStyle = "#6b7280"; x.lineWidth = 2;
    for (let k = 4; k < 256; k += 12) { x.beginPath(); x.moveTo(k, 0); x.lineTo(k, 256); x.moveTo(0, k); x.lineTo(256, k); x.stroke(); }
    x.fillStyle = "#efeae0"; x.beginPath(); x.arc(128, 128, 70, 0, Math.PI * 2); x.fill();
    return new T.CanvasTexture(c);
  }
  function soft(hex) {
    return once("soft" + hex, () => {
      const c = document.createElement("canvas"); c.width = c.height = 128;
      const x = c.getContext("2d"), g = x.createRadialGradient(64, 64, 0, 64, 64, 64);
      g.addColorStop(0, hex); g.addColorStop(0.35, hex); g.addColorStop(1, "rgba(255,255,255,0)");
      x.fillStyle = g; x.fillRect(0, 0, 128, 128);
      return new T.CanvasTexture(c);
    });
  }
  function wave() {
    return once("wave", () => {
      const c = document.createElement("canvas"); c.width = 64; c.height = 128;
      const x = c.getContext("2d");
      x.strokeStyle = "#e8261b"; x.lineWidth = 5; x.lineCap = "round";
      x.beginPath(); x.moveTo(32, 124); x.quadraticCurveTo(52, 94, 32, 64); x.quadraticCurveTo(12, 34, 32, 4); x.stroke();
      return new T.CanvasTexture(c);
    });
  }
  function sprite(tex, key, op, w, h) {
    const o = q(op, 20);
    const m = once(`sp${key}${o}`, () => new T.SpriteMaterial({ map: tex, transparent: true, opacity: o, depthWrite: false }));
    const s = new T.Sprite(m); s.scale.set(w, h || w, 1); return s;
  }
  const glow = (hex, size, op) => sprite(soft(hex), "g" + hex, op, size);

  // ── materials by colour (cached; a colour mid-change is rounded to a step) ──
  const col = (hex, fallback) => (typeof hex === "string" && /^#[0-9a-f]{3,8}$/i.test(hex) ? hex : fallback || "#dff3ff");
  function mix(a, b, f) {
    a = col(a);
    if (!b || f <= 0) return a;
    b = col(b, a);
    if (f >= 1) return b;
    return "#" + new T.Color(a).lerp(new T.Color(b), Math.round(f * 24) / 24).getHexString();
  }
  const solidMat = (hex, shine) => once(`s${hex}${shine ? 1 : 0}`, () => new T.MeshPhongMaterial({ color: new T.Color(col(hex, "#999")), specular: shine ? 0xffffff : 0x333333, shininess: shine ? 120 : 25 }));
  // Liquids show their outside only: a clear mesh drawing its far side too
  // sorts its own triangles badly and the surface turns to teeth.
  const wet = (hex, op) => { const o = q(op, 20); return once(`w${hex}${o}`, () => new T.MeshPhongMaterial({ color: new T.Color(col(hex)), specular: 0xffffff, shininess: 120, transparent: true, opacity: o, side: T.FrontSide, depthWrite: false })); };
  // A colourless liquid is seen by its tint and its shine, not as milk.
  const clearish = (hex) => { const c = new T.Color(col(hex)); return c.r + c.g + c.b > 2.6; };
  // A white solid on a white board: a shade darker, so it is seen.
  const seen = (hex) => { const c = new T.Color(col(hex, "#f5f5f5")); return c.r + c.g + c.b > 2.7 ? "#" + c.multiplyScalar(0.84).getHexString() : col(hex); };
  const fire = (hex, op) => { const o = q(op, 20); return once(`f${hex}${o}`, () => new T.MeshBasicMaterial({ color: new T.Color(col(hex, "#4ea8ff")), transparent: true, opacity: o, side: T.DoubleSide, depthWrite: false })); };

  // ── geometry ──
  const V2 = (p) => new T.Vector2(Math.max(0, p[0]), p[1]);
  const geo = (key, make) => once("g:" + key, make);
  const mesh = (g, m) => new T.Mesh(g, m);
  function rAt(pts, y) {                        // a profile's radius at height y
    for (let i = 1; i < pts.length; i++) {
      const [r0, y0] = pts[i - 1], [r1, y1] = pts[i];
      if (y <= y1 && y >= y0) return y1 === y0 ? Math.max(r0, r1) : r0 + ((r1 - r0) * (y - y0)) / (y1 - y0);
    }
    return y < pts[0][1] ? pts[0][0] : pts[pts.length - 1][0];
  }
  // What fills a vessel between two heights: the inside of its profile, closed flat.
  function band(key, pts, lo, hi, inset) {
    lo = q(lo); hi = q(hi);
    return geo(`b${key}:${lo}:${hi}:${inset}`, () => {
      const out = [[0, lo], [rAt(pts, lo) - inset, lo]];
      for (const [r, y] of pts) if (y > lo && y < hi) out.push([r - inset, y]);
      out.push([rAt(pts, hi) - inset, hi], [0, hi]);
      return new T.LatheGeometry(out.map(V2), 40);
    });
  }
  function rod(a, b, r, m) {
    const g = mesh(geo("rod" + r, () => new T.CylinderGeometry(r, r, 1, 10)), m);
    g.scale.y = a.distanceTo(b);
    g.position.copy(a).add(b).multiplyScalar(0.5);
    g.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    return g;
  }
  function ringAt(r, y, w, m) {
    const o = mesh(geo(`r${q(r)}:${w}`, () => new T.TorusGeometry(r, w, 6, 72)), m || M.edge);
    o.rotation.x = Math.PI / 2; o.position.y = y; return o;
  }

  // Glassware: the body (clear), its outline drawn on both sides and round
  // the rim, so it reads on a white board as glass does on a bench.
  const P = {
    beaker: (w, h) => { const r = w / 2; return [[0, 0], [r, 0], [r, h], [r * 1.06, h + 0.06]]; },
    tube: (r, h) => {
      const p = [];
      for (let k = 0; k <= 8; k++) { const a = -Math.PI / 2 + (k * Math.PI) / 16; p.push([r * Math.cos(a), r + r * Math.sin(a)]); }
      p.push([r, h], [r * 1.14, h + 0.04]); return p;
    },
    conical: (rb, h, rn) => [[0, 0], [rb, 0], [rb, 0.12], [rn, h * 0.72], [rn, h], [rn * 1.15, h + 0.04]],
    round: (R, rn, neck) => {
      const p = [], top = Math.acos(rn / R);
      for (let k = 0; k <= 16; k++) { const a = -Math.PI / 2 + ((top + Math.PI / 2) * k) / 16; p.push([R * Math.cos(a), R + R * Math.sin(a)]); }
      const y0 = R + R * Math.sin(top);
      p.push([rn, y0 + neck], [rn * 1.15, y0 + neck + 0.04]); return p;
    },
    jar: (r, h) => [[0, 0], [r * 1.12, 0], [r * 1.12, 0.14], [r, 0.16], [r, h], [r * 1.12, h], [r * 1.12, h + 0.06]],
    trough: (r, h) => [[0, 0], [r, 0], [r * 1.04, h], [r * 1.08, h + 0.05]],
    funnel: (rt, h, rs, sh) => [[rs, 0], [rs, sh], [rt, sh + h], [rt * 1.04, sh + h + 0.03]],
    sepFunnel: (k) => [[0.05, 0], [0.05, 0.9], [0.09, 1.0], [0.09, 1.25], [0.35, 1.45], [0.8, 2.0], [1.0, 2.5], [0.95, 2.9], [0.6, 3.35], [0.2, 3.6], [0.2, 3.85], [0.24, 3.9]].map(([r, y]) => [r * k, y * k]),
    dish: (R, d) => { const p = []; for (let k = 0; k <= 12; k++) { const r = (R * k) / 12; p.push([r, d * (r / R) ** 2]); } p.push([R * 1.07, d * 1.04]); return p; },
    crucible: (k) => [[0, 0], [0.42 * k, 0], [0.66 * k, k], [0.7 * k, k * 1.02]],
  };
  function vessel(kind, ...a) {
    const pts = P[kind](...a), key = kind + a.map((x) => q(x)).join(":");
    const opaque = kind === "dish" || kind === "crucible";
    const g = new T.Group();
    g.add(mesh(geo("l" + key, () => new T.LatheGeometry(pts.map(V2), 56)), opaque ? M.porcelain : M.glass));
    if (!opaque) {
      const line = geo("o" + key, () => {
        const path = new T.CurvePath();
        for (let i = 1; i < pts.length; i++) path.add(new T.LineCurve3(new T.Vector3(pts[i - 1][0], pts[i - 1][1], 0), new T.Vector3(pts[i][0], pts[i][1], 0)));
        return new T.TubeGeometry(path, pts.length * 8, 0.026, 5, false);
      });
      const l = mesh(line, M.edge), r = mesh(line, M.edge); r.scale.x = -1;
      g.add(l, r);
      if (pts[0][0] === 0 && pts[1][1] === pts[0][1]) g.add(ringAt(pts[1][0], pts[1][1], 0.026));
    }
    const top = pts[pts.length - 1];
    g.add(ringAt(top[0], top[1], 0.026, opaque ? M.porcelain : M.edge));
    const v = { g, pts, key, h: top[1] };
    v.r = (y) => rAt(pts, y);
    v.fill = (lo, hi, colour, op, inset) => {
      const m = mesh(band(key, pts, Math.max(0.04, lo), Math.min(hi, v.h - 0.03), inset == null ? 0.03 : inset), wet(colour, op == null ? 0.72 : op));
      g.add(m); return m;
    };
    // The lowest height a particle of radius pr can sit at, pr from the axis by d.
    v.floor = (d, pr) => { for (let y = 0.02; y < v.h; y += 0.02) if (rAt(pts, y) >= d + pr) return y + pr * 0.8; return pr; };
    return v;
  }
  function put(obj, xPx, yPx, z) { obj.position.set(X(xPx), Y(yPx), z || 0); W.add(obj); return obj; }

  // ── the rest of the apparatus ──
  function bench(floor) {
    const g = new T.Group();
    const top = mesh(geo("bench", () => new T.BoxGeometry(26, 0.12, 2.6)), M.bench);
    top.position.set(0, -0.06, -0.3); g.add(top);
    const lip = mesh(geo("benchLip", () => new T.BoxGeometry(26, 0.05, 0.05)), M.benchEdge);
    lip.position.set(0, -0.01, 1.0); g.add(lip);
    return put(g, 640, floor, 0);
  }
  function flame(tt, on, colour, size) {
    const g = new T.Group();
    if (on <= 0) return g;
    colour = col(colour, "#4ea8ff");
    const white = /^#f{3}$|^#f{6}$/i.test(colour);
    const f = 1 + 0.1 * Math.sin(tt * 17) + 0.05 * Math.sin(tt * 31 + 1);
    const outer = mesh(geo("fo", () => new T.ConeGeometry(0.24, 1.3, 24, 1, true)), fire(white ? "#ffe9a8" : colour, 0.55 * on));
    outer.position.y = 0.65;
    const inner = mesh(geo("fi", () => new T.ConeGeometry(0.12, 0.6, 20, 1, true)), fire(white ? "#fffbe6" : colour === "#4ea8ff" ? "#1e40af" : "#ffffff", 0.7 * on));
    inner.position.y = 0.3;
    g.add(outer, inner);
    g.scale.set(size * on, size * on * f, size * on);
    if (white) { const s = glow("#ffe680", 3.4, 0.85 * on); s.position.y = 0.6; s.scale.multiplyScalar(f); g.add(s); }
    return g;
  }
  function burner(tt, on, colour) {
    // A Bunsen burner: base, barrel, air-hole collar, gas inlet; its flame. 2.06 units to the barrel's top.
    const g = new T.Group();
    const base = mesh(geo("bb", () => new T.CylinderGeometry(0.72, 0.82, 0.16, 32)), M.dark); base.position.y = 0.08;
    const barrel = mesh(geo("bbar", () => new T.CylinderGeometry(0.15, 0.15, 1.9, 20)), M.metal); barrel.position.y = 1.11;
    const collar = mesh(geo("bcol", () => new T.CylinderGeometry(0.2, 0.2, 0.28, 20)), M.metal); collar.position.y = 0.45;
    const inlet = mesh(geo("binl", () => new T.CylinderGeometry(0.06, 0.06, 0.7, 10)), M.metal); inlet.rotation.z = Math.PI / 2; inlet.position.set(0.5, 0.32, 0);
    g.add(base, barrel, collar, inlet);
    const fl = flame(tt, on, colour || "#4ea8ff", 1); fl.position.y = 2.06; g.add(fl);
    return g;
  }
  function tripod(h, r, gauze) {
    const g = new T.Group();
    g.add(ringAt(r, h, 0.05, M.dark));
    for (let k = 0; k < 3; k++) {
      const a = (k * 2 * Math.PI) / 3 + 0.5;
      g.add(rod(new T.Vector3(Math.cos(a) * r, h, Math.sin(a) * r), new T.Vector3(Math.cos(a) * r * 1.3, 0, Math.sin(a) * r * 1.3), 0.05, M.dark));
    }
    if (gauze) {
      const gz = mesh(geo("gz" + q(r), () => new T.BoxGeometry(r * 2.5, 0.03, r * 2.5)), M.gauze);
      gz.position.y = h + 0.05; g.add(gz);
    }
    return g;
  }
  function stand(xPx, floor, h) {
    const g = new T.Group();
    const base = mesh(geo("sb", () => new T.BoxGeometry(1.6, 0.14, 1.1)), M.dark); base.position.set(0.5, 0.07, 0);
    const pole = mesh(geo("sr" + q(h), () => new T.CylinderGeometry(0.06, 0.06, h, 12)), M.metal); pole.position.y = h / 2;
    g.add(base, pole);
    return put(g, xPx, floor, -1);
  }
  function arm(st, yPx, toXPx, toZ) {
    // A clamp's arm from the stand to a point on the board; the boss on the stand.
    const a = new T.Vector3(st.position.x, Y(yPx), st.position.z), b = new T.Vector3(X(toXPx), Y(yPx), toZ || 0);
    W.add(rod(a, b, 0.045, M.metal));
    const boss = mesh(geo("boss", () => new T.BoxGeometry(0.2, 0.22, 0.2)), M.dark); boss.position.copy(a); W.add(boss);
    return b;
  }
  function jaws(p, r, angle) {
    const g = new T.Group();
    [-1, 1].forEach((s) => { const j = mesh(geo("jaw", () => new T.BoxGeometry(0.1, 0.34, 0.24)), M.cork); j.position.x = s * (r + 0.05); g.add(j); });
    g.position.copy(p); g.rotation.z = angle || 0; W.add(g);
  }
  function ringClamp(p, r) { const o = ringAt(r, 0, 0.04, M.metal); o.position.add(p); W.add(o); }
  function rack(xPx, floor, topPx) {
    // A wooden test-tube rack: a base, two posts and a top board the tube goes through.
    const g = new T.Group(), h = Y(topPx) - Y(floor);
    const base = mesh(geo("rkb", () => new T.BoxGeometry(1.2, 0.1, 0.7)), M.wood); base.position.y = 0.05;
    const top = mesh(geo("rkt", () => new T.BoxGeometry(1.2, 0.08, 0.7)), M.wood); top.position.y = h;
    g.add(base, top);
    [-0.55, 0.55].forEach((x) => { const p = mesh(geo("rkp" + q(h), () => new T.BoxGeometry(0.08, h, 0.6)), M.wood); p.position.set(x, h / 2, 0); g.add(p); });
    return put(g, xPx, floor, 0);
  }
  function dropper() {
    // A teat pipette, its tip at the origin.
    const g = new T.Group();
    g.add(mesh(geo("dp", () => new T.LatheGeometry([[0.025, 0], [0.065, 0.2], [0.065, 1.2]].map(V2), 20)), M.tubeGlass));
    const bulb = mesh(geo("db", () => new T.SphereGeometry(1, 20, 14)), M.rubber); bulb.scale.set(0.14, 0.28, 0.14); bulb.position.y = 1.42;
    g.add(bulb);
    return g;
  }
  function pipe(key, pts, r, m) {
    // A bent glass tube (delivery tube, side arm) through board points.
    return mesh(geo("pipe" + key, () => new T.TubeGeometry(new T.CatmullRomCurve3(pts, false, "catmullrom", 0.05), 64, r || 0.05, 8, false)), m || M.tubeGlass);
  }
  function bung(r, y) { const b = mesh(geo("bung" + q(r), () => new T.CylinderGeometry(r * 1.15, r * 0.95, 0.32, 20)), M.cork); b.position.y = y; return b; }
  function thermometer(len) {
    const g = new T.Group();
    const stem = mesh(geo("th" + q(len), () => new T.CylinderGeometry(0.05, 0.05, len, 10)), M.tubeGlass); stem.position.y = len / 2;
    const line = mesh(geo("thl" + q(len), () => new T.CylinderGeometry(0.018, 0.018, len * 0.6, 6)), M.mercury); line.position.y = len * 0.3;
    const bulb = K.ball(0.07, M.mercury);
    g.add(stem, line, bulb);
    return g;
  }
  function magnet() {
    // A horseshoe magnet, poles down; the origin at the middle of its bend.
    const g = new T.Group();
    g.add(mesh(geo("mgArc", () => new T.TorusGeometry(0.55, 0.2, 12, 32, Math.PI)), M.magnet));
    [-0.55, 0.55].forEach((x) => {
      const leg = mesh(geo("mgLeg", () => new T.CylinderGeometry(0.2, 0.2, 0.8, 16)), M.magnet); leg.position.set(x, -0.4, 0);
      const tip = mesh(geo("mgTip", () => new T.CylinderGeometry(0.2, 0.2, 0.25, 16)), M.metal); tip.position.set(x, -0.92, 0);
      g.add(leg, tip);
    });
    return g;
  }

  // ── what happens: bubbles, drops, smoke, heat ──
  function bubbles(parent, n, src, topY, tt, seed, size) {
    const rnd = K.rand(seed);
    for (let j = 0; j < n; j++) {
      const rise = 0.9 + rnd() * 0.9, st = rnd() * 1.2, pos = src(rnd), wob = rnd() * 6.28, sz = 0.7 + rnd() * 0.6;
      if (tt < st) continue;
      const ph = ((tt - st) % rise) / rise;
      const b = K.ball((size || 0.06) * (0.6 + 0.8 * ph) * sz, M.bubble);
      b.position.set(pos[0] + Math.sin(tt * 5 + wob) * 0.03, pos[1] + (topY - pos[1]) * ph, pos[2]);
      parent.add(b);
    }
  }
  function puffs(parent, x, y, z, tt, hex, n, height, spread) {
    for (let j = 0; j < n; j++) {
      const per = 2.4, ph = (((tt + (j * per) / n) % per) + per) % per / per;
      if (tt < (j * per) / n * 0.3) continue;
      const s = glow(hex, 0.35 + ph * (spread || 1.2), 0.45 * (1 - ph));
      s.position.set(x + Math.sin(j * 2.1 + tt) * 0.2 * ph, y + ph * height, z);
      parent.add(s);
    }
  }
  function shimmer(parent, x, y, tt) {
    for (let k = 0; k < 3; k++) {
      const op = 0.4 + 0.4 * Math.sin(tt * 3 + k * 1.3);
      const s = sprite(wave(), "wave", Math.max(0, op), 0.3, 0.6);
      s.position.set(x + (k - 1) * 0.7, y + 0.3 + ((tt * 0.4 + k * 0.3) % 1) * 0.4, 0.3);
      parent.add(s);
    }
  }
  function drip(parent, x, y1, y2, tt, every, hex, from) {
    // Drops falling from a tip again and again (a stem, a condenser).
    if (tt < (from || 0)) return;
    for (let k = 0; k < 2; k++) {
      const ph = (((tt - (from || 0)) / every + k * 0.5) % 1);
      const d = K.ball(0.06, wet(hex, 0.9)); d.scale.y = 0.08;
      d.position.set(x, y1 + (y2 - y1) * ph * ph, 0);
      parent.add(d);
    }
  }
  // A slow sway, and a push in towards the bench as the reaction starts —
  // small, so the board's words stay beside what they name.
  function camera(t, tt, cx) {
    const push = tt == null ? 0 : Math.exp(-((tt - 1.6) ** 2) / 2.2);
    const aim = X(cx || 640) * 0.18 * push;
    K.camera.position.set(Math.sin((t || 0) * 0.22) * 0.45 + aim, 5 - push * 0.7, 19.4 - push * 1.6);
    K.camera.lookAt(aim * 0.6, -0.5 * push, 0);
  }

  // ═══ the bench: the reaction ═══
  LAB.chem_lab = function (s, t, dur) {
    init();
    const lab = s.lab || {}, kind = lab.vessel || "beaker";
    const t0 = s._t0 != null ? s._t0 : Math.min(2, dur * 0.3), span = s._span != null ? s._span : Math.max(1.5, dur - t0 - 0.3);
    const tt = t - t0, at = (a, d) => clamp01((tt - a) / Math.max(0.01, d));
    const social = !!K.data.social, cx = social ? 640 : 470, floor = 650;
    camera(t, tt, cx);
    const heatBelow = !!lab.burner || (!!lab.flame && kind === "beaker");
    bench(floor);
    const shrink = lab.solid_shrinks ? 1 - 0.85 * ease(at(1, span * 0.85)) : 1;
    const solidC = lab.solid ? mix(lab.solid, lab.solid_to, at(1, span * 0.6)) : null;
    let liquidC = lab.liquid ? mix(lab.liquid, lab.liquid_to, at(1, span * 0.75)) : null;
    if (liquidC && lab.precipitate) liquidC = mix(liquidC, lab.precipitate, 0.25 * at(0.9, span * 0.5));
    const on = lab.flame || lab.burner ? at(0.6, 0.4) : 0;

    if (kind === "heated_tube") return heatedTube();
    if (kind === "spoon") return spoon();
    if (kind === "gas_jar") return gasJar();
    if (kind === "crucible") return crucible();
    if (kind === "burner") return burnerOnly();
    return openVessel();

    // A beaker, a test tube held in a clamp, a trough, or a flask with a
    // delivery tube to limewater — with what goes in and what is seen.
    function openVessel() {
      let v, x = cx, base = floor, level;
      const tube = kind === "test_tube", trough = kind === "trough", flask = !!lab.limewater;
      if (tube) {
        v = vessel("tube", U(42), U(320)); base = floor - 40;
        const st = stand(cx - 200, floor, U(440));
        const p = arm(st, base - 250, cx); jaws(p, U(42));
      } else if (trough) v = vessel("trough", U(190), U(140));
      else if (flask) v = vessel("conical", U(118), U(290), U(30));
      else if (heatBelow) {
        put(tripod(U(150), U(95), true), cx, floor);
        put(burner(tt, on, "#4ea8ff"), cx, floor);
        v = vessel("beaker", U(200), U(230)); base = floor - 155;
      } else v = vessel("beaker", U(230), U(290));
      level = v.h * (tube ? 0.55 : trough ? 0.62 : flask ? 0.42 : 0.62);
      put(v.g, x, base);
      // With a precipitate the liquid stays fairly clear, so the solid's own colour shows through it.
      if (liquidC) v.fill(0.04, level, liquidC, lab.precipitate ? 0.38 : clearish(liquidC) ? (trough ? 0.28 : 0.42) : 0.72);
      const g = v.g, rIn = v.r(level * 0.5);

      // The solid: a strip of metal lowered in, lumps of a carbonate, or a lump darting on the water.
      let src = (rnd) => { const a = rnd() * 6.28, d = rnd() * rIn * 0.6; return [Math.cos(a) * d, v.floor(d, 0.05), Math.sin(a) * d]; };
      if (lab.solid && tt >= 0) {
        const drop = (1 - ease(at(0, 0.8))) * (v.h + 1.5);
        if (trough) {
          const r = 0.32 * Math.max(0.2, shrink), wx = lab.solid_moves ? Math.sin(tt * 2.3) * rIn * 0.55 : 0, wz = lab.solid_moves ? Math.cos(tt * 1.7) * 0.5 : 0;
          const lump = K.ball(r, solidMat(solidC, true)); lump.scale.y = r * 0.7;
          lump.position.set(wx, level + r * 0.3 + drop, wz); g.add(lump);
          if (lab.flame) { const f = flame(tt, at(0.8, 0.3), lab.flame, 0.55 * Math.max(0.3, shrink)); f.position.set(wx, level + r * 0.6, wz); g.add(f); }
          src = (rnd) => [wx + (rnd() - 0.5) * 0.5, level - 0.1, wz + (rnd() - 0.5) * 0.3];
          puffs(g, wx, level + 0.3, wz, tt, "#cfd6dd", 4, 1.2, 0.6);
        } else if (lab.bubbles === "CO2") {
          const rnd = K.rand(91);
          const lumps = [];
          for (let k = 0; k < 6; k++) {
            const a = rnd() * 6.28, d = rnd() * rIn * 0.55, r = (0.18 + rnd() * 0.12) * (tube ? 0.6 : 1) * Math.max(0.2, shrink);
            const l = mesh(geo("lump", () => new T.DodecahedronGeometry(1, 0)), solidMat(solidC));
            l.scale.setScalar(r); l.rotation.set(rnd() * 3, rnd() * 3, 0);
            l.position.set(Math.cos(a) * d, v.floor(d, r) + drop, Math.sin(a) * d); g.add(l); lumps.push(l.position.clone());
          }
          src = (rnd) => { const p = lumps[Math.floor(rnd() * lumps.length)]; return [p.x + (rnd() - 0.5) * 0.2, p.y + 0.1, p.z + (rnd() - 0.5) * 0.2]; };
        } else {
          const sw = tube ? 0.28 : 0.55, sh = (tube ? 1.5 : 1.9) * shrink, y0 = tube ? U(42) * 0.5 : 0.05;
          const strip = mesh(geo("strip", () => new T.BoxGeometry(1, 1, 1)), solidMat(lab.coating ? mix(solidC, lab.coating, 0.5 * at(1.2, span * 0.7)) : solidC, true));
          strip.scale.set(sw * (0.4 + 0.6 * shrink), sh, 0.05);
          strip.position.set(0, y0 + sh / 2 + drop, 0); g.add(strip);
          if (lab.coating) {
            const rnd = K.rand(55);
            for (let k = 0; k < 46; k++) {
              const px = (rnd() - 0.5) * sw, py = y0 + rnd() * sh * 0.9, side = rnd() < 0.5 ? -1 : 1, when = 1.2 + rnd() * span * 0.7, r = 0.025 + rnd() * 0.03;
              if (tt < when || py > level) continue;
              const sp = K.ball(r * ease(clamp01((tt - when) / 0.6)), solidMat(lab.coating));
              sp.position.set(px, py + drop, side * 0.03); g.add(sp);
            }
          }
          src = (rnd) => [(rnd() - 0.5) * sw, y0 + rnd() * sh, (rnd() < 0.5 ? -1 : 1) * 0.05];
        }
      }
      // Drops from a dropper above the mouth.
      if (lab.drops && tt >= -0.2) {
        const d = dropper(); d.position.set(0, v.h + 0.5, 0); g.add(d);
        for (let k = 0; k < 6; k++) {
          const when = 0.5 + k * ((span * 0.45) / 6), ph = (tt - when) / 0.5;
          if (ph < 0 || ph > 1) continue;
          const dr = K.ball(0.07, wet(lab.drop_colour || "#9ad1ff", 0.9));
          dr.position.set(0, v.h + 0.5 + (level - v.h - 0.5) * ph * ph, 0); g.add(dr);
        }
      }
      // A precipitate: specks that appear as the drops land, then settle.
      if (lab.precipitate) {
        const rnd = K.rand(17);
        for (let k = 0; k < 110; k++) {
          const a = rnd() * 6.28, d = rnd(), y = rnd(), when = 0.9 + rnd() * span * 0.35, r = (0.04 + rnd() * 0.04) * (tube ? 0.8 : 1), heap = rnd();
          if (tt < when) continue;
          const yy = v.floor(d * rIn * 0.8, r) + y * (level - 0.3) * 0.7, rest = v.floor(d * rIn * 0.6, r) + heap * 0.12;
          const f = ease(clamp01((tt - when - 0.4) / (span * 0.4)));
          const p = K.ball(r, solidMat(seen(lab.precipitate)));
          p.position.set(Math.cos(a) * d * rIn * (0.8 - 0.2 * f), yy + (rest - yy) * f, Math.sin(a) * d * rIn * (0.8 - 0.2 * f)); g.add(p);
        }
      }
      if (lab.bubbles && liquidC) bubbles(g, lab.slow ? 7 : 26, src, level - 0.05, tt - 1, 3, tube ? 0.045 : 0.06);
      if (lab.heat && !heatBelow && !lab.flame) shimmer(g, 0, v.h + 0.2, tt - 1.5);
      if (flask) limewater(v, x, base);
    }

    // The gas led through limewater: a bung, the delivery tube, the limewater turning milky.
    function limewater(v, x, base, from) {
      const lx = cx + 257, lBase = floor - 12, lh = U(200), lr = U(22);
      rack(lx, floor, floor - 90);
      const lw = vessel("tube", lr, lh); put(lw.g, lx, lBase);
      const milky = at(2, span * 0.5);
      lw.fill(0.04, lh * 0.55, mix("#eef7ff", "#f2f2f0", milky), 0.45 + 0.5 * milky);
      const start = from ? from.mouth : new T.Vector3(X(x), Y(base) + v.h, 0);
      if (!from) v.g.add(bung(v.r(v.h - 0.1), v.h - 0.1));
      const end = new T.Vector3(X(lx), Y(lBase) + lr * 1.2, 0);
      const top = Math.max(start.y, Y(lBase) + lh) + 0.7;
      W.add(pipe("dl" + q(start.x) + q(start.y), [start.clone().add(new T.Vector3(0, -0.15, 0)), new T.Vector3(start.x, top, 0), new T.Vector3((start.x + end.x) / 2, top + 0.15, 0), new T.Vector3(end.x, top, 0), end]));
      if (lab.bubbles) bubbles(lw.g, 10, (rnd) => [(rnd() - 0.5) * 0.12, lr * 1.2, 0], lh * 0.55 - 0.04, tt - 1.5, 9, 0.05);
    }

    // A powder heated in a tube held in a clamp; the gas to limewater, or a bright burning.
    function heatedTube() {
      const r = U(36), h = U(300), ang = -1.0, bx = cx - 110, by = floor - 225;
      put(burner(tt, Math.max(on, at(0.6, 0.4)), "#4ea8ff"), bx + 20, floor);
      const v = vessel("tube", r, h); v.g.rotation.z = ang; put(v.g, bx, by);
      const st = stand(cx - 330, floor, U(420));
      const mid = new T.Vector3(X(bx) + Math.sin(-ang) * h * 0.62, Y(by) + Math.cos(-ang) * h * 0.62, 0);
      const p = arm(st, (360 - mid.y * PX), (mid.x * PX + 640)); jaws(p, r, ang);
      if (lab.solid) {
        const heap = K.ball(1, solidMat(solidC));
        heap.scale.set(r * 0.55, r * 1.5, r * 0.6); heap.position.set(r * 0.32, r * 1.5, 0); v.g.add(heap);
        if (lab.flame && /^#f{3,6}$/i.test(lab.flame)) { const gl = glow("#ffe680", 2.2, 0.9 * at(1, 0.4) * (0.85 + 0.15 * Math.sin(tt * 20))); gl.position.set(r * 0.3, r * 1.5, 0.2); v.g.add(gl); }
      }
      const mouth = new T.Vector3(X(bx) + Math.sin(-ang) * h, Y(by) + Math.cos(-ang) * h, 0);
      if (lab.limewater) {
        const b = bung(r, 0); b.position.set(0, h - 0.1, 0); v.g.add(b);
        limewater(v, 0, 0, { mouth });
      } else if (lab.bubbles) puffs(W, mouth.x, mouth.y + 0.2, 0, tt - 1, "#d7dde3", 4, 1.2, 0.8);
    }

    // A deflagrating spoon held in the flame: the solid catches, burns with its colour, smokes.
    function spoon() {
      put(burner(tt, at(0.2, 0.4), "#4ea8ff"), cx, floor);
      const cup = new T.Vector3(X(cx), Y(floor - 236), 0), handle = new T.Vector3(X(cx + 280), Y(floor - 380), 0.6);
      W.add(rod(cup.clone().add(new T.Vector3(0, 0.08, 0)), handle, 0.035, M.metal));
      const grip = rod(handle, handle.clone().add(new T.Vector3(0.9, 0.45, 0.15)), 0.08, M.wood); W.add(grip);
      const c = mesh(geo("cup", () => new T.CylinderGeometry(0.26, 0.2, 0.14, 20, 1, true)), M.metal); c.position.copy(cup); W.add(c);
      const disc = mesh(geo("cupB", () => new T.CircleGeometry(0.2, 20)), M.metal); disc.rotation.x = -Math.PI / 2; disc.position.copy(cup).add(new T.Vector3(0, -0.06, 0)); W.add(disc);
      if (lab.solid) {
        const l = K.ball(0.17 * Math.max(0.5, shrink), solidMat(solidC)); l.scale.y *= 0.6; l.position.copy(cup).add(new T.Vector3(0, 0.05, 0)); W.add(l);
      }
      if (lab.flame) { const f = flame(tt, at(0.9, 0.4), lab.flame, 0.8); f.position.copy(cup).add(new T.Vector3(0, 0.08, 0)); W.add(f); }
      if (lab.smoke) puffs(W, cup.x, cup.y + 0.8, 0, tt - 1.2, "#b9c0c8", 7, 2.4, 1.4);
    }

    // A gas jar of the gas, the solid lowered in on a spoon, burning.
    function gasJar() {
      const v = vessel("jar", U(85), U(300)); put(v.g, cx, floor);
      if (lab.gas) v.fill(0.17, v.h - 0.02, lab.gas, 0.42 * (1 - (lab.gas_fades ? 0.85 * at(span * 0.25, span * 0.5) : 0)), 0.02);
      const low = ease(at(0, 0.9)), cupY = v.h * 0.45 + (1 - low) * (v.h * 0.55 + 1.2);
      const g = v.g;
      g.add(rod(new T.Vector3(0, cupY + 0.08, 0), new T.Vector3(0, cupY + v.h + 0.8, 0), 0.035, M.metal));
      const lid = mesh(geo("lid", () => new T.CylinderGeometry(U(85) * 1.15, U(85) * 1.15, 0.05, 32)), M.metal);
      lid.position.y = Math.max(v.h + 0.06, cupY + v.h * 0.55); g.add(lid);
      const c = mesh(geo("cup", () => new T.CylinderGeometry(0.26, 0.2, 0.14, 20, 1, true)), M.metal); c.position.y = cupY; g.add(c);
      if (lab.solid) { const l = K.ball(0.17 * Math.max(0.5, shrink), solidMat(solidC)); l.scale.y *= 0.6; l.position.y = cupY + 0.05; g.add(l); }
      if (lab.flame) { const f = flame(tt, at(0.9, 0.4), lab.flame, 0.7); f.position.y = cupY + 0.08; g.add(f); }
      if (lab.heat) shimmer(g, 0, v.h + 0.9, tt - 1.5);
    }

    // A crucible on a pipe-clay triangle over the flame: the solid glowing, changing.
    function crucible() {
      const th = U(150);
      put(tripod(th, U(80), false), cx, floor);
      put(burner(tt, Math.max(on, at(0.4, 0.4)), "#4ea8ff"), cx, floor);
      const tri = new T.Group();
      for (let k = 0; k < 3; k++) {
        const a1 = (k * 2 * Math.PI) / 3 + 0.5, a2 = ((k + 1) * 2 * Math.PI) / 3 + 0.5, R = U(80) * 1.05;
        tri.add(rod(new T.Vector3(Math.cos(a1) * R, th + 0.06, Math.sin(a1) * R), new T.Vector3(Math.cos(a2) * R, th + 0.06, Math.sin(a2) * R), 0.04, M.porcelain));
      }
      put(tri, cx, floor);
      const k = 1.6, v = vessel("crucible", k); put(v.g, cx, floor);
      v.g.position.y = Y(floor) + th - 0.12;              // sitting down in the triangle
      if (lab.solid) v.fill(0.06, k * 0.45, solidC, 1, 0.04);
      const gl = glow("#ff9a3c", 1.6, 0.5 * at(1, span * 0.4) * (0.85 + 0.15 * Math.sin(tt * 9))); gl.position.set(0, k * 0.3, 0.8); v.g.add(gl);
      if (lab.heat) shimmer(v.g, 0, k + 0.4, tt - 1.5);
    }

    // A fuel burning: the flame, a cold dry beaker held over it misting with water.
    function burnerOnly() {
      put(burner(tt, at(0.3, 0.4), lab.flame || "#4ea8ff"), cx, floor);
      const v = vessel("beaker", U(170), U(200)); v.g.rotation.z = Math.PI; put(v.g, cx, floor - 410);
      const st = stand(cx - 230, floor, U(480)); const p = arm(st, floor - 330, cx); jaws(p, U(85));
      const rnd = K.rand(33);
      for (let k = 0; k < 40; k++) {
        const a = rnd() * 6.28, y = rnd() * U(170), when = 1 + rnd() * span * 0.7;
        if (tt < when) continue;
        const d = K.ball(0.03 + 0.02 * ease(clamp01((tt - when) / 1)), wet("#9cc9ef", 0.8));
        d.position.set(Math.cos(a) * U(80), y, Math.sin(a) * U(80)); v.g.add(d);
      }
    }
  };

  // ═══ the separations ═══
  LAB.chem_separation = function (s, t, dur) {
    init();
    const m = s.method;
    const t0 = s._t0 != null ? s._t0 : Math.min(1.2, dur * 0.2), span = s._span != null ? s._span : Math.max(2, dur - t0 - 0.3);
    const tt = t - t0, at = (a, d) => clamp01((tt - a) / Math.max(0.01, d));
    const social = !!K.data.social, cx = social ? 640 : 380, floor = 650;
    camera(t, tt, cx);
    bench(floor);
    const water = "#bfe3ff";
    // This mixture's own substances (chem_separation's plan): their colours, which is which.
    const L = s.look || {};
    const C_ = (o, d) => (o && o.colour) || d;
    const nth = (arr, k, d) => (arr && arr.length ? arr[k % arr.length].colour : d);
    // A colourless liquid tinted a little, so a layer or a distillate is seen.
    const vis = (hex) => (clearish(hex) ? mix(hex, "#8fb3d1", 0.35) : hex);
    if (m === "filtration") filtration();
    else if (m === "dissolve" || m === "flotation") dissolve();
    else if (m === "evaporation" || m === "crystallisation" || m === "fractional_crystallisation") evaporation(m !== "evaporation");
    else if (m === "distillation" || m === "fractional_distillation") distillation(m === "fractional_distillation");
    else if (m === "separating_funnel") sepFunnel();
    else if (m === "magnet") magnetic();
    else if (m === "chromatography") chromatography();
    else if (m === "sublimation") sublimation();

    function filtration() {
      // A filter funnel lined with paper in a ring on a stand, the flask below.
      const st = stand(cx - 190, floor, U(470));
      const f = vessel("funnel", U(95), U(110), U(10), U(90)); put(f.g, cx, 450);
      ringClamp(arm(st, 450 - 150, cx), U(68));
      const paper = mesh(geo("fp", () => new T.LatheGeometry([[0.01, 0], [U(88), U(104)]].map(V2), 40)), M.paper);
      paper.position.y = U(90) + 0.03; f.g.add(paper);
      const fl = vessel("conical", U(80), U(170), U(25)); put(fl.g, cx, floor);
      // The muddy water in the paper going down; the sand left on it.
      const left = 1 - ease(at(0.5, span * 0.75)), top = U(90) + U(100) * (0.25 + 0.65 * left);
      if (left > 0.02) f.g.add(mesh(band(f.key + "p", [[0.01, U(90)], [U(84), U(90) + U(100)]], U(90) + 0.08, top, 0.02), wet(mix(C_(L.filtrate, water), nth(L.residue, 0, "#b08a5a"), 0.55), 0.8)));
      const rnd = K.rand(5);
      for (let k = 0; k < 26; k++) {
        const a = rnd() * 6.28, y = rnd(), when = 0.6 + rnd() * span * 0.5;
        if (tt < when) continue;
        const yy = U(90) + 0.12 + y * 0.45, rr = (yy - U(90)) * (U(84) / U(100)) * 0.7;
        const p = K.ball(0.06, solidMat(seen(nth(L.residue, k, "#b08a5a")))); p.position.set(Math.cos(a) * rr, yy, Math.sin(a) * rr); f.g.add(p);
      }
      drip(W, X(cx), Y(450), Y(floor) + fl.h * 0.25, tt, 0.7, vis(C_(L.filtrate, water)), 0.8);
      fl.fill(0.04, 0.05 + fl.h * 0.3 * ease(at(0.8, span * 0.8)), vis(C_(L.filtrate, "#dff3ff")), 0.7);
    }

    function dissolve() {
      const v = vessel("beaker", U(240), U(260)); put(v.g, cx, floor);
      const level = v.h * 0.6;
      const dissolving = (L.dissolves || [])[0] || {};
      v.fill(0.04, level, mix(vis(C_(L.solvent, water)), vis(dissolving.colour || "#eef7ff"), at(1, span * 0.5)), 0.7);
      const ang = tt * 2.2, rodTop = new T.Vector3(Math.cos(ang) * 0.5, v.h + 0.8, Math.sin(ang) * 0.5);
      v.g.add(rod(new T.Vector3(Math.cos(ang) * 0.9, 0.12, Math.sin(ang) * 0.9), rodTop, 0.045, M.tubeGlass));
      const rnd = K.rand(8);
      for (let k = 0; k < 30; k++) {
        const a = rnd() * 6.28, d = rnd() * v.r(1) * 0.8, y = 0.3 + rnd() * (level - 0.5), sinks = k % 2 === 1;
        const f = at(1, span * 0.5), sw = a + tt * (1.4 - 0.9 * f);
        const floats = !sinks && (L.floats || []).length > 0;          // flotation: the light part rises to the top
        const r = sinks || floats ? 0.07 : 0.07 * (1 - f);
        if (r < 0.01) continue;
        const p = K.ball(r, solidMat(seen(sinks ? nth(L.stays, k, "#b08a5a") : floats ? nth(L.floats, k, "#c99a5b") : dissolving.solid || "#ffffff")));
        p.position.set(Math.cos(sw) * d, sinks ? y + (v.floor(d, 0.07) - y) * f : floats ? y + (level - 0.06 - y) * f : y, Math.sin(sw) * d); v.g.add(p);
      }
    }

    function heated(th, x) {
      // A tripod and gauze over a burner; returns the height of the gauze.
      put(tripod(th, U(85), true), x || cx, floor);
      put(burner(tt, at(0.3, 0.4), "#4ea8ff"), x || cx, floor);
      return Y(floor) + th + 0.07;
    }

    function evaporation(crystals) {
      const top = heated(U(160));
      const d = vessel("dish", U(110), U(46)); d.g.position.set(X(cx), top, 0); W.add(d.g);
      const left = 1 - ease(at(1, span * (crystals ? 0.55 : 0.75)));
      if (left > 0.03) d.fill(0.02, 0.04 + U(40) * left, vis(C_(L.solution, "#bfe3ff")), 0.8, 0.01);
      puffs(W, X(cx), top + U(50), 0.2, tt - 1, "#c3ccd5", 6, 2.2, 1.5);
      const rnd = K.rand(12);
      for (let k = 0; k < 18; k++) {
        const a = rnd() * 6.28, rr = rnd() * U(70), when = span * 0.45 + rnd() * span * 0.45, sz = (crystals ? 0.1 : 0.06) + rnd() * 0.04;
        if (tt < when) continue;
        const c = mesh(geo("cube", () => new T.BoxGeometry(1, 1, 1)), solidMat(seen(C_(L.crystals, "#ffffff")), true));
        c.scale.setScalar(sz * (L.crystals && L.crystals.hydrated ? 1.4 : 1) * ease(clamp01((tt - when) / 0.8))); c.rotation.set(a, a * 2, 0);
        c.position.set(Math.cos(a) * rr, d.floor(rr, 0.02) + sz * 0.4, Math.sin(a) * rr); d.g.add(c);
      }
    }

    function distillation(fractional) {
      const fx = cx - 120, th = U(150), top = heated(th, fx);
      const R = U(70), neck = fractional ? U(170) : U(70);
      const fl = vessel("round", R, U(18), neck); fl.g.position.set(X(fx), top - 0.02, 0); W.add(fl.g);
      const boil = fl.h * 0.3 * (1 - 0.35 * at(1, span));
      const inFlask = L.liquids ? mix(vis(L.liquids[0].colour), vis(L.liquids[L.liquids.length - 1].colour), 0.5) : vis(C_(L.solution, "#bfe3ff"));
      const distillate = vis(L.liquids ? L.liquids[0].colour : C_(L.distillate, "#dff3ff"));
      fl.fill(0.05, boil, inFlask, 0.75);
      bubbles(fl.g, 14, (rnd) => [(rnd() - 0.5) * R * 0.8, 0.12, (rnd() - 0.5) * R * 0.5], boil, tt - 0.8, 4, 0.05);
      if (fractional) {                                   // glass beads in the column
        const rnd = K.rand(21);
        for (let k = 0; k < 26; k++) { const b = K.ball(0.07, M.tubeGlass); b.position.set((rnd() - 0.5) * 0.3, fl.h - neck + 0.2 + rnd() * (neck - 0.5), (rnd() - 0.5) * 0.2); fl.g.add(b); }
      }
      const headY = fl.g.position.y + fl.h, headX = X(fx);
      const th1 = thermometer(1.6); th1.position.set(headX, headY - 0.3, 0); W.add(th1);
      W.add(bung(U(18), 0).translateX(headX).translateY(headY - 0.1));
      // The condenser, sloping down to the receiver; water in its jacket.
      const a = new T.Vector3(headX + 0.6, headY - 0.25, 0), b = new T.Vector3(X(fx + 330), headY - U(130), 0);
      W.add(pipe("arm" + q(headY), [new T.Vector3(headX, headY - 0.25, 0), a], 0.08));
      const len = a.distanceTo(b), mid = a.clone().add(b).multiplyScalar(0.5), dir = b.clone().sub(a).normalize();
      const jacket = new T.Group();
      jacket.add(mesh(geo("cj" + q(len), () => new T.CylinderGeometry(0.34, 0.34, len * 0.78, 28, 1, true)), M.glass));
      jacket.add(mesh(geo("cw" + q(len), () => new T.CylinderGeometry(0.31, 0.31, len * 0.78, 28)), wet("#9fd3f7", 0.28)));
      [-1, 1].forEach((s2) => { const e = ringAt(0.34, (s2 * len * 0.78) / 2, 0.026); jacket.add(e); });
      [-0.34, 0.34].forEach((x2) => { const l = mesh(geo("cl" + q(len), () => new T.CylinderGeometry(0.02, 0.02, len * 0.78, 5)), M.edge); l.position.x = x2; jacket.add(l); });
      const inlet = mesh(geo("cin", () => new T.CylinderGeometry(0.07, 0.07, 0.45, 10)), M.tubeGlass);
      inlet.position.set(0.45, -len * 0.3, 0); inlet.rotation.z = Math.PI / 2; jacket.add(inlet);
      const outlet = inlet.clone(); outlet.position.set(-0.45, len * 0.3, 0); jacket.add(outlet);
      jacket.position.copy(mid); jacket.quaternion.setFromUnitVectors(new T.Vector3(0, -1, 0), dir); W.add(jacket);
      W.add(pipe("ci" + q(len), [a, b], 0.08));
      const st = stand(fx + 190, floor, U(330)); arm(st, 360 - mid.y * PX, mid.x * PX + 640);
      // Vapour along the inner tube, condensing; drops into the receiver.
      for (let k = 0; k < 5; k++) {
        if (tt < 1.4) break;
        const ph = ((tt - 1.4) / 2.2 + k / 5) % 1;
        const p = K.ball(0.05, wet(distillate, 0.9)); p.position.copy(a).lerp(b, ph); W.add(p);
      }
      const rcv = vessel("conical", U(70), U(150), U(22)); put(rcv.g, fx + 345, floor);
      drip(W, b.x, b.y - 0.1, Y(floor) + rcv.h * 0.2, tt, 0.8, distillate, 2);
      rcv.fill(0.04, 0.05 + rcv.h * 0.3 * ease(at(2, span * 0.8)), distillate, 0.7);
    }

    function sepFunnel() {
      const k = U(330) / 3.9, bottom = floor - 170;
      const st = stand(cx - 170, floor, U(600));
      const f = vessel("sepFunnel", k); put(f.g, cx, bottom);
      ringClamp(arm(st, bottom - 2.25 * k * PX, cx), 0.9 * k);
      const tap = mesh(geo("tap", () => new T.CylinderGeometry(0.06, 0.06, 0.5, 10)), M.metal); tap.rotation.z = Math.PI / 2; tap.position.y = 1.12 * k; f.g.add(tap);
      const handle = mesh(geo("tapH", () => new T.BoxGeometry(0.06, 0.3, 0.06)), M.dark);
      handle.position.set(0.3, 1.12 * k, 0); handle.rotation.z = tt > 0.8 ? 0 : Math.PI / 2; f.g.add(handle);
      const drain = ease(at(1, span * 0.6));
      const lowHi = (2.3 - 1.25 * drain) * k, upHi = (3.1 - 1.05 * drain) * k;
      const lower = vis(C_(L.bottom, "#7fbfff")), upper = vis(C_(L.top, "#f6d365"));
      if (lowHi > 1.06 * k) f.fill(0.02, lowHi, lower, 0.75, 0.02);
      f.fill(lowHi, upHi, upper, 0.8, 0.02);
      const bk = vessel("beaker", U(140), U(110)); put(bk.g, cx, floor);
      if (tt > 0.8 && drain < 1) drip(W, X(cx), Y(bottom), Y(floor) + bk.h * 0.3, tt, 0.5, lower, 0.8);
      bk.fill(0.04, 0.05 + bk.h * 0.55 * drain, lower, 0.75);
    }

    function magnetic() {
      const d = vessel("dish", U(170), U(26)); put(d.g, cx, floor);
      const rnd = K.rand(40), pole = [];
      const come = ease(at(0.6, 1.0)), mx = X(cx - 400 + 400 * come), my = Y(floor - 260);
      const mg = magnet(); mg.position.set(mx, my, 0); mg.scale.setScalar(1.1); W.add(mg);
      for (let j = 0; j < 2; j++) pole.push(new T.Vector3(mx + (j ? 0.6 : -0.6), my - 1.15, 0));
      for (let k = 0; k < 44; k++) {
        const a = rnd() * 6.28, rr = rnd() * U(140), iron = k % 2 === 0, jit = rnd();
        const home = new T.Vector3(X(cx) + Math.cos(a) * rr, Y(floor) + d.floor(rr, 0.05) + 0.03, Math.sin(a) * rr);
        let p = home;
        if (iron) {
          const when = 1.8 + (k / 44) * 1.2, f = ease(clamp01((tt - when) / 0.8));
          const P0 = pole[k % 4 < 2 ? 0 : 1].clone().add(new T.Vector3((jit - 0.5) * 0.35, -jit * 0.2, (rnd() - 0.5) * 0.3));
          p = home.clone().lerp(P0, f);
        } else rnd();
        const b = mesh(geo("grain", () => new T.DodecahedronGeometry(1, 0)), solidMat(seen(iron ? nth(L.magnetic, k, "#4b5563") : nth(L.others, k, "#e6c200")), iron));
        b.scale.setScalar(0.06); b.position.copy(p); W.add(b);
      }
    }

    function chromatography() {
      const v = vessel("beaker", U(200), U(360)); put(v.g, cx, floor);
      v.fill(0.04, U(45), vis(C_(L.solvent, "#dff3ff")), 0.6);
      v.g.add(rod(new T.Vector3(-U(130), v.h + 0.08, 0), new T.Vector3(U(130), v.h + 0.08, 0), 0.04, M.tubeGlass));
      const ph = U(340), pw = U(80), y0 = v.h + 0.06 - ph;
      const sheet = mesh(geo("chromP", () => new T.PlaneGeometry(pw, ph)), M.sheet); sheet.position.set(0, y0 + ph / 2, 0); v.g.add(sheet);
      const line = mesh(geo("chromL", () => new T.PlaneGeometry(pw * 0.9, 0.02)), M.pencil); line.position.set(0, Y(floor - 110) - Y(floor), 0.005); v.g.add(line);
      const front = ease(at(0.6, span * 0.8)), wetH = 0.2 + (ph - 0.4) * front;
      const w = mesh(geo("chromW" + q(wetH), () => new T.PlaneGeometry(pw, wetH)), wet("#b8dcf5", 0.55)); w.position.set(0, y0 + wetH / 2, 0.004); v.g.add(w);
      const base = line.position.y;
      const dyes = (L.dyes || [{ colour: "#e8261b" }, { colour: "#1d4ed8" }, { colour: "#e6c200" }]).map((d, j, all) => [d.colour, 0.3 + (0.6 * (j + 0.5)) / all.length]);
      dyes.forEach(([c, f]) => {
        const sp = mesh(geo("spot", () => new T.CircleGeometry(0.1, 20)), fire(c, 0.85));
        sp.position.set(0, base + (U(280) * f) * front, 0.008); v.g.add(sp);
      });
    }

    function sublimation() {
      const top = heated(U(150));
      const d = vessel("dish", U(110), U(46)); d.g.position.set(X(cx), top, 0); W.add(d.g);
      const fn = vessel("funnel", U(100), U(150), U(10), U(70)); fn.g.rotation.z = Math.PI; fn.g.position.set(X(cx), top + U(46) + U(150) + U(70), 0); W.add(fn.g);
      const wool = new T.Group(); const rw = K.rand(2);
      for (let k = 0; k < 6; k++) { const b = K.ball(0.09, M.wool); b.position.set((rw() - 0.5) * 0.15, rw() * 0.2, (rw() - 0.5) * 0.15); wool.add(b); }
      wool.position.y = -0.15; fn.g.add(wool);
      const rnd = K.rand(14);
      const gone = at(1, span * 0.7);
      for (let k = 0; k < 30; k++) {
        const a = rnd() * 6.28, rr = rnd() * U(80), iodine = k % 2 === 1;
        if (iodine && rnd() < gone) continue;
        const p = mesh(geo("grain", () => new T.DodecahedronGeometry(1, 0)), solidMat(seen(iodine ? C_(L.sublimer, "#5b21b6") : nth(L.others, k, "#b08a5a"))));
        p.scale.setScalar(0.06); p.position.set(Math.cos(a) * rr, d.floor(rr, 0.05), Math.sin(a) * rr); d.g.add(p);
      }
      const sc = C_(L.sublimer, "#4c1d95");
      puffs(W, X(cx), top + 0.3, 0.1, tt - 1, clearish(sc) ? "#cbd5e1" : mix(sc, "#ffffff", 0.45), 5, 1.6, 0.9);
      // Crystals forming on the cold funnel.
      const rc = K.rand(66);
      for (let k = 0; k < 40; k++) {
        const a = rc() * 6.28, y = rc(), when = 1.5 + rc() * span * 0.7;
        if (tt < when) continue;
        const yy = U(70) + U(150) * (0.15 + 0.8 * y), rr = U(10) + (U(100) - U(10)) * ((yy - U(70)) / U(150)) * 0.96;
        const c = mesh(geo("cube", () => new T.BoxGeometry(1, 1, 1)), solidMat(seen(sc), true));
        c.scale.setScalar(0.05 * ease(clamp01((tt - when) / 0.5))); c.position.set(Math.cos(a) * rr, yy, Math.sin(a) * rr); fn.g.add(c);
      }
    }
  };
})();
