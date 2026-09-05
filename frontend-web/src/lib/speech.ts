/**
 * The device's own voice, for narrating a walkthrough step.
 *
 * The player had two tiers: a pre-generated MP3, or — with no file — a timer
 * that advanced on a word count. The middle is where almost every walkthrough
 * actually sits, because narration audio costs a call per step to synthesise
 * and a place to store it, so most steps have no file and are read in silence.
 *
 * Every browser can already speak. It costs nothing, needs no key, stores
 * nothing, and works with no network on most platforms — and it is genuinely
 * real-time, which a synthesised file is not. It also syncs by construction:
 * `onend` fires when the sentence finishes, which is exactly when the step
 * should advance, so the timing follows the words instead of estimating them.
 */

export interface SpeakHandle {
  cancel: () => void;
}

/** Whether this device can speak at all. */
export function canSpeak(): boolean {
  return typeof window !== "undefined"
    && "speechSynthesis" in window
    && typeof window.SpeechSynthesisUtterance === "function";
}

let cachedVoices: SpeechSynthesisVoice[] = [];

function voices(): SpeechSynthesisVoice[] {
  if (!canSpeak()) return [];
  const found = window.speechSynthesis.getVoices();
  if (found.length) cachedVoices = found;
  return cachedVoices;
}

if (canSpeak()) {
  // Voices load asynchronously, and on a first visit `getVoices()` returns []
  // until this fires. Without it the first step of the first walkthrough is
  // silent and every later one speaks.
  window.speechSynthesis.addEventListener?.("voiceschanged", () => {
    cachedVoices = window.speechSynthesis.getVoices();
  });
}

/**
 * The best available voice for a language tag, or none.
 *
 * Accent is negotiable; language is not. Kenyan English is rarely installed,
 * so `en-KE` happily becomes `en-GB` — a lesson read in another English accent
 * is worth far more than a lesson read in silence.
 *
 * Crossing INTO another language is not the same trade. Asked for Kiswahili on
 * a device with no Kiswahili voice, this used to return the default English
 * one, which reads Swahili as mispronounced nonsense — worse than silence,
 * because it sounds like teaching. It now returns nothing and the caller falls
 * back to the step timer.
 */
export function voiceFor(lang: string): SpeechSynthesisVoice | undefined {
  const all = voices();
  if (!all.length) return undefined;
  const wanted = (lang || "en-KE").toLowerCase();
  const base = wanted.split("-")[0];

  const exact = all.find((v) => v.lang.toLowerCase() === wanted);
  if (exact) return exact;

  const sameLanguage = all.filter((v) => {
    const tag = v.lang.toLowerCase();
    return tag === base || tag.startsWith(`${base}-`);
  });
  if (sameLanguage.length) {
    return sameLanguage.find((v) => v.default) || sameLanguage[0];
  }

  // No voice for this language at all. Say nothing rather than say it wrong.
  return undefined;
}

/**
 * Say one step's narration.
 *
 * `onEnd` fires when the words finish — or immediately, if this device cannot
 * speak — so a caller can always treat it as "the step is over" and never has
 * to branch on whether speech happened.
 */
export function speak(
  text: string,
  options: {
    lang?: string;
    rate?: number;
    onEnd?: () => void;
    onError?: (reason: string) => void;
  } = {}
): SpeakHandle {
  const trimmed = (text || "").trim();
  if (!canSpeak() || !trimmed) {
    options.onError?.(canSpeak() ? "nothing to say" : "this device has no voice");
    return { cancel: () => {} };
  }

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(trimmed);
  utterance.lang = options.lang || "en-KE";
  utterance.rate = options.rate ?? 0.95; // a shade under conversational: this
                                         // is a teacher explaining a step
  const voice = voiceFor(utterance.lang);
  if (voice) utterance.voice = voice;

  let finished = false;
  const done = () => {
    if (finished) return;
    finished = true;
    window.clearInterval(keepAlive);
    options.onEnd?.();
  };

  utterance.onend = done;
  utterance.onerror = (event) => {
    if (finished) return;
    finished = true;
    window.clearInterval(keepAlive);
    // A cancel raises `interrupted`, which is us stopping it deliberately —
    // not a failure to report.
    const reason = (event as SpeechSynthesisErrorEvent).error || "unknown";
    if (reason === "interrupted" || reason === "canceled") return;
    options.onError?.(reason);
  };

  // Chrome stops speaking after roughly fifteen seconds unless the queue is
  // nudged, and a step's narration is often longer than that. Pausing and
  // resuming keeps it going; the interval is cleared the moment it ends.
  const keepAlive = window.setInterval(() => {
    if (finished) {
      window.clearInterval(keepAlive);
      return;
    }
    if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
      window.speechSynthesis.pause();
      window.speechSynthesis.resume();
    }
  }, 10_000);

  window.speechSynthesis.speak(utterance);

  return {
    cancel: () => {
      finished = true;
      window.clearInterval(keepAlive);
      window.speechSynthesis.cancel();
    },
  };
}

export function pauseSpeech(): void {
  if (canSpeak() && window.speechSynthesis.speaking) window.speechSynthesis.pause();
}

export function resumeSpeech(): void {
  if (canSpeak() && window.speechSynthesis.paused) window.speechSynthesis.resume();
}

export function stopSpeech(): void {
  if (canSpeak()) window.speechSynthesis.cancel();
}
