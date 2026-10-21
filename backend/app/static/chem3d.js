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
  const KINDS = { chem_atom: 1, chem_ionic: 1, chem_covalent: 1 };
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

  // ── one atom: a nucleus of protons and neutrons, its shells, its electrons ──
  const SHELL_R = (k) => 1.1 + k * 0.85;
  const TILTS = [[0.2, 0.1], [-0.35, 0.25], [0.5, -0.3], [-0.15, 0.6]];
  function buildAtom(a, opts) {
    // opts: {built: 0..1 (how far the electrons have arrived), t: seconds, lose: n outer electrons gone, gain: n added, spin}
    const g = new THREE.Group();
    const nucleons = Math.min(40, (a.protons || 1) + (a.neutrons || 0));
    const rnd = rand((a.Z || 1) * 7919);
    const nr = 0.22 + Math.cbrt(nucleons) * 0.12;
    for (let i = 0; i < nucleons; i++) {
      // Fibonacci points in a small ball: a packed nucleus, the same every frame.
      const y = 1 - (i / Math.max(1, nucleons - 1)) * 2, rad = Math.sqrt(1 - y * y), th = i * 2.399963;
      const d = nr * Math.cbrt((i + 0.5) / nucleons) * 1.2;
      const p = ball(0.13, i < (a.protons || 1) ? mat("#dc2626") : mat("#9ca3af"));
      p.position.set(Math.cos(th) * rad * d, y * d, Math.sin(th) * rad * d);
      g.add(p);
    }
    const shells = (opts.shells || a.shells || []).slice();
    const total = shells.reduce((x, y) => x + y, 0);
    let count = 0;
    shells.forEach((n, k) => {
      const r = SHELL_R(k);
      const tilt = TILTS[k % 4];
      const holder = new THREE.Group();
      holder.rotation.set(Math.PI / 2 + tilt[0], tilt[1], 0);
      const shellShown = clamp01(opts.built * total - count + 1);
      if (shellShown > 0) holder.add(ring(r, k === shells.length - 1 && opts.outerColour ? opts.outerColour : 0x6b7280, 0.25 + 0.5 * shellShown));
      const speed = 0.9 / (k + 1);
      for (let e = 0; e < n; e++) {
        count++;
        const arrived = clamp01(opts.built * total - (count - 1));
        if (arrived <= 0) continue;
        const ang = (e / n) * Math.PI * 2 + (opts.t || 0) * speed * (opts.spin == null ? 1 : opts.spin);
        const el = ball(0.11 * (0.4 + 0.6 * ease(arrived)), electronMat);
        el.position.set(Math.cos(ang) * r, Math.sin(ang) * r, 0);
        holder.add(el);
      }
      g.add(holder);
    });
    return g;
  }
  function outerPoint(a, slot, of, t, centre, scaleK) {
    // Where electron `slot` of `of` on the outer shell is, in world space.
    const k = (a.shells || [1]).length - 1, r = SHELL_R(k), tilt = TILTS[k % 4];
    const ang = (slot / Math.max(1, of)) * Math.PI * 2 + t * (0.9 / (k + 1));
    const v = new THREE.Vector3(Math.cos(ang) * r, Math.sin(ang) * r, 0);
    v.applyEuler(new THREE.Euler(Math.PI / 2 + tilt[0], tilt[1], 0));
    return v.multiplyScalar(scaleK || 1).add(centre);
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
      const x = !s.short ? -2.6 : both.length > 1 ? (j === 0 ? -4.2 : 4.2) : -4.2;
      g.position.set(x, s.short ? 0.2 : 0, 0);
      g.scale.setScalar(s.short ? 0.85 : 1.05);
      world.add(g);
      const sym = label(a.symbol, "#ffffff", 72);
      sym.position.copy(g.position).add(new THREE.Vector3(0, 0, 1.2));
      sym.scale.set(1.1, 0.55, 1);
      world.add(sym);
    });
    camera.position.set(Math.sin(t * 0.25) * 2.5, 1.2 + Math.sin(t * 0.18) * 0.6, 15);
    camera.lookAt(s.short ? 0 : -1.2, 0, 0);
  }

  function ionicScene(s, i, t, dur) {
    const nm = Math.min(3, s.counts[s.metal.symbol] || 1), nn = Math.min(3, s.counts[s.nonmetal.symbol] || 1);
    const moves = s.moves || [];
    const tMove0 = dur * 0.18, perMove = Math.min(1.6, (dur * 0.42) / Math.max(1, moves.length));
    const tMoved = tMove0 + perMove * moves.length;
    const tLattice = Math.max(tMoved + 1.2, dur * 0.72);
    const k = Math.max(nm, nn) > 1 ? 0.62 : 0.8;
    const mPos = Array.from({ length: nm }, (_, j) => new THREE.Vector3(-4.2, (j - (nm - 1) / 2) * 3.3 * k, 0));
    const nPos = Array.from({ length: nn }, (_, j) => new THREE.Vector3(4.2, (j - (nn - 1) / 2) * 3.3 * k, 0));
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
        const l = label(given[j] >= qm ? `${s.metal.symbol}${sup(qm)}⁺` : s.metal.symbol, given[j] >= qm ? "#c2410c" : "#ffffff", 64);
        const side = nm > 1 && given[j] >= qm;   // stacked atoms: the ion's name beside it, not on the one above
        l.position.copy(p).add(new THREE.Vector3(side ? -2.9 * k : 0, given[j] >= qm && !side ? 2.6 * k : 0, 1.3)); if (toLattice < 0.5) world.add(l);
      });
      nPos.forEach((p, j) => {
        const shells = s.nonmetal.shells.slice();
        shells[shells.length - 1] += taken[j];
        const g = buildAtom(s.nonmetal, { built: 1, t: t + 2, shells });
        g.position.copy(p); g.scale.setScalar(k * (1 - toLattice));
        world.add(g);
        const full = taken[j] >= qn;
        const l = label(full ? `${s.nonmetal.symbol}${sup(qn)}⁻` : s.nonmetal.symbol, full ? "#1d4ed8" : "#ffffff", 64);
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
  function covalentScene(s, i, t, dur) {
    const [A, B] = s.atoms, centre = A.symbol === s.centre ? A : B, outer = centre === A ? B : A;
    const same = A.symbol === B.symbol;
    const n = same ? 1 : Math.min(4, s.counts[outer.symbol] || 1);
    let dirs = SHAPES[n] || SHAPES[1];
    if (n === 2) dirs = centre.symbol === "O" || centre.symbol === "S" ? SHAPES[2].bent : SHAPES[2].linear;
    const order = same ? (centre.valency || 1) : (outer.valency || 1);
    const come = ease(clamp01(t / Math.max(1, dur * 0.25)));
    const pairsShown = clamp01((t - dur * 0.3) / Math.max(1, dur * 0.4));
    const d = SHELL_R(centre.shells.length - 1) * 0.85 + SHELL_R(outer.shells.length - 1) * 0.55;
    const grp = new THREE.Group();
    const cAtom = buildAtom(centre, { built: 1, t, spin: 0.4 });
    if (same) cAtom.position.set(-d / 2 - (1 - come) * 3, 0, 0);
    grp.add(cAtom);
    const cl = label(centre.symbol, "#ffffff", 72); cl.position.copy(cAtom.position).add(new THREE.Vector3(0, 0, 1.3)); cl.scale.set(1.1, 0.55, 1); grp.add(cl);
    dirs.forEach((dv, j) => {
      const dir = new THREE.Vector3(...dv).normalize();
      const at = same ? new THREE.Vector3(d / 2 + (1 - come) * 3, 0, 0) : dir.clone().multiplyScalar(d + (1 - come) * 4);
      const o = buildAtom(outer, { built: 1, t: t + j, spin: 0.4 });
      o.position.copy(at); grp.add(o);
      const ol = label(outer.symbol, outer.symbol === "H" ? "#1b1f2a" : "#ffffff", 72); ol.position.copy(at).add(new THREE.Vector3(0, 0, 1.3)); ol.scale.set(1.1, 0.55, 1); grp.add(ol);
      // The shared pairs, between the two nuclei: green, gently breathing.
      const from = same ? cAtom.position.clone() : new THREE.Vector3(0, 0, 0);
      const mid = from.clone().add(at).multiplyScalar(0.5);
      const side = new THREE.Vector3().crossVectors(at.clone().sub(from).normalize(), new THREE.Vector3(0, 0, 1)).normalize();
      if (side.lengthSq() < 0.01) side.set(0, 1, 0);
      for (let p = 0; p < order; p++) {
        const show = clamp01(pairsShown * order * (same ? 1 : n) - (j * order + p));
        if (show <= 0) continue;
        const off = side.clone().multiplyScalar((p - (order - 1) / 2) * 0.42);
        const wob = Math.sin(t * 2 + p + j) * 0.06;
        [-0.13, 0.13].forEach((dz) => {
          const e = ball(0.13 * ease(show), sharedMat);
          e.position.copy(mid).add(off).add(new THREE.Vector3(0, wob, dz)); grp.add(e);
        });
      }
    });
    grp.scale.setScalar(same ? 0.95 : n > 2 ? 1.05 : 1.0);
    grp.rotation.set(0.25, t * 0.3, 0);
    grp.position.set(0, 0.4, 0);
    world.add(grp);
    camera.position.set(0, 1.2, 16);
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
    else covalentScene(s, i, t, dur);
    renderer.render(scene3, camera);
  }
  window.__onChem3d = frame;
})();
