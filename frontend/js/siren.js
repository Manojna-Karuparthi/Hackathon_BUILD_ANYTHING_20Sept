/* Siren + speech.

   Deliberately zero third-party dependencies: the tone is synthesised with the
   Web Audio API and the voice comes from the browser's own speech engine.
   Nothing here can fail because someone else's sandbox is down or a phone
   number was not pre-joined - which is exactly why this, and not a messaging
   integration, is the channel the demo leans on.

   The spoken text is written to be relayed over a village public-address
   loudspeaker, for people who have no smartphone at all. */

let ctx = null;
const audioCtx = () => {
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) ctx = new AC();
  }
  return ctx;
};

/** Two-tone rising/falling civil-defence style sweep. */
export function playSiren(cycles = 3) {
  const ac = audioCtx();
  if (!ac) return;
  if (ac.state === "suspended") ac.resume();

  const t0 = ac.currentTime;
  const gain = ac.createGain();
  gain.connect(ac.destination);
  gain.gain.setValueAtTime(0.0001, t0);

  const osc = ac.createOscillator();
  osc.type = "sawtooth";
  osc.connect(gain);

  const period = 1.1;
  for (let i = 0; i < cycles; i++) {
    const s = t0 + i * period;
    osc.frequency.setValueAtTime(440, s);
    osc.frequency.linearRampToValueAtTime(880, s + period * 0.5);
    osc.frequency.linearRampToValueAtTime(440, s + period);
    gain.gain.setValueAtTime(0.0001, s);
    gain.gain.exponentialRampToValueAtTime(0.22, s + 0.06);
    gain.gain.exponentialRampToValueAtTime(0.0001, s + period - 0.04);
  }
  osc.start(t0);
  osc.stop(t0 + cycles * period + 0.1);
}

let voices = [];
const loadVoices = () => { voices = window.speechSynthesis ? speechSynthesis.getVoices() : []; };
if (window.speechSynthesis) {
  loadVoices();
  speechSynthesis.onvoiceschanged = loadVoices;
}

/** Speak the alert in a given language.

    `lang` is a BCP-47 tag from the server (hi-IN, ne-NP, ta-IN, ...). If the
    device has no voice for it we fall back to the base language, then to
    English, and report which one was actually used - a dialect silently read
    out in the wrong language is worse than an obvious fallback. */
export function speak(text, { rate = 0.88, repeat = 1, lang = "en-IN" } = {}) {
  if (!window.speechSynthesis || !text) return null;
  speechSynthesis.cancel();
  if (!voices.length) loadVoices();

  const base = lang.split("-")[0];
  const chosen =
    voices.find((v) => v.lang.replace("_", "-").toLowerCase() === lang.toLowerCase()) ||
    voices.find((v) => v.lang.toLowerCase().startsWith(base.toLowerCase())) ||
    voices.find((v) => /^en/i.test(v.lang)) ||
    null;

  for (let i = 0; i < repeat; i++) {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = rate;
    u.pitch = 1.0;
    u.volume = 1.0;
    u.lang = lang;
    if (chosen) u.voice = chosen;
    speechSynthesis.speak(u);
  }
  return chosen ? chosen.lang : null;
}

/** Which of the requested languages this device can actually voice. */
export function availableVoiceLangs() {
  if (!voices.length) loadVoices();
  return new Set(voices.map((v) => v.lang.replace("_", "-").toLowerCase()));
}

export const stopSpeech = () => window.speechSynthesis && speechSynthesis.cancel();

/** Browsers block audio until the user interacts; call this from a click. */
export function unlockAudio() {
  const ac = audioCtx();
  if (ac && ac.state === "suspended") ac.resume();
}
