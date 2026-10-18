/* The teacher: a three.js presenter beside the whiteboard in the social cut.
 *
 * She (or he) reads the question in a studio panel, thinks through the
 * countdown, shrinks to a corner while the board works the solution, cheers
 * the answer, then comes back to ask "Did you get it right?".
 *
 * Everything is a function of time, like the hand and the captions: the
 * server photographs the page frame by frame with window.__seek(t), and a
 * frame must look the same however it is reached. The mouth follows the
 * voice from loudness envelopes the server measured from the very audio the
 * MP4 carries (WB_DATA.social.teacher.mouth, one list per scene).
 *
 * The figure is built from primitives — no model files, nothing to license —
 * and drawn with toon shading, cheap enough for a server with no GPU.
 * Expects THREE (r128), WB_DATA.social.teacher = {gender, mouth, fps}, and
 * window.__onTime(t) being called by the whiteboard engine.
 */
(function () {
  "use strict";
  const data = window.WB_DATA || {};
  const cfg = (data.social || {}).teacher;
  const root = document.getElementById("social");
  if (!cfg || !root || typeof THREE === "undefined") return;
  const scenes = data.scenes || [];
  const female = cfg.gender !== "male";
  const FPS = cfg.fps || 30;
  const W = 480, H = 580;

  // ── what each scene asks of the teacher ──
  const TEACHER_SCENES = { title: 1, countdown: 1, check: 1, outro: 1 };
  const MOOD = { title: "tense", countdown: "tense", answer: "lively", check: "lively", outro: "lively" };
  const POSE = { title: "present", countdown: "think", answer: "present", check: "point", outro: "wave" };

  // ── the stage ──
  const panel = document.createElement("div");
  panel.id = "teacher";
  panel.style.cssText = `position:absolute;left:40px;top:1000px;width:${W}px;height:${H}px;border-radius:30px;overflow:hidden;` +
    "transform-origin:0 100%;box-shadow:0 18px 40px rgba(0,0,0,.35);" +
    "background:radial-gradient(90% 70% at 50% 30%,rgba(255,255,255,.22),rgba(255,255,255,.06) 60%,rgba(0,0,0,.15));" +
    "border:4px solid rgba(255,255,255,.25)";
  root.appendChild(panel);
  const vignette = document.createElement("div");
  vignette.style.cssText = "position:absolute;inset:0;pointer-events:none;opacity:0;" +
    "background:radial-gradient(75% 60% at 50% 45%,transparent 45%,rgba(40,0,0,.9) 100%)";
  root.appendChild(vignette);
  const glow = document.createElement("div");
  glow.style.cssText = "position:absolute;inset:0;pointer-events:none;opacity:0;mix-blend-mode:screen;" +
    "background:radial-gradient(80% 50% at 50% 40%,rgba(255,230,120,.55),transparent 70%)";
  root.appendChild(glow);
  const confetti = document.createElement("canvas");
  confetti.width = 1080; confetti.height = 1920;
  confetti.style.cssText = "position:absolute;inset:0;pointer-events:none";
  root.appendChild(confetti);
  const cctx = confetti.getContext("2d");

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  } catch (e) {
    console.warn("teacher: no WebGL", e);
    panel.remove();
    window.__teacher = "no-webgl";
    return;
  }
  renderer.setPixelRatio(1);
  renderer.setSize(W, H);
  panel.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, W / H, 0.1, 50);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x556677, 0.85));
  const key = new THREE.DirectionalLight(0xffffff, 0.75);
  key.position.set(1.5, 3, 4);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xbcd7ff, 0.35);
  rim.position.set(-3, 2, -2);
  scene.add(rim);

  // Toon shading in three steps: a drawn look, quick to render.
  const steps = new Uint8Array([90, 170, 255]);
  const gradient = new THREE.DataTexture(steps, 3, 1, THREE.LuminanceFormat);
  gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
  gradient.needsUpdate = true;
  const mat = (c) => new THREE.MeshToonMaterial({ color: c, gradientMap: gradient });
  const flat = (c) => new THREE.MeshBasicMaterial({ color: c });

  const SKIN = female ? 0x8d5a38 : 0x7a4b2c;
  const HAIR = 0x15100d;
  const TOP = female ? 0xd9476a : 0x8fb8e8;
  const OVER = female ? 0x2c3e66 : 0x34405a;
  const skin = mat(SKIN), hair = mat(HAIR);

  function mesh(geo, m, x = 0, y = 0, z = 0, parent = scene) {
    const o = new THREE.Mesh(geo, m);
    o.position.set(x, y, z);
    parent.add(o);
    return o;
  }
  const sphere = (r, ws = 24, hs = 16) => new THREE.SphereGeometry(r, ws, hs);

  // ── the body ──
  const body = new THREE.Group();
  scene.add(body);
  const torsoShape = [[0, 0.2], [0.33, 0.2], [0.36, 0.5], [0.38, 0.85], [0.42, 1.08], [0.36, 1.2], [0.12, 1.26], [0, 1.27]]
    .map(([r, y]) => new THREE.Vector2(r * (female ? 0.94 : 1.04), y));
  const torso = mesh(new THREE.LatheGeometry(torsoShape, 28), mat(TOP), 0, 0, 0, body);
  torso.scale.z = 0.62;
  // An open jacket or cardigan over the top: two front panels.
  for (const s of [-1, 1]) {
    const p = mesh(new THREE.BoxGeometry(0.17, 0.82, 0.04), mat(OVER), s * 0.26, 0.72, 0.205, body);
    p.rotation.z = s * 0.06;
    const sleeveTop = mesh(sphere(0.12), mat(OVER), s * 0.38, 1.12, 0, body);
    sleeveTop.scale.set(1, 0.8, 0.9);
  }
  if (!female) {      // a collar and a tie
    mesh(new THREE.BoxGeometry(0.07, 0.42, 0.03), mat(0xb3262e), 0, 0.98, 0.235, body).rotation.z = 0.02;
    mesh(new THREE.ConeGeometry(0.05, 0.08, 4), mat(0xb3262e), 0, 1.2, 0.23, body).rotation.x = Math.PI;
  } else {            // a necklace
    const chain = mesh(new THREE.TorusGeometry(0.13, 0.008, 6, 32, Math.PI), mat(0xe8c15a), 0, 1.2, 0.19, body);
    chain.rotation.set(0.35, 0, Math.PI);
  }
  mesh(new THREE.CylinderGeometry(0.075, 0.085, 0.16, 16), skin, 0, 1.31, 0, body);

  // Arms: shoulder → elbow → hand, each joint a group to turn.
  function arm(side) {
    const shoulder = new THREE.Group();
    shoulder.position.set(side * 0.38, 1.13, 0);
    body.add(shoulder);
    mesh(new THREE.CylinderGeometry(0.075, 0.065, 0.46, 12), mat(OVER), 0, -0.23, 0, shoulder);
    const elbow = new THREE.Group();
    elbow.position.set(0, -0.46, 0);
    shoulder.add(elbow);
    mesh(new THREE.CylinderGeometry(0.062, 0.05, 0.4, 12), mat(OVER), 0, -0.2, 0, elbow);
    mesh(new THREE.CylinderGeometry(0.052, 0.05, 0.05, 12), mat(TOP), 0, -0.4, 0, elbow);
    const hand = mesh(sphere(0.065, 14, 10), skin, 0, -0.46, 0.01, elbow);
    hand.scale.set(0.9, 1.15, 0.6);
    const thumb = mesh(sphere(0.027, 10, 8), skin, side * -0.045, -0.43, 0.04, elbow);
    thumb.scale.set(1, 1.5, 1);
    return { shoulder, elbow };
  }
  const armA = arm(1), armB = arm(-1);        // A: screen right, the gesturing arm

  // ── the head ──
  const head = new THREE.Group();
  head.position.set(0, 1.58, 0);
  body.add(head);
  const skull = mesh(sphere(0.3, 32, 24), skin, 0, 0, 0, head);
  skull.scale.set(0.92, 1.08, 0.98);
  const jaw = mesh(sphere(0.24, 24, 16), skin, 0, -0.11, 0.035, head);
  jaw.scale.set(0.95, 0.85, 0.95);
  for (const s of [-1, 1]) {
    mesh(sphere(0.06, 12, 10), skin, s * 0.285, -0.01, 0, head).scale.set(0.5, 1, 0.8);
    if (female) mesh(sphere(0.022, 10, 8), mat(0xe8c15a), s * 0.29, -0.08, 0.01, head);
  }
  const nose = mesh(sphere(0.045, 14, 10), mat(female ? 0x6d4027 : 0x5e361f), 0, -0.03, 0.29, head);
  nose.scale.set(1.15, 0.9, 0.8);

  // Eyes, lids that blink, brows that say how the teacher feels.
  const eyes = [], lids = [], brows = [];
  for (const s of [-1, 1]) {
    const white = mesh(sphere(0.068, 20, 14), flat(0xfaf7f2), s * 0.108, 0.045, 0.232, head);
    white.scale.set(1, 0.9, 0.55);
    const iris = mesh(sphere(0.04, 16, 12), flat(0x3a2414), s * 0.108, 0.042, 0.262, head);
    iris.scale.set(1, 1, 0.45);
    const pupil = mesh(sphere(0.02, 10, 8), flat(0x050505), s * 0.108, 0.042, 0.276, head);
    const glint = mesh(sphere(0.008, 6, 6), flat(0xffffff), s * 0.108 + 0.012, 0.056, 0.281, head);
    eyes.push({ iris, pupil, glint, x: s * 0.108 });
    const lid = mesh(new THREE.SphereGeometry(0.073, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), skin, s * 0.108, 0.046, 0.233, head);
    lid.scale.set(1, 0.05, 0.6);
    lids.push(lid);
    if (female) {           // lashes
      const lash = mesh(new THREE.BoxGeometry(0.13, 0.01, 0.01), flat(0x0b0806), s * 0.108, 0.1, 0.25, head);
      lash.rotation.z = s * -0.1;
      eyes[eyes.length - 1].lash = lash;
    }
    const brow = mesh(new THREE.BoxGeometry(0.11, female ? 0.018 : 0.026, 0.02), hair, s * 0.11, 0.14, 0.27, head);
    brows.push({ mesh: brow, side: s });
  }

  // The mouth: a smile line when closed, an open mouth (teeth, tongue) when speaking.
  const mouth = new THREE.Group();
  mouth.position.set(0, -0.13, 0.268);
  head.add(mouth);
  const lip = female ? 0x8a2f3e : 0x4a2216;
  const smile = mesh(new THREE.TorusGeometry(0.07, 0.011, 8, 20, Math.PI), mat(lip), 0, 0.02, 0, mouth);
  smile.rotation.z = Math.PI;
  const open = mesh(sphere(0.055, 20, 12), flat(0x3a0d10), 0, 0, 0, mouth);
  const teeth = mesh(new THREE.BoxGeometry(0.07, 0.016, 0.02), flat(0xf4f1ea), 0, 0.01, 0.016, mouth);
  const tongue = mesh(sphere(0.03, 12, 8), flat(0xb5484f), 0, -0.016, 0.008, mouth);
  const lips = mesh(new THREE.TorusGeometry(0.056, 0.011, 8, 24), mat(lip), 0, 0, 0.004, mouth);

  // Hair: a cap over the skull, then her afro puff or his short crop.
  // The cap's rim rises at the front (a hairline above the brows) and falls at the back.
  const cap = mesh(new THREE.SphereGeometry(0.318, 32, 16, 0, Math.PI * 2, 0, Math.PI * (female ? 0.47 : 0.42)), hair, 0, 0.03, -0.02, head);
  cap.scale.set(0.95, 1.1, 1.02);
  cap.rotation.x = female ? -0.55 : -0.5;
  if (female) {
    mesh(sphere(0.21, 24, 16), hair, 0, 0.3, -0.2, head).scale.set(1.15, 1, 1);
    for (const s of [-1, 1]) mesh(sphere(0.12, 16, 12), hair, s * 0.25, 0.04, -0.12, head).scale.set(0.6, 1.3, 1);
    mesh(new THREE.TorusGeometry(0.13, 0.026, 8, 24), mat(0xf2b134), 0, 0.22, -0.16, head).rotation.x = 1.0;
  } else {
    // Glasses: two rims and a bridge.
    for (const s of [-1, 1]) mesh(new THREE.TorusGeometry(0.068, 0.009, 8, 28), flat(0x111111), s * 0.105, 0.045, 0.285, head);
    mesh(new THREE.BoxGeometry(0.06, 0.01, 0.01), flat(0x111111), 0, 0.055, 0.29, head);
    // A short beard along the jaw, behind the lips.
    mesh(new THREE.SphereGeometry(0.225, 20, 12, 0, Math.PI * 2, Math.PI * 0.7, Math.PI * 0.3), hair, 0, -0.07, 0.025, head);
  }

  // ── poses ──
  const P = {
    // [turn out, swing forward, bend the elbow] — solved so the hand lands
    // where it should: on the chin to think, at the viewer to point.
    rest: { a: [0.14, 0, -0.25], b: [-0.14, 0, -0.25] },
    present: { a: [1.3, -0.4, -1.75], b: [-0.14, 0, -0.3] },
    think: { a: [-0.7, -1.45, -2.1], b: [1.35, 0.2, -1.65] },       // knuckles on the cheek
    point: { a: [-0.05, -1.75, 0], b: [-0.14, 0, -0.3] },
    thumbs: { a: [-0.4, -0.55, -2.1], b: [-0.14, 0, -0.3] },
    celebrate: { a: [2.95, -0.15, -0.5], b: [-2.95, -0.15, -0.5] },
    wave: { a: [2.65, -0.6, -1.45], b: [-0.14, 0, -0.3] },
  };
  const ease = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x));
  const mix = (p, q, k) => p.map((v, i) => v + (q[i] - v) * k);
  function poseName(i, into) {
    const sc = scenes[i] || {};
    let name = POSE[sc.scene] || (TEACHER_SCENES[sc.scene] ? "present" : "rest");
    if (name === "celebrate" && into > 1.6) name = "rest";
    if (name === "point" && into > 1.8) name = "thumbs";
    return name;
  }
  function poseOf(i, into) { return P[poseName(i, into)]; }

  // ── the clock ──
  function sceneAt(t) {
    const starts = window.__starts || [];
    let i = -1;
    for (let k = 0; k < starts.length; k++) if (starts[k] <= t) i = k;
    return { i, into: i >= 0 ? t - starts[i] : t, start: i >= 0 ? starts[i] : 0 };
  }
  // Mouth shapes (visemes), one per frame, from the words: [width, open, round, teeth].
  const SHAPE = {
    X: [1.0, 0.0, 0.0, 0], M: [0.95, 0.0, 0.0, 0], A: [1.05, 0.95, 0.0, 1], E: [1.25, 0.38, 0.0, 1],
    O: [0.7, 0.62, 1.0, 0], L: [1.0, 0.38, 0.0, 1], S: [1.18, 0.14, 0.0, 1], F: [1.06, 0.12, 0.0, 1],
    R: [0.84, 0.32, 0.6, 0], K: [1.0, 0.52, 0.0, 1],
  };
  function shapeAt(i, into) {
    const seq = ((cfg.shapes || [])[i]) || "";
    if (!seq.length || into < 0) return null;
    const f = into * FPS, k = Math.floor(f), r = f - k;
    if (k >= seq.length) return SHAPE.X;
    const a = SHAPE[seq[k]] || SHAPE.X, b = SHAPE[seq[Math.min(seq.length - 1, k + 1)]] || SHAPE.X;
    // Lips move between shapes, not jump: blend toward the next frame's.
    const out = a.map((v, n) => v + (b[n] - v) * r * 0.8);
    out.c = seq[k];
    return out;
  }
  // Where each phrase starts: the voice coming back after a pause. A speaker
  // gestures and nods on these, not on every syllable.
  const ONSETS = (cfg.mouth || []).map((env) => {
    const out = [];
    let quiet = 99;
    (env || []).forEach((v, k) => {
      if (v < 0.08) quiet++;
      else { if (quiet >= FPS * 0.22) out.push(k / FPS); quiet = 0; }
    });
    return out;
  });
  function beatAt(i, into) {
    let since = 99, n = 0;
    for (const s of ONSETS[i] || []) if (s <= into) { since = into - s; n++; }
    return { since, n };
  }
  function energy(i, into) {
    const env = ((cfg.mouth || [])[i]) || [];
    if (!env.length || into < 0) return 0;
    const f = into * FPS, k = Math.floor(f), r = f - k;
    const a = env[Math.min(env.length - 1, k)] || 0, b = env[Math.min(env.length - 1, k + 1)] || 0;
    return k >= env.length ? 0 : a + (b - a) * r;
  }
  const hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  function blink(t) {
    // A blink every 2.8–4.6 s, a tenth of a second long, fixed by the clock.
    let at = 0.8, n = 0;
    while (at < t + 0.2) {
      const d = t - at;
      if (d >= 0 && d < 0.14) return 1 - Math.abs(d - 0.07) / 0.07;
      at += 2.8 + hash(++n) * 1.8;
    }
    return 0;
  }

  // ── layout: studio (big) or corner (small) ──
  const capEl = document.getElementById("sc-caption"), count = document.getElementById("sc-count");
  const foot = root.querySelector(".foot"), hook = root.querySelector(".hook");
  const hookText = hook ? hook.textContent : "";
  const panelLook = panel.style.cssText;
  function layout(big, i, cover) {
    if (cover) {              // on the cover: big, cut out, pointing at the viewer
      panel.style.cssText = panelLook + ";z-index:6;left:560px;background:transparent;border:0;box-shadow:none";
      panel.style.transform = "scale(1.08)";
      panel.style.top = `${1640 - H}px`;
      return;
    }
    if (panel.style.zIndex === "6") panel.style.cssText = panelLook;
    const s = 0.42 + 0.58 * big;
    panel.style.transform = `scale(${s})`;
    panel.style.top = `${1580 - H}px`;
    const right = 40 + W * s;
    if (capEl) {
      capEl.style.left = `${60 + (right - 60 + 30) * big}px`;
      capEl.style.fontSize = `${60 - 12 * big}px`;
      capEl.style.top = `${1040 + 10 * big}px`;
    }
    if (count) { count.style.left = `${(right - 10) * big}px`; count.style.right = `${130 * big}px`; }
    if (foot) foot.style.left = `${Math.max(60, right + 24)}px`;
    if (hook) {
      const sc = scenes[i] || {};
      const want = sc.scene === "check" ? "Did you get it right?" : hookText;
      if (hook.textContent !== want) hook.textContent = want;
    }
  }

  // ── effects: tension and celebration ──
  function confettiAt(since) {
    cctx.clearRect(0, 0, 1080, 1920);
    if (since < 0 || since > 3.2) return;
    const colours = ["#facc15", "#f472b6", "#34d399", "#60a5fa", "#fb923c", "#ffffff"];
    for (let n = 0; n < 140; n++) {
      const x0 = 540 + (hash(n) - 0.5) * 300, y0 = 760 + hash(n + 9) * 120;
      const vx = (hash(n + 3) - 0.5) * 1500, vy = -900 - hash(n + 5) * 900;
      const x = x0 + vx * since, y = y0 + vy * since + 0.5 * 1900 * since * since;
      if (y > 1950) continue;
      const rot = (hash(n + 7) - 0.5) * 20 * since, w = 14 + hash(n + 11) * 14;
      cctx.save();
      cctx.globalAlpha = Math.max(0, 1 - since / 3.2);
      cctx.translate(x, y); cctx.rotate(rot);
      cctx.fillStyle = colours[n % colours.length];
      cctx.fillRect(-w / 2, -w / 4, w, w / 2 * (0.4 + 0.6 * Math.abs(Math.cos(since * 9 + n))));
      cctx.restore();
    }
  }

  function moodAt(i, into) {
    const sc = scenes[i] || {}, prev = scenes[i - 1] || {};
    const now = MOOD[sc.scene] || "calm", was = MOOD[prev.scene] || "calm";
    const k = ease(into / 0.6);
    const level = (m) => (m === "tense" ? 1 : 0), joy = (m) => (m === "lively" ? 1 : 0);
    return { tense: level(was) + (level(now) - level(was)) * k, lively: joy(was) + (joy(now) - joy(was)) * k, scene: sc.scene };
  }

  // ── a frame ──
  function draw(t) {
    const { i, into } = sceneAt(t);
    const sc = scenes[i] || {};
    const prevBig = i > 0 && TEACHER_SCENES[(scenes[i - 1] || {}).scene] ? 1 : 0;
    const nowBig = i < 0 || TEACHER_SCENES[sc.scene] ? 1 : 0;
    const big = prevBig + (nowBig - prevBig) * ease(into / 0.55);
    const cover = window.__coverUntil != null && t < window.__coverUntil;
    layout(big, i, cover);

    const m = moodAt(i, into);
    const e = Math.min(1, energy(i, into) * 1.5);
    if (REAL) panel.style.visibility = "visible";
    if (REAL && cover) {
      REAL.draw({ t, i: -1, into: t, sc: { scene: "cover" }, m: { tense: 0, lively: 1 }, e: 0, shape: null, k: 1,
                  from: "point", to: "point", talk: 0, dance: 0, think: 0, blink: 0, surprise: 1 });
      return;
    }
    if (REAL) {
      let k = ease(into / 0.5);
      if (sc.scene === "answer" && into > 1.6) k = ease((into - 1.6) / 0.4);
      REAL.draw({ t, i, into, sc, m, e, shape: shapeAt(i, into), k,
                  from: i > 0 ? poseName(i - 1, 99) : "rest", to: poseName(i, into),
                  talk: e * (TEACHER_SCENES[sc.scene] || i < 0 ? 1 : 0.4),
                  dance: 0, beat: beatAt(i, into),
                  think: sc.scene === "countdown" ? ease(into / 0.6) : 0, blink: blink(t) });
      effects(t, i, into, sc, m);
      return;
    }
    // No realistic model (still loading, or it could not load): no teacher
    // at all rather than the old drawn figure — the frame is complete without one.
    panel.style.visibility = "hidden";
    if (!window.__teacherDrawn) return;
    // Pose: from the last scene's to this one's over half a second.
    const from = i > 0 ? poseOf(i - 1, 99) : P.rest, to = poseOf(i, into);
    let k = ease(into / 0.5);
    if (sc.scene === "answer" && into > 1.6) k = ease((into - 1.6) / 0.4);
    const pa = mix(from.a, to.a, k), pb = mix(from.b, to.b, k);
    // Talking hands: a small beat with the voice.
    const talk = e * (TEACHER_SCENES[sc.scene] || i < 0 ? 1 : 0.4);
    pa[0] += Math.sin(t * 5.1) * 0.08 * talk; pa[2] += Math.sin(t * 6.3) * 0.18 * talk;
    if (to === P.wave) pa[0] += Math.sin(t * 9) * 0.3 * k;
    // The end: a wave, then a little dance to the bright music (120 beats a minute).
    const dance = sc.scene === "outro" ? ease((into - 1.2) / 0.5) : 0;
    if (dance > 0) {
      const d = into - 1.2, beat = Math.sin(d * Math.PI * 4), sway = Math.sin(d * Math.PI * 2);
      const da = [1.25 + 0.75 * beat, -0.55, -1.7 + 0.5 * beat], db = [-1.25 + 0.75 * beat, -0.55, -1.7 - 0.5 * beat];
      for (let n = 0; n < 3; n++) { pa[n] += (da[n] - pa[n]) * dance; pb[n] += (db[n] - pb[n]) * dance; }
    }
    armA.shoulder.rotation.set(pa[1], 0, pa[0]); armA.elbow.rotation.set(pa[2], 0, 0);
    armB.shoulder.rotation.set(pb[1], 0, pb[0]); armB.elbow.rotation.set(pb[2], 0, 0);

    // Breath, sway, nods with the voice; a tilt to think.
    const think = sc.scene === "countdown" ? ease(into / 0.6) : 0;
    body.position.y = Math.sin(t * 1.6) * 0.008 + (sc.scene === "answer" && into < 1.6 ? Math.abs(Math.sin(into * 7)) * 0.05 * (1 - into / 1.6) : 0);
    body.scale.y = 1 + Math.sin(t * 1.6) * 0.006;
    body.position.x = 0; body.rotation.set(0, 0, 0);
    if (dance > 0) {
      const d = into - 1.2;
      body.position.x = Math.sin(d * Math.PI * 2) * 0.09 * dance;                 // a step to each side
      body.position.y += Math.abs(Math.sin(d * Math.PI * 4)) * 0.05 * dance;      // a bounce on every beat
      body.rotation.z = Math.sin(d * Math.PI * 2) * 0.07 * dance;
      body.rotation.y = Math.sin(d * Math.PI) * 0.3 * dance;
    }
    head.rotation.set(Math.sin(t * 7.3) * 0.05 * e - 0.12 * think + Math.sin(t * 0.9) * 0.02,
                      Math.sin(t * 0.6) * 0.09 * (1 - think), Math.sin(t * 0.45) * 0.03 - 0.13 * think
                      + Math.sin((into - 1.2) * Math.PI * 4) * 0.12 * dance);

    // Face: eyes glance up to think; brows knit under tension, lift for joy.
    const look = think * 0.012;
    for (const ey of eyes) {
      const dx = Math.sin(t * 0.37) * 0.006;
      ey.iris.position.x = ey.x + dx; ey.pupil.position.x = ey.x + dx; ey.glint.position.x = ey.x + dx + 0.009;
      ey.iris.position.y = 0.042 + look; ey.pupil.position.y = 0.042 + look; ey.glint.position.y = 0.053 + look;
    }
    const shut = Math.max(blink(t), 0.25 * m.tense * (sc.scene === "countdown" ? 1 : 0));
    for (const lid of lids) if (lid) lid.scale.y = 0.05 + 0.95 * shut;
    for (const b of brows) {
      b.mesh.rotation.z = b.side * (0.28 * m.tense - 0.18 * m.lively);   // inner ends down to focus, up for joy
      b.mesh.position.y = 0.14 - 0.012 * m.tense + 0.02 * m.lively + 0.008 * e;
    }
    // The lips: the shape of the sound being said, opened by how loud it is.
    const sh = shapeAt(i, into);
    const width = sh ? sh[0] : 1, round = sh ? sh[2] : 0;
    const opening = sh ? (sh[1] > 0 ? sh[1] * (0.45 + 0.55 * Math.min(1, e * 1.3)) : 0) : (e > 0.06 ? e : 0);
    const pressed = sh && sh[1] === 0 && e > 0.06;          // m, b, p: lips together, mid-speech
    open.visible = tongue.visible = lips.visible = opening > 0.02;
    teeth.visible = open.visible && (sh ? sh[3] === 1 : true);
    smile.visible = !open.visible;
    const w = width * (1 + 0.12 * m.lively) * (1 - 0.32 * round);
    open.scale.set(w, 0.1 + 0.62 * opening, 0.35);
    lips.scale.set(w, 0.14 + 0.58 * opening, 1 + 0.4 * round);
    lips.position.z = 0.004 + 0.012 * round;
    teeth.position.y = 0.008 + 0.014 * opening;
    tongue.position.y = (sh && sh.c === "L" ? 0.004 : -0.014) - 0.014 * opening;
    const grin = 0.35 + 0.65 * m.lively - 0.3 * m.tense;
    smile.scale.set((0.8 + 0.4 * m.lively) * (pressed ? 0.85 : 1), pressed ? 0.1 : Math.max(0.12, grin), pressed ? 1.6 : 1);

    // Camera: a slow push in under tension, a shake on each second of the count.
    let cz = 3.75 - 0.45 * m.tense, cy = 1.45, cx = 0;
    if (sc.scene === "countdown") {
      const tickAge = into - Math.floor(into);
      const shake = Math.exp(-tickAge * 14) * 0.012;
      cx += Math.sin(into * 61) * shake; cy += Math.cos(into * 47) * shake;
    }
    camera.position.set(cx, cy, cz);
    camera.lookAt(0, 1.42 - 0.04 * m.tense, 0);
    renderer.render(scene, camera);
    effects(t, i, into, sc, m);
  }

  // The frame around: a dark pulsing vignette, then a warm glow and confetti.
  function effects(t, i, into, sc, m) {
    const pulse = sc.scene === "countdown" ? 0.12 * Math.exp(-(into - Math.floor(into)) * 5) : 0;
    vignette.style.opacity = String(Math.min(0.85, 0.55 * m.tense + pulse));
    glow.style.opacity = String(0.6 * m.lively * (sc.scene === "answer" ? Math.max(0.35, 1 - into / 3) : 0.35));
    const answerAt = scenes.findIndex((s) => s.scene === "answer");
    const starts = window.__starts || [];
    confettiAt(answerAt >= 0 && starts[answerAt] != null ? t - starts[answerAt] - 0.3 : -1);
  }

  // ── the realistic teacher: a Microsoft Rocketbox avatar (MIT) ──
  let REAL = null;
  function b64(s) { const bin = atob(s), out = new Uint8Array(bin.length); for (let k = 0; k < bin.length; k++) out[k] = bin.charCodeAt(k); return out.buffer; }
  // The cast: one teacher (TEACHER_GLB), or a classroom — a teacher and
  // students — each a model in TEACHER_GLBS, placed as cfg.cast says.
  const GLBS = window.TEACHER_GLBS || (window.TEACHER_GLB ? { teacher: window.TEACHER_GLB } : null);
  const parse = (data) => new Promise((ok, fail) => new THREE.GLTFLoader().parse(b64(data), "", ok, fail));
  window.__teacherReady = (GLBS && THREE.GLTFLoader && cfg.model !== false)
    ? Promise.all(Object.entries(GLBS).map(([id, data]) => parse(data).then((g) => [id, g])))
        .then((loaded) => {
          try { REAL = makeStage(loaded); window.__teacher = "real"; } catch (err) { console.warn("teacher model", err); }
          draw(0);
          return REAL;
        })
        .catch((err) => { console.warn("teacher model", err); return null; })
    : Promise.resolve(null);

  function makeStage(loaded) {
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    const stage = new THREE.Scene();
    stage.add(new THREE.HemisphereLight(0xfff4e6, 0x2c3448, 0.8));
    const keyL = new THREE.DirectionalLight(0xffffff, 1.25); keyL.position.set(1.2, 2.4, 2.6); stage.add(keyL);
    const fillL = new THREE.DirectionalLight(0xdfe8ff, 0.4); fillL.position.set(-1.8, 1.4, 1.6); stage.add(fillL);
    const rimL = new THREE.DirectionalLight(0xbcd2ff, 0.7); rimL.position.set(0, 2.2, -2.2); stage.add(rimL);
    const cam = new THREE.PerspectiveCamera(26, W / H, 0.05, 30);
    const places = Object.fromEntries((cfg.cast || []).map((c) => [c.id, c]));
    const actors = {};
    for (const [id, g] of loaded) actors[id] = makeActor(g, stage, places[id] || { x: 0 });
    const ids = Object.keys(actors);
    const speakerAt = (i) => {
      const who = (cfg.speakers || [])[i];
      return actors[who] ? who : (actors.teacher ? "teacher" : ids[0]);
    };
    const V = (x, y, z) => new THREE.Vector3(x, y, z);

    function draw(st) {
      const who = st.i >= 0 ? speakerAt(st.i) : speakerAt(0);
      const before = st.i > 0 ? speakerAt(st.i - 1) : who;
      const head = actors[who].head;
      for (const id of ids) {
        const me = id === who;
        const student = id !== "teacher";
        let pose = "rest";
        if (!me) {
          if (st.sc.scene === "countdown" && student) pose = "think";          // the class thinks it through
          else if (st.sc.scene === "answer" && student && st.into < 1.6) pose = "celebrate";
        }
        actors[id].draw(me ? st : { ...st, e: 0, shape: null, talk: 0, from: pose, to: pose, k: 1, surprise: 0,
                                    dance: st.dance, think: pose === "think" ? st.think : 0 },
                        head);
      }
      // Camera: on whoever speaks, moving there over half a second; the whole
      // class for the first moments of the question.
      let cx = 0, cy = 0;
      if (st.sc.scene === "countdown") {
        const age = st.into - Math.floor(st.into), shake = Math.exp(-age * 14) * 0.006;
        cx = Math.sin(st.into * 61) * shake; cy = Math.cos(st.into * 47) * shake;
      }
      const kk = ease(st.into / 0.6);
      const focus = actors[before].head.clone().lerp(head, kk);
      let dist = 1.95 - 0.45 * st.m.tense;
      if (ids.length > 1 && st.sc.scene === "title" && st.into < 2.2) {
        const xs = ids.map((id) => actors[id].head.x);
        const wide = V((Math.min(...xs) + Math.max(...xs)) / 2, Math.max(...ids.map((id) => actors[id].head.y)) - 0.15, focus.z);
        const w = 1 - ease((st.into - 1.2) / 1.0);
        focus.lerp(wide, w);
        dist += (2.6 + (Math.max(...xs) - Math.min(...xs)) * 1.6 - dist) * w;
      }
      cam.position.set(focus.x + cx, focus.y - 0.08 + cy, focus.z + dist);
      cam.lookAt(focus.x, focus.y - 0.16 + 0.04 * st.m.tense, focus.z);
      renderer.render(stage, cam);
    }
    return { draw, actors };
  }

  function makeActor(gltf, stage, place) {
    const V = (x, y, z) => new THREE.Vector3(x, y, z);
    const model = gltf.scene;
    model.position.set(place.x || 0, 0, place.z || 0);
    model.rotation.y = place.ry || 0;
    const base = model.position.clone(), baseRy = model.rotation.y;
    stage.add(model);
    const bones = {}, faces = [];
    model.traverse((o) => {
      if (o.isBone) bones[o.name.replace(/^Bip01_/, "")] = o;
      if (o.isMesh) { o.frustumCulled = false; if (o.morphTargetDictionary) faces.push(o); }
    });
    const B = (n) => bones[n];
    const rest = new Map();
    Object.values(bones).forEach((b) => rest.set(b, b.quaternion.clone()));
    model.updateMatrixWorld(true);
    const at = (n) => B(n).getWorldPosition(new THREE.Vector3());
    const H0 = at("Head"), J0 = at("MJaw");
    const sideOf = (n) => Math.sign(at(n).x) || 1;
    // A: the arm on the viewer's right, the one that gestures.
    const A = sideOf("L_UpperArm") > 0 ? "L" : "R", Bs = A === "L" ? "R" : "L";
    const arm = (s) => ({ up: B(`${s}_UpperArm`), fore: B(`${s}_Forearm`), hand: B(`${s}_Hand`), side: sideOf(`${s}_UpperArm`),
                          fingers: Object.keys(bones).filter((n) => n.startsWith(`${s}_Finger`)).map((n) => bones[n]) });
    const armA = arm(A), armB = arm(Bs);
    const SA = at(`${A}_UpperArm`), SB = at(`${Bs}_UpperArm`);
    const sa = armA.side, sb = armB.side;

    // Where each hand goes (and which way its elbow points) for each pose.
    // At rest a presenter's hands meet loosely in front, at the waist — not
    // hanging at the sides.
    const T = {
      rest: { a: [V(sa * 0.035, SA.y - 0.5, SA.z + 0.24), V(sa * 0.5, -0.6, -0.2)],
              b: [V(sb * 0.035, SB.y - 0.52, SB.z + 0.23), V(sb * 0.5, -0.6, -0.2)] },
      present: { a: [V(SA.x + sa * 0.26, SA.y - 0.27, SA.z + 0.3), V(sa * 0.4, -0.7, -0.1)] },
      think: { a: [V(J0.x + sa * 0.04, J0.y - 0.14, J0.z + 0.11), V(sa * 0.05, -1, 0.35)],
               b: [V(SB.x * 0.05, SB.y - 0.42, SB.z + 0.24), V(sb * 0.2, -0.45, 0.05)] },
      point: { a: [V(SA.x + sa * 0.04, SA.y - 0.06, SA.z + 0.55), V(sa * 0.2, -0.5, 0.0)] },
      thumbs: { a: [V(SA.x - sa * 0.04, SA.y - 0.26, SA.z + 0.33), V(sa * 0.25, -0.5, -0.05)] },
      celebrate: { a: [V(SA.x + sa * 0.22, SA.y + 0.5, SA.z + 0.06), V(sa * 0.6, 0.0, -0.25)],
                   b: [V(SB.x + sb * 0.22, SB.y + 0.5, SB.z + 0.06), V(sb * 0.6, 0.0, -0.25)] },
      wave: { a: [V(SA.x + sa * 0.2, SA.y + 0.38, SA.z + 0.12), V(sa * 0.6, -0.6, -0.1)] },
    };
    let thinkAt = null;          // the cheek, where the head is this frame
    const pick = (name, which) => (name === "think" && which === "a" && thinkAt ? [thinkAt, T.think.a[1]]
                                   : (T[name] && T[name][which]) || T.rest[which]);

    // ── turning bones by world axes, whatever the rig's own axes are ──
    const qa = new THREE.Quaternion(), qb = new THREE.Quaternion(), qc = new THREE.Quaternion();
    function turn(bone, axis, angle) {
      if (!bone || !angle) return;
      bone.parent.getWorldQuaternion(qa);
      qb.setFromAxisAngle(axis, angle);
      qc.copy(qa).invert().multiply(qb).multiply(qa);
      bone.quaternion.premultiply(qc);
      bone.updateMatrixWorld(true);
    }
    const X = V(1, 0, 0), Y = V(0, 1, 0), Z = V(0, 0, 1);
    const angle = (u, v) => u.angleTo(v);
    // Two-bone IK: shoulder–elbow–wrist reaches `target`, the elbow toward `pole`.
    function reach(ch, target, pole) {
      const a = ch.up.getWorldPosition(V()), b = ch.fore.getWorldPosition(V()), c = ch.hand.getWorldPosition(V());
      const lab = a.distanceTo(b), lcb = b.distanceTo(c);
      const lat = Math.min(Math.max(a.distanceTo(target), 0.02), lab + lcb - 0.005);
      const ac = c.clone().sub(a), ab = b.clone().sub(a), ba = a.clone().sub(b), bc = c.clone().sub(b), at_ = target.clone().sub(a);
      const ac_ab0 = angle(ac, ab), ba_bc0 = angle(ba, bc), ac_at0 = angle(ac, at_);
      const clamp = (x) => Math.min(1, Math.max(-1, x));
      const ac_ab1 = Math.acos(clamp((lcb * lcb - lab * lab - lat * lat) / (-2 * lab * lat)));
      const ba_bc1 = Math.acos(clamp((lat * lat - lab * lab - lcb * lcb) / (-2 * lab * lcb)));
      const axis0 = ac.clone().cross(ab).normalize();
      if (axis0.lengthSq() < 1e-8) axis0.copy(Z);
      turn(ch.up, axis0, ac_ab1 - ac_ab0);
      turn(ch.fore, axis0, ba_bc1 - ba_bc0);
      const c2 = ch.hand.getWorldPosition(V()).sub(a);
      const axis1 = c2.clone().cross(at_).normalize();
      if (axis1.lengthSq() > 1e-8) turn(ch.up, axis1, angle(c2, at_));
      // Swing the elbow round the shoulder–hand line toward the pole.
      const dir = at_.clone().normalize();
      const elbow = ch.fore.getWorldPosition(V()).sub(a);
      const e1 = elbow.clone().sub(dir.clone().multiplyScalar(elbow.dot(dir)));
      const p = pole.clone().sub(dir.clone().multiplyScalar(pole.dot(dir)));
      if (e1.lengthSq() > 1e-8 && p.lengthSq() > 1e-8) {
        let ang = angle(e1, p);
        if (e1.clone().cross(p).dot(dir) < 0) ang = -ang;
        turn(ch.up, dir, ang);
      }
    }
    function curl(ch, amount, thumbIn) {
      ch.fingers.forEach((f) => {
        const isThumb = /Finger0/.test(f.name);
        const amt = isThumb ? (thumbIn ? 0.5 : 0.15) : amount;
        f.quaternion.multiply(qb.setFromAxisAngle(Z, -amt * ch.side));
      });
    }

    // The face: viseme shapes from the words, and the mood's expressions.
    const VIS = { X: "AA_VI_00_Sil", M: "AA_VI_01_PP", F: "AA_VI_02_FF", L: "AA_VI_04_DD", S: "AA_VI_07_SS",
                  A: "AA_VI_10_aa", E: "AA_VI_11_E", O: "AA_VI_13_O", R: "AA_VI_09_RR", K: "AA_VI_05_KK" };
    const SEC = { L: "AA_VI_08_nn", E: "AA_VI_12_I", O: "AA_VI_14_U" };
    function face(name, value) {
      for (const f of faces) {
        const k = f.morphTargetDictionary[name];
        if (k !== undefined) f.morphTargetInfluences[k] = Math.min(1, Math.max(0, (f.morphTargetInfluences[k] || 0) + value));
      }
    }

    // Smooth, never-repeating motion: three slow waves, a different mix per seed.
    const drift = (x, seed) => (Math.sin(x + seed * 1.7) + 0.5 * Math.sin(2.13 * x + seed * 2.9) + 0.25 * Math.sin(3.71 * x + seed * 0.6)) / 1.75;
    const rnd = (n) => { const v = Math.sin(n * 91.7 + (place.x || 0) * 13.1) * 43758.5453; return v - Math.floor(v); };
    function glance(t) {
      let at = 0, n = 0, x = 0, y = 0;
      while (at <= t) { x = (rnd(++n) - 0.5) * 0.36; y = rnd(n + 50) < 0.25 ? -0.2 : 0; at += 1.1 + rnd(n + 99) * 1.6; }
      return { x: rnd(n + 7) < 0.45 ? 0 : x, y };
    }

    function draw(st, speakerHead) {
      const { t, into, m, e } = st;
      // Back to rest, then the frame's pose on top.
      rest.forEach((q, b) => b.quaternion.copy(q));
      model.position.copy(base); model.rotation.set(0, baseRy, 0);
      // A slow shift of weight, as a person standing to speak does.
      model.position.x = base.x + drift(t * 0.13, 3) * 0.012;
      model.rotation.y = baseRy + drift(t * 0.17, 4) * 0.03;
      model.updateMatrixWorld(true);
      turn(B("Spine1"), X, Math.sin(t * 1.5) * 0.01);                       // breath
      turn(B("Spine"), Z, drift(t * 0.2, 5) * 0.012);
      // A nod as each phrase lands; between, the head drifts a little.
      const bt = st.beat || { since: 99, n: 0 };
      const landing = bt.since < 0.45 ? Math.sin(Math.PI * bt.since / 0.45) : 0;
      const nod = 0.05 * landing * Math.min(1, st.talk * 1.5) + drift(t * 0.33, 1) * 0.018 + 0.1 * st.think;
      turn(B("Neck"), X, nod * 0.4);
      turn(B("Head"), X, nod * 0.6);
      // A listener turns toward whoever is speaking.
      const toward = speakerHead && speakerHead.distanceTo(H0) > 0.05
        ? Math.max(-0.5, Math.min(0.5, Math.atan2(speakerHead.x - H0.x, 1.6))) : 0;
      turn(B("Head"), Y, drift(t * 0.27, 2) * 0.06 * (1 - st.think) + toward);
      turn(B("Head"), Z, -sa * 0.12 * st.think + drift(t * 0.21, 6) * 0.025);
      model.updateMatrixWorld(true);
      const Jn = B("MJaw").getWorldPosition(V());
      const shift = model.position.clone().sub(base);
      thinkAt = V(Jn.x + sa * 0.04, Jn.y - 0.14, Jn.z + 0.11).sub(shift);   // under the chin

      // Hands: from the last pose's spot to this one's, with the voice's beat.
      const ta = pick(st.from, "a")[0].clone().lerp(pick(st.to, "a")[0], st.k);
      const pa = pick(st.from, "a")[1].clone().lerp(pick(st.to, "a")[1], st.k);
      const tb = pick(st.from, "b")[0].clone().lerp(pick(st.to, "b")[0], st.k);
      const pb = pick(st.from, "b")[1].clone().lerp(pick(st.to, "b")[1], st.k);
      // A gesture as each phrase begins — the palm opens up and out, then
      // settles — one hand then the other; still between phrases.
      const g = bt.since < 0.8 ? Math.sin(Math.PI * bt.since / 0.8) * Math.min(1, st.talk * 1.4) : 0;
      const gh = bt.n % 3 === 2 ? tb : ta, gs = gh === ta ? sa : sb;
      gh.x += gs * 0.06 * g; gh.y += 0.07 * g; gh.z += 0.07 * g;
      ta.y += drift(t * 0.5, 7) * 0.006; tb.y += drift(t * 0.5, 8) * 0.006;
      if (st.to === "wave") ta.x += Math.sin(t * 6) * 0.045 * st.k * sa;
      reach(armA, ta.add(shift), pa);
      reach(armB, tb.add(shift), pb);
      // To think, the wrist bends the knuckles in under the chin.
      const thinking = (st.to === "think" ? st.k : 0) + (st.from === "think" ? 1 - st.k : 0);
      turn(armA.hand, X, -1.0 * thinking);
      const fist = st.to === "thumbs" || st.to === "celebrate" ? st.k : 0;
      curl(armA, 0.25 + 0.6 * fist + (st.to === "think" ? 0.65 * st.k : 0), fist > 0.5);
      curl(armB, 0.3 + (st.to === "celebrate" ? 0.6 * st.k : 0), false);

      // Face.
      for (const f of faces) f.morphTargetInfluences.fill(0);
      const sh = st.shape;
      if (sh && sh.c && sh.c !== "X") {
        const open = 0.45 + 0.55 * Math.min(1, e * 1.3);
        face(VIS[sh.c], 0.95 * open);
        if (SEC[sh.c]) face(SEC[sh.c], 0.35 * open);
      } else if (e > 0.08) face("AA_VI_10_aa", e * 0.6);
      face("AK_09_EyeBlinkLeft", st.blink); face("AK_10_EyeBlinkRight", st.blink);
      // Measured, warm: brows lift a little as a phrase lands, a resting smile
      // that grows when the answer is right.
      face("AK_01_BrowDownLeft", 0.3 * m.tense); face("AK_02_BrowDownRight", 0.3 * m.tense);
      face("AK_03_BrowInnerUp", 0.2 * m.lively + 0.25 * st.think + 0.12 * landing);
      face("AK_04_BrowOuterUpLeft", 0.15 * m.lively + 0.18 * landing); face("AK_05_BrowOuterUpRight", 0.15 * m.lively + 0.18 * landing);
      const smile = 0.2 + 0.3 * m.lively - 0.08 * m.tense;
      face("AK_44_MouthSmileLeft", smile); face("AK_45_MouthSmileRight", smile);
      face("AK_07_CheekSquintLeft", 0.15 * m.lively); face("AK_08_CheekSquintRight", 0.15 * m.lively);
      // The eyes: mostly on the viewer, with a small glance every second or two.
      const gaze = glance(t);
      face(gaze.x > 0 ? "AK_15_EyeLookOutLeft" : "AK_13_EyeLookInLeft", Math.abs(gaze.x));
      face(gaze.x > 0 ? "AK_14_EyeLookInRight" : "AK_16_EyeLookOutRight", Math.abs(gaze.x));
      if (gaze.y < 0) { face("AK_11_EyeLookDownLeft", -gaze.y); face("AK_12_EyeLookDownRight", -gaze.y); }
      face("AK_17_EyeLookUpLeft", 0.45 * st.think); face("AK_18_EyeLookUpRight", 0.45 * st.think);
      face("AK_19_EyeSquintLeft", 0.25 * m.tense); face("AK_20_EyeSquintRight", 0.25 * m.tense);
      if (st.surprise) {      // the cover: wide eyes, brows up, an "oh!"
        face("AK_21_EyeWideLeft", 0.7 * st.surprise); face("AK_22_EyeWideRight", 0.7 * st.surprise);
        face("AK_03_BrowInnerUp", 0.5 * st.surprise); face("AA_VI_13_O", 0.55 * st.surprise);
      }

    }
    return { draw, head: H0 };
  }

  window.__onTime = draw;
  window.__teacher = "ready";
  draw(0);
})();
