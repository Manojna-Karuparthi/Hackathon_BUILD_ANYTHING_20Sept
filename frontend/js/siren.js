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

/** Speak the alert. Slowed and pitched for intelligibility over a PA system. */
export function speak(text, { rate = 0.88, repeat = 1 } = {}) {
  if (!window.speechSynthesis || !text) return;
  speechSynthesis.cancel();
  for (let i = 0; i < repeat; i++) {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = rate;
    u.pitch = 1.0;
    u.volume = 1.0;
    const preferred =
      voices.find((v) => /en-IN|en_IN/i.test(v.lang)) ||
      voices.find((v) => /en-GB/i.test(v.lang)) ||
      voices.find((v) => /^en/i.test(v.lang));
    if (preferred) u.voice = preferred;
    speechSynthesis.speak(u);
  }
}

export const stopSpeech = () => window.speechSynthesis && speechSynthesis.cancel();

/** Browsers block audio until the user interacts; call this from a click. */
export function unlockAudio() {
  const ac = audioCtx();
  if (ac && ac.state === "suspended") ac.resume();
}
