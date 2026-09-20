/* The situation assistant panel: ask in any supported language, by typing or
   by voice, and hear the answer read back.

   Both directions use the browser's own speech engines — SpeechRecognition in,
   SpeechSynthesis out — so there is no API key, no upload of anyone's voice to
   a third party, and nothing that stops working when the network does. Where a
   dialect has no TTS voice of its own (Bhojpuri, Maithili) it falls back to a
   related voice, and the panel says so rather than silently substituting. */

import { postBody, json } from "./api.js";
import { speak, stopSpeech } from "./siren.js";

export class Assistant {
  constructor(getLang) {
    this.getLang = getLang;
    this.log = document.getElementById("as-log");
    this.form = document.getElementById("as-form");
    this.input = document.getElementById("as-input");
    this.mic = document.getElementById("as-mic");
    this.chips = document.getElementById("as-chips");
    this.panel = document.getElementById("assistant");
    this.recognition = null;
    this.busy = false;

    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      const q = this.input.value.trim();
      if (q) this.ask(q);
    });

    document.getElementById("fab-assistant").addEventListener("click", () => this.open());
    document.getElementById("as-close").addEventListener("click", () => this.close());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.panel.hidden) this.close();
    });

    this._setupMic();
    this._loadStarters();
  }

  open() {
    this.panel.hidden = false;
    this.input.focus();
    if (!this.log.children.length) {
      this.push("bot", "Ask me what is happening, whether you are safe, or what to do. I answer in the language selected at the top.", { meta: "ready · offline capable" });
    }
  }

  close() {
    this.panel.hidden = true;
    stopSpeech();
    this._stopMic();
  }

  async _loadStarters() {
    try {
      const { questions } = await json("/api/assistant/starters");
      this.chips.innerHTML = questions
        .map((q) => `<button class="as-chip" type="button">${q}</button>`)
        .join("");
      this.chips.querySelectorAll(".as-chip").forEach((el) =>
        el.addEventListener("click", () => this.ask(el.textContent))
      );
    } catch { /* starters are a convenience, not a requirement */ }
  }

  push(who, text, { meta = "", rtl = false, speakText = null } = {}) {
    const div = document.createElement("div");
    div.className = `msg is-${who}${rtl ? " is-rtl" : ""}`;
    div.textContent = text;
    if (meta) {
      const m = document.createElement("span");
      m.className = "msg-meta";
      m.textContent = meta;
      div.appendChild(m);
    }
    if (speakText) {
      const b = document.createElement("button");
      b.className = "msg-speak";
      b.type = "button";
      b.textContent = "🔊 Read aloud";
      b.addEventListener("click", () => speak(speakText, { lang: this._speechLang }));
      div.appendChild(b);
    }
    this.log.appendChild(div);
    this.log.scrollTop = this.log.scrollHeight;
    return div;
  }

  async ask(question) {
    if (this.busy) return;
    this.busy = true;
    this.input.value = "";
    this.push("user", question);
    const pending = this.push("bot", "…");

    try {
      const res = await postBody("/api/assistant", {
        question, lang: this.getLang(), zone_id: null, allow_llm: true,
      });
      this._speechLang = res.speech_lang;
      pending.remove();
      this.push("bot", res.text, {
        meta: `${res.intent} · ${res.source} · ${res.speech_lang}`,
        rtl: res.rtl,
        speakText: res.speak,
      });
      speak(res.speak, { lang: res.speech_lang });
    } catch (err) {
      pending.remove();
      this.push("bot", `Could not reach the assistant: ${err.message}`);
    } finally {
      this.busy = false;
    }
  }

  /* ---------------------------------------------------------- voice in --- */
  _setupMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      this.mic.disabled = true;
      this.mic.title = "Voice input is not supported in this browser";
      return;
    }
    this.mic.addEventListener("click", () => {
      if (this.recognition) return this._stopMic();
      const rec = new SR();
      rec.lang = this._speechLang || "en-IN";
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onresult = (e) => {
        const said = e.results[0][0].transcript;
        this.input.value = said;
        this.ask(said);
      };
      rec.onerror = () => this._stopMic();
      rec.onend = () => this._stopMic();
      this.recognition = rec;
      this.mic.classList.add("is-live");
      rec.start();
    });
  }

  _stopMic() {
    if (this.recognition) {
      try { this.recognition.stop(); } catch { /* already stopped */ }
      this.recognition = null;
    }
    this.mic.classList.remove("is-live");
  }

  setSpeechLang(code) { this._speechLang = code; }
}
