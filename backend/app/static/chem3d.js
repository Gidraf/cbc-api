/* Chemistry in 3D, over the whiteboard: atoms with their shells and orbiting
 * electrons, electrons travelling from a metal to a non-metal (ionic
 * bonding) and the ions settling into a crystal lattice, and molecules in
 * their real shapes with their shared pairs (covalent bonding).
 *
 * Like the whiteboard and the teacher, everything is a function of time:
 * the server photographs the page frame by frame with window.__seek(t), so
 * each frame is computed from the scene and its moment alone — no physics,
 * no state carried between frames. The board writes the words; this canvas
 * (transparent where empty) draws the atoms over it. Without WebGL it does
 * nothing, and the board draws its flat versions instead.
 *
 * Expects THREE (r128), window.WB_DATA, window.__starts / __total from the
 * whiteboard engine, and calls from it through window.__onChem3d(t).
 */
(function () {
  "use strict";
  const data = window.WB_DATA || {};
  const scenes = data.scenes || [];
  // The lab bench and the separations are drawn by lab3d.js, through this canvas.
  const KINDS = { chem_atom: 1, chem_ionic: 1, chem_covalent: 1, chem_lab: 1, chem_separation: 1 };
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
  canvas.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;display:none;z-index:2";   // the atoms in front of the marker hand
  root.appendChild(canvas);
  renderer.setClearColor(0x000000, 0);

  const scene3 = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 16 / 9, 0.1, 200);
  scene3.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(6, 10, 12);
  scene3.add(key);
  const rim = new THREE.DirectionalLight(0x9cc8ff, 0.35);
  rim.position.set(-8, -4, 6);
  scene3.add(rim);
  const world = new THREE.Group();
  scene3.add(world);

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
  const sharedMat = new THREE.MeshPhongMaterial({ color: 0x16a34a, emissive: 0x15803d, emissiveIntensity: 0.6, shininess: 120 });
  function ball(r, material) { const m = new THREE.Mesh(sphereGeo, material); m.scale.setScalar(r); return m; }
  // Geometries and materials made once and reused: every frame rebuilds the
  // scene graph, and a render is hundreds of frames.
  const ringGeos = {}, ringMats = {}, ghostMats = [];
  function ring(r, colour, opacity) {
    const rk = r.toFixed(2), op = Math.round((opacity == null ? 0.7 : opacity) * 10) / 10, mk = `${colour || 0x6b7280}:${op}`;
    if (!ringGeos[rk]) ringGeos[rk] = new THREE.TorusGeometry(r, 0.025, 8, 96);
    if (!ringMats[mk]) ringMats[mk] = new THREE.MeshBasicMaterial({ color: colour || 0x6b7280, transparent: true, opacity: op });
    return new THREE.Mesh(ringGeos[rk], ringMats[mk]);
  }
  function ghostMat(tr) {
    if (!ghostMats[tr]) ghostMats[tr] = new THREE.MeshBasicMaterial({ color: 0xf97316, transparent: true, opacity: 0.5 - tr * 0.07 });
    return ghostMats[tr];
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
  function rand(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

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
    const key = p + ":" + n;
    if (nuclei[key]) return nuclei[key];
    const N = Math.max(1, p + n), rnd = rand(p * 131 + n * 7 + 1), pts = [];
    if (N === 1) return (nuclei[key] = [{ v: new THREE.Vector3(), proton: p > 0 }]);
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
    return (nuclei[key] = pts.map((v, i) => ({ v, proton: proton.has(i) })));
  }
  function buildAtom(a, opts) {
    // opts: built 0..1 (electrons arrived so far), t (seconds), spin, shells
    // (to draw an ion), gained (the last n outer electrons came from another
    // atom: drawn orange), bare (no outer electrons: a diagram places them).
    const g = new THREE.Group();
    for (const nu of nucleusLayout(a.protons || 1, a.neutrons || 0)) {
      const b = ball(NUC_R, nu.proton ? mat("#dc2626") : mat("#a3a9b3"));
      b.position.copy(nu.v); g.add(b);
    }
    const shells = (opts.shells || a.shells || []).slice();
    const total = shells.reduce((x, y) => x + y, 0);
    const built = opts.built == null ? 1 : opts.built;
    let count = 0;
    shells.forEach((n, k) => {
      const r = SHELL_R(k), last = k === shells.length - 1;
      const shown = clamp01(built * total - count + 1);
      if (shown > 0) g.add(ring(r, 0x6b7280, 0.3 + 0.45 * shown));
      const angs = slotAngles(n, k, r), turn = sway(opts.t || 0, k) * (opts.spin == null ? 1 : opts.spin);
      for (let e = 0; e < n; e++) {
        count++;
        if (last && opts.bare) continue;
        const arrived = clamp01(built * total - (count - 1));
        if (arrived <= 0) continue;
        const foreign = last && e >= n - (opts.gained || 0);
        const el = ball(0.12 * (0.4 + 0.6 * ease(arrived)), foreign ? movingMat : electronMat);
        el.position.set(Math.cos(angs[e] + turn) * r, Math.sin(angs[e] + turn) * r, 0.02);
        g.add(el);
      }
    });
    return g;
  }
  function outerPoint(a, slot, of, t, centre, scaleK) {
    // Where electron `slot` of `of` on the outer shell is, in world space.
    const k = (a.shells || [1]).length - 1, r = SHELL_R(k);
    const ang = slotAngles(of, k, r)[Math.max(0, Math.min(of - 1, slot))] + sway(t, k);
    return new THREE.Vector3(Math.cos(ang) * r, Math.sin(ang) * r, 0).multiplyScalar(scaleK || 1).add(centre);
  }
  // The symbol on the nucleus, dark with a white edge, so it reads over red and grey.
  const tags = {};
  function tag(text) {
    if (!tags[text]) {
      const c = document.createElement("canvas"), x = c.getContext("2d");
      c.width = 256; c.height = 128;
      x.font = "bold 76px 'Patrick Hand', 'Comic Sans MS', sans-serif";
      x.textAlign = "center"; x.textBaseline = "middle";
      x.lineWidth = 14; x.strokeStyle = "rgba(255,255,255,0.92)"; x.lineJoin = "round";
      x.strokeText(text, 128, 66); x.fillStyle = "#111827"; x.fillText(text, 128, 66);
      tags[text] = new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false });
    }
    const sp = new THREE.Sprite(tags[text]);
    sp.scale.set(1.0, 0.5, 1);
    return sp;
  }

  // ── the scenes ──
  function atomScene(s, i, t, dur) {
    const prev = s.short && s.slot === 1 ? scenes[i - 1] : null;
    const both = [prev, s].filter(Boolean);
    const built = clamp01(t / Math.max(1, dur * 0.6));
    both.forEach((a, j) => {
      const isNow = a === s;
      const g = buildAtom(a, { built: isNow ? built : 1, t: t + j * 3 });
      // One atom: left of centre (its facts are written on the right). A pair: side by side.
      const x = !s.short ? -2.9 : both.length > 1 ? (j === 0 ? -4.2 : 4.2) : -4.2;
      g.position.set(x, s.short ? 0.3 : 0, 0);
      g.scale.setScalar((s.short ? 0.85 : 1.05) * Math.min(1, 2.95 / SHELL_R(a.shells.length - 1)));
      g.rotation.set(0.12, Math.sin(t * 0.5 + j) * 0.3, 0);         // a slow turn: it is a ball, not a drawing
      world.add(g);
      const sym = tag(a.symbol);
      sym.position.copy(g.position).add(new THREE.Vector3(0, 0, 1.2));
      world.add(sym);
    });
    camera.position.set(0, 0.5, 15);
    camera.lookAt(s.short ? 0 : -1.2, 0, 0);
  }

  function ionicScene(s, i, t, dur) {
    const nm = Math.min(3, s.counts[s.metal.symbol] || 1), nn = Math.min(3, s.counts[s.nonmetal.symbol] || 1);
    const moves = s.moves || [];
    const tMove0 = dur * 0.18, perMove = Math.min(1.6, (dur * 0.42) / Math.max(1, moves.length));
    const tMoved = tMove0 + perMove * moves.length;
    const tLattice = Math.max(tMoved + 1.2, dur * 0.72);
    // Several atoms of a kind stand in a column, apart: sized so the column fits.
    const Rm = SHELL_R(s.metal.shells.length - 1), Rn = SHELL_R(s.nonmetal.shells.length - 1);
    const k = Math.min(0.8, 7.4 / (nm * 2 * Rm * 1.08), 7.4 / (nn * 2 * Rn * 1.08));
    const mPos = Array.from({ length: nm }, (_, j) => new THREE.Vector3(-4.2, (j - (nm - 1) / 2) * 2 * Rm * 1.08 * k, 0));
    const nPos = Array.from({ length: nn }, (_, j) => new THREE.Vector3(4.2, (j - (nn - 1) / 2) * 2 * Rn * 1.08 * k, 0));
    const qm = Math.abs(s.metal.ion_charge || 1), qn = Math.abs(s.nonmetal.ion_charge || 1);
    const toLattice = clamp01((t - tLattice) / 1.8);
    // How many electrons each atom has given or taken so far.
    const given = mPos.map(() => 0), taken = nPos.map(() => 0);
    const flying = [];
    moves.forEach((mv, n) => {
      const a = tMove0 + n * perMove, f = clamp01((t - a) / (perMove * 0.85));
      const im = Math.min(mv.from, nm - 1), jn = Math.min(mv.to, nn - 1);
      if (f >= 1) { given[im]++; taken[jn]++; }
      else if (f > 0) flying.push({ im, jn, f, n, slotM: given[im], slotN: taken[jn] });
    });
    if (toLattice < 1) {
      mPos.forEach((p, j) => {
        const shells = s.metal.shells.slice();
        shells[shells.length - 1] -= given[j] + flying.filter((x) => x.im === j).length;
        const g = buildAtom(s.metal, { built: 1, t, shells: shells[shells.length - 1] > 0 ? shells : shells.slice(0, -1) });
        const shrink = given[j] >= qm ? 0.88 : 1;
        g.position.copy(p); g.scale.setScalar(k * shrink * (1 - toLattice));
        world.add(g);
        const l = given[j] >= qm ? label(`${s.metal.symbol}${sup(qm)}⁺`, "#c2410c", 64) : tag(s.metal.symbol);
        const side = nm > 1 && given[j] >= qm;   // stacked atoms: the ion's name beside it, not on the one above
        l.position.copy(p).add(new THREE.Vector3(side ? -2.9 * k : 0, given[j] >= qm && !side ? 2.6 * k : 0, 1.3)); if (toLattice < 0.5) world.add(l);
      });
      nPos.forEach((p, j) => {
        const shells = s.nonmetal.shells.slice();
        shells[shells.length - 1] += taken[j];
        const g = buildAtom(s.nonmetal, { built: 1, t: t + 2, shells, gained: taken[j] });
        g.position.copy(p); g.scale.setScalar(k * (1 - toLattice));
        world.add(g);
        const full = taken[j] >= qn;
        const l = full ? label(`${s.nonmetal.symbol}${sup(qn)}⁻`, "#1d4ed8", 64) : tag(s.nonmetal.symbol);
        const side = nn > 1 && full;
        l.position.copy(p).add(new THREE.Vector3(side ? 3.6 * k : 0, full && !side ? 3.0 * k : 0, 1.3)); if (toLattice < 0.5) world.add(l);
      });
      // The electrons in flight: an arc from the metal's outer shell to the non-metal's.
      flying.forEach((fl) => {
        const from = outerPoint(s.metal, s.metal.shells[s.metal.shells.length - 1] - 1 - fl.slotM, s.metal.shells[s.metal.shells.length - 1], t, mPos[fl.im], k);
        const to = outerPoint(s.nonmetal, s.nonmetal.shells[s.nonmetal.shells.length - 1] + fl.slotN, 8, t + 2, nPos[fl.jn], k);
        const mid = from.clone().add(to).multiplyScalar(0.5).add(new THREE.Vector3(0, 2.2, 1.5));
        const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
        const e = ease(fl.f);
        const p = curve.getPoint(e);
        const el = ball(0.17, movingMat); el.position.copy(p); world.add(el);
        for (let tr = 1; tr <= 6; tr++) {                // a fading trail behind it
          const q = curve.getPoint(Math.max(0, e - tr * 0.035));
          const ghost = ball(0.12 * (1 - tr / 8), ghostMat(tr));
          ghost.position.copy(q); world.add(ghost);
        }
      });
    }
    if (toLattice > 0) {
      // The ions settle into a lattice: alternating ions in a cube (1:1, like
      // NaCl and MgO), or the formula's ions around the metal ion otherwise.
      const grp = new THREE.Group();
      const mR = 0.55, nR = 0.85;
      if (nm === nn) {
        for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
          const metal = (x + y + z + 3) % 2 === 0;
          const b = ball(metal ? mR : nR, mat(metal ? s.metal.colour : s.nonmetal.colour, { transparent: true, opacity: 0.95 }));
          b.position.set(x * 1.6, y * 1.6, z * 1.6);
          grp.add(b);
        }
      } else {
        // The formula's ions: the scarcer kind in the middle, the other round them.
        const fewMetal = nm <= nn, few = fewMetal ? nm : nn, more = fewMetal ? nn : nm;
        const fewR = fewMetal ? mR : nR, moreR = fewMetal ? nR : mR;
        const fewC = fewMetal ? s.metal.colour : s.nonmetal.colour, moreC = fewMetal ? s.nonmetal.colour : s.metal.colour;
        for (let j = 0; j < few; j++) {
          const b = ball(fewR * 1.05, mat(fewC));
          b.position.set(few > 1 ? (j - (few - 1) / 2) * 1.5 : 0, 0, 0); grp.add(b);
        }
        for (let j = 0; j < more; j++) {
          const ang = (j / more) * Math.PI * 2 + 0.3;
          const b = ball(moreR, mat(moreC));
          b.position.set(Math.cos(ang) * 2.3, Math.sin(ang) * 1.6, Math.sin(ang + 1) * 1.2);
          grp.add(b);
        }
      }
      grp.scale.setScalar(ease(toLattice));
      grp.rotation.set(0.5 + t * 0.15, t * 0.35, 0);
      world.add(grp);
    }
    camera.position.set(Math.sin(t * 0.2) * 1.5, 1 + Math.sin(t * 0.15) * 0.5, 17);
    camera.lookAt(0, 0.3, 0);
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
  function covalentScene(s, i, t, dur) {
    // First the dot-and-cross diagram as it is drawn in the exam — the outer
    // shells overlapping, each shared pair (green) in the overlap, the lone
    // pairs at their places, the outer atoms' electrons orange — then the
    // molecule in its real shape, space-filling, turning.
    const [A, B] = s.atoms, centre = A.symbol === s.centre ? A : B, outer = centre === A ? B : A;
    const same = A.symbol === B.symbol;
    const n = same ? 1 : Math.min(4, s.counts[outer.symbol] || 1);
    const order = same ? (centre.valency || 1) : (outer.valency || 1);
    const come = ease(clamp01(t / Math.max(1, dur * 0.18)));
    const share = ease(clamp01((t - dur * 0.2) / Math.max(1, dur * 0.3)));
    const toModel = ease(clamp01((t - dur * 0.64) / 1.4));
    const V = (x, y) => new THREE.Vector3(x, y, 0);
    const dirOf = (si) => V(Math.cos(SLOTS[si]), Math.sin(SLOTS[si]));
    if (toModel < 1) {
      const flat = new THREE.Group();
      const Rc = SHELL_R(centre.shells.length - 1), Ro = SHELL_R(outer.shells.length - 1);
      const overlap = Math.min(Rc, Ro) * 0.5, d = Rc + Ro - overlap;
      const bonded = same ? [1] : { 1: [1], 2: [3, 1], 3: [3, 1, 2], 4: [0, 1, 2, 3] }[n];
      const cPos = same ? V(-d / 2, 0) : V(0, 0);
      const lone = (pos, R, count, slots, material) => {
        for (let e = 0; e < count; e++) {
          const si = slots[Math.floor(e / 2) % slots.length], paired = count - Math.floor(e / 2) * 2 >= 2;
          const ang = SLOTS[si] + (paired ? (e % 2 ? -1 : 1) * (0.17 / R) : 0);
          const el = ball(0.12, material); el.position.copy(pos).add(V(Math.cos(ang) * R, Math.sin(ang) * R)); flat.add(el);
        }
      };
      const loneSlots = (facing, pairs) => {
        const far = (facing + 2) % 4, perp = [(facing + 1) % 4, (facing + 3) % 4];
        return pairs === 1 ? [far, ...perp] : [...perp, far];
      };
      const atom = (a, pos) => {
        const g = buildAtom(a, { built: 1, t: 0, spin: 0, bare: true }); g.position.copy(pos); flat.add(g);
        const tg = tag(a.symbol); tg.position.copy(pos).add(V(0, 0)).setZ(1.2); flat.add(tg);
      };
      atom(centre, cPos);
      const cOuter = centre.shells[centre.shells.length - 1], cLone = Math.max(0, cOuter - bonded.length * order);
      const cSlots = same ? loneSlots(1, cLone / 2) : [0, 1, 2, 3].filter((k) => !bonded.includes(k));
      lone(cPos, Rc, cLone, cSlots.length ? cSlots : [0], electronMat);
      bonded.forEach((si, j) => {
        const dir = dirOf(si), perp = V(-dir.y, dir.x);
        const oPos = same ? V(d / 2 + (1 - come) * 3, 0) : dir.clone().multiplyScalar(d + (1 - come) * 4);
        atom(outer, oPos);
        const oOuter = outer.shells[outer.shells.length - 1], oLone = Math.max(0, oOuter - order), facing = (si + 2) % 4;
        lone(oPos, Ro, oLone, loneSlots(facing, oLone / 2), movingMat);
        // Each shared pair: one electron from each atom, meeting in the overlap.
        const mid = cPos.clone().add(dir.clone().multiplyScalar(Rc - overlap / 2));
        for (let p = 0; p < order; p++) {
          const off = perp.clone().multiplyScalar((p - (order - 1) / 2) * 0.36);
          const tilt = (p - (order - 1) / 2) * (0.36 / Rc);
          const fromC = cPos.clone().add(V(Math.cos(SLOTS[si] + tilt) * Rc, Math.sin(SLOTS[si] + tilt) * Rc));
          const fromO = oPos.clone().add(V(Math.cos(SLOTS[facing] - tilt) * Ro, Math.sin(SLOTS[facing] - tilt) * Ro));
          const toC = mid.clone().add(off).add(dir.clone().multiplyScalar(-0.13)), toO = mid.clone().add(off).add(dir.clone().multiplyScalar(0.13));
          const eC = ball(0.12, share > 0.5 ? sharedMat : electronMat); eC.position.copy(fromC.lerp(toC, share)); flat.add(eC);
          const eO = ball(0.12, share > 0.5 ? sharedMat : movingMat); eO.position.copy(fromO.lerp(toO, share)); flat.add(eO);
        }
      });
      const extX = same ? d / 2 + Ro : d + Ro, extY = bonded.some((k) => k === 0 || k === 2) ? d + Ro : Math.max(Rc, Ro);
      flat.scale.setScalar(Math.min(1, 6.2 / (2 * extY), 12 / (2 * extX)) * (1 - toModel));
      flat.position.set(0, 0.35, 0);
      world.add(flat);
    }
    if (toModel > 0) {
      // The real shape: CH4 a tetrahedron, NH3 a pyramid, H2O bent, CO2 straight.
      const mol = new THREE.Group();
      const rc = VDW[centre.symbol] || 0.9, ro = VDW[outer.symbol] || 0.9;
      const tint = (a) => mat(a.symbol === "H" ? "#f1f1f1" : a.colour || "#999999");
      if (same) {
        const L = rc * 1.5 * (1 - 0.07 * (order - 1));
        [-1, 1].forEach((sg) => { const b = ball(rc, tint(centre)); b.position.x = (sg * L) / 2; mol.add(b); });
      } else {
        mol.add(ball(rc, tint(centre)));
        let dirs = SHAPES[n] || SHAPES[1];
        if (n === 2) dirs = centre.shells[centre.shells.length - 1] - 2 * order > 0 ? SHAPES[2].bent : SHAPES[2].linear;
        dirs.forEach((dv) => { const b = ball(ro, tint(outer)); b.position.copy(new THREE.Vector3(...dv).normalize().multiplyScalar((rc + ro) * 0.8 * (1 - 0.05 * (order - 1)))); mol.add(b); });
      }
      mol.scale.setScalar(1.7 * toModel);
      mol.rotation.set(0.35, t * 0.6, 0);
      mol.position.set(0, 0.35, 0);
      world.add(mol);
    }
    camera.position.set(0, 0.6, 16);
    camera.lookAt(0, 0.3, 0);
  }

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
    if (s.scene === "chem_atom") atomScene(s, i, t, dur);
    else if (s.scene === "chem_ionic") ionicScene(s, i, t, dur);
    else if (s.scene === "chem_covalent") covalentScene(s, i, t, dur);
    else if (window.__lab3d && window.__lab3d[s.scene]) window.__lab3d[s.scene](s, t, dur);
    renderer.render(scene3, camera);
  }
  window.__onChem3d = frame;
  window.__chem3dKit = { THREE, world, camera, data, mat, ball, label, rand };
})();
