/* Sound effects, timed to the board: a whoosh as an electron flies, a pop as
 * it lands, a chime when the shell is full, fizzing, drips, a flame's roar.
 *
 * Builders note a sound with window.sfxAt(t, kind, gain, pitch); the list is
 * window.__sfx. Live, they are synthesised here (WebAudio, no files) as the
 * clock passes them; a rendered video reads the same list and the server
 * synthesises the same recipes (services/sfx.py) into a track under the voice.
 */
(function () {
  "use strict";
  const events = (window.__sfx = window.__sfx || []);
  window.sfxAt = function (t, kind, gain, pitch) {
    if (!(t >= 0)) return;
    events.push({ t: Math.round(t * 1000) / 1000, kind, gain: gain == null ? 1 : gain, pitch: pitch || 1 });
  };
  let ctx = null, master = null, noise = null, last = -1;
  function ensure() {
    if (ctx) return ctx;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      master = ctx.createGain(); master.gain.value = 0.32; master.connect(ctx.destination);
      noise = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const d = noise.getChannelData(0); let s = 7;
      for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = (s / 2147483647) * 2 - 1; }
    } catch (e) { ctx = null; }
    return ctx;
  }
  window.__sfxUnlock = function () { if (ensure() && ctx.state === "suspended") ctx.resume(); };
  // Called with the clock: plays what it has just passed, never on a jump (a seek).
  window.__sfxTick = function (now, playing) {
    if (!playing || !ctx) { last = now; return; }
    if (now < last || now - last > 0.5) { last = now; return; }
    for (const e of events) if (e.t > last && e.t <= now) play(e);
    last = now;
  };

  function env(g, at, peak, attack, decay) {
    g.gain.setValueAtTime(0.0001, at);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), at + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  }
  function tone(type, f0, f1, dur, peak, attack) {
    const t = ctx.currentTime, o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    env(g, t, peak, attack || 0.005, dur); o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.05);
  }
  function hiss(kind, f0, f1, dur, peak, attack, q) {
    const t = ctx.currentTime, src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain();
    src.buffer = noise; src.loop = true;
    f.type = kind; f.Q.value = q || 1; f.frequency.setValueAtTime(f0, t); f.frequency.exponentialRampToValueAtTime(Math.max(30, f1), t + dur);
    env(g, t, peak, attack || 0.01, dur); src.connect(f); f.connect(g); g.connect(master); src.start(t); src.stop(t + dur + 0.1);
  }
  // The recipes: the same in services/sfx.py, so a video sounds as the page does.
  const R = {
    whoosh: (k, p) => hiss("bandpass", 300 * p, 2600 * p, 0.55, 0.9 * k, 0.25, 1.4),
    pop: (k, p) => tone("sine", 900 * p, 260 * p, 0.12, 0.8 * k),
    ding: (k, p) => { tone("sine", 1320 * p, 1310 * p, 1.1, 0.5 * k); tone("sine", 2640 * p, 2630 * p, 0.7, 0.18 * k); },
    chime: (k, p) => [1047, 1319, 1568].forEach((f, i) => setTimeout(() => tone("sine", f * p, f * p, 0.9, 0.35 * k), i * 90)),
    zap: (k, p) => { hiss("highpass", 3000, 1200, 0.16, 0.5 * k, 0.003); tone("sawtooth", 1800 * p, 300 * p, 0.18, 0.18 * k); },
    snap: (k, p) => { hiss("highpass", 2500, 2500, 0.04, 0.8 * k, 0.002); tone("sine", 160 * p, 70 * p, 0.18, 0.7 * k); },
    thud: (k, p) => tone("sine", 95 * p, 48 * p, 0.35, 0.9 * k),
    fizz: (k) => hiss("highpass", 5000, 7000, 1.2, 0.18 * k, 0.15),
    drip: (k, p) => tone("sine", 1250 * p, 560 * p, 0.07, 0.5 * k),
    sparkle: (k, p) => [0, 1, 2, 3].forEach((i) => setTimeout(() => tone("sine", (2200 + i * 380) * p, (2200 + i * 380) * p, 0.25, 0.16 * k), i * 70)),
    flame: (k) => hiss("lowpass", 380, 260, 1.4, 0.45 * k, 0.3),
    click: (k, p) => tone("square", 1800 * p, 1700 * p, 0.025, 0.25 * k, 0.001),
    riser: (k, p) => { hiss("bandpass", 200 * p, 3000 * p, 1.6, 0.5 * k, 1.4, 2); tone("sine", 220 * p, 880 * p, 1.6, 0.12 * k, 1.4); },
    tick: (k, p) => tone("triangle", 1500 * p, 1500 * p, 0.05, 0.35 * k),
  };
  function play(e) { try { (R[e.kind] || R.pop)(e.gain, e.pitch); } catch (err) { /* a sound never stops the board */ } }
})();
