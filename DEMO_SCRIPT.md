# Demo runbook

Five minutes. The room decides in the first fifteen seconds, again at the siren, and again
when you switch the language.

---

## Before you present

```bash
make demo          # replay mode — zero network dependency
```

- [ ] Open **http://localhost:8000**, click **Test audio output**. Browsers block audio until
      a user gesture, so this must happen *before* you present, not during.
- [ ] Check the language dropdown lists voices. If a language shows `·no voice`, your OS
      lacks that TTS voice — install it or pick another for the demo. **Test the one you plan
      to switch to.**
- [ ] Set **Data source → Langtang Lirung collapse**, press **⟲ restart**.
- [ ] Volume up. The siren and the spoken alert are the demo.
- [ ] Second tab on `localhost:8000/api/methodology` for the "is it hardcoded" question.
- [ ] Phone on the same wifi at `http://<laptop-ip>:8000`, ready to hold up.
- [ ] Use `make demo` (replay) on stage, never `make run` (live). Live mode is for Q&A, where
      "this is real current data" lands much harder as an *answer*.

---

## 0:00 — The opening (do not touch the laptop)

> *"On August 26, a glacier collapse in Nepal killed over 955 people and left almost 4,800
> missing. Nepal already had an early warning system. It didn't fail from lack of funding.
> It failed because it was listening for rain, not for the mountain moving.*
>
> ***We built a system that listens for both — and tells you what it can predict, what it can
> only detect, and the difference.***"

---

## 0:25 — Establish that it is real

Point at the hero row and the **Feed health** panel.

> *"Ten districts across Nepal and Assam, live rainfall and modelled river discharge from
> Open-Meteo, live seismic from USGS. Plus every active natural disaster on Earth —"*

Click the **World hazards** tab.

> *"— from NASA EONET and GDACS. Earthquakes, cyclones, wildfires, volcanoes, floods,
> droughts, nine categories, all free, no API keys anywhere. Filter them live."*

Tap two filter chips. Then back to **Regional risk**.

---

## 0:55 — Press **▶ Play**

Narrate only over the transitions.

**Around step 6** — micro-seismicity begins:

> *"Shallow micro-seismicity at the headwall. No rain anywhere in Nepal — Channel A is flat.
> A rainfall-only system sees nothing here. Not a low reading. Nothing."*

**Step 8 — detachment. Let the siren fire. Do not talk over it.**

Three full seconds of silence from you.

> *"That's the collapse. Ground motion only — still zero rainfall."*

---

## 1:40 — The countdowns, and the honest refusal

Point at the **Forecast** panel — it now shows DETECTED cards, not percentages.

> *"Look at what the forecast panel says. It does **not** give you a probability. It says
> DETECTED, twenty-six minutes, and it says why: this hazard class cannot be predicted in
> advance. It can only be detected and then outrun.*
>
> *Most systems would have shown you a confident number there. That's the number that gets
> people killed. Rasuwa: twenty-six minutes. Chitwan: nine hours, seven hundred and twenty
> thousand people. The mountain already moved — we're just doing arithmetic on how fast water
> travels down a valley."*

---

## 2:15 — The kill shot

Point at the red banner.

> *"Sixteen lakh people at risk that a rainfall-only system reports as normal."*

Hit **Legacy — rainfall only**. Wait. Let the room watch every zone go green.

> *"Same data, same engine, one channel removed. This is the configuration that was live in
> the Trishuli valley that morning. The water is forty-five minutes downstream and the board
> is green.*
>
> *That's not our simulation of a failure. That's the failure, reproduced."*

Switch back to **Dual-channel**.

---

## 2:50 — Now show prediction where prediction is honest

Switch **Data source → Assam tributary floods**, seek to ~step 16.

> *"Different mechanism — rainfall-driven, slow onset. Here we CAN predict."*

Point at the forecast cards: 96%, 95%, 91%, all IMMINENT.

> *"Ninety-six percent probability of dangerous flooding in Golaghat within twenty-four hours.
> And it shows its working: a hundred and seventy-four millimetres forecast, plus sixty-eight
> carried over, against a hundred and sixteen millimetre threshold. Method named on the card —
> numerical weather prediction threshold exceedance, on real ECMWF forecast output.*
>
> *Above ninety percent it alarms on the forecast alone. It doesn't wait for the threshold,
> because waiting for the threshold means warning people while the water is already arriving.*
>
> *No trained model anywhere in this. Every one of those is a published method — Reasenberg-Jones
> for aftershocks, Caine for landslides, IMD criteria for heat. We can't validate a trained
> flood model in a day, and neither can anyone who says they did."*

Now flip to **Legacy** again.

> *"And here's the honest part — watch. Nothing changes. Zero blind spots. On the rainfall
> mechanism, existing systems work, and we show that on purpose. We're not claiming they're
> useless. We're claiming they have one specific blind spot, and that blind spot just killed
> a thousand people."*

---

## 3:40 — The last mile: language and voice

Change the language dropdown to **नेपाली**.

> *"Same alert. Eleven languages, including Bhojpuri and Maithili — dialects that never get
> localised. And it's not machine translation at send time: these are validated templates,
> checked at load so a translation can never silently drop the arrival time."*

Click **🔊 Repeat aloud** on the siren card.

> *"That's the script for a village loudspeaker. 'Do not wait for rain' is in there, because
> in a clear-sky flood the absence of rain is exactly what kills people."*

Open the **Ask** assistant, tap *"What should I do?"*.

> *"And anyone can just ask — typing or speaking — and hear the answer back in their language.
> This tier runs entirely offline. Someone asking 'should I leave' can't depend on an API
> being up."*

Hold up your phone showing the same dashboard.

> *"Runs on a phone. Works offline. Zero API keys."*

---

## 4:40 — Land it

> *"Prahari. Two channels, because the last system only had one — and it tells you the
> difference between what it predicts and what it merely detects."*

---

## Q&A — the questions you will actually get

**"Is any of this hardcoded?"**
> `curl localhost:8000/api/methodology` — every weight, curve, anchor, band edge and forecast
> method, served from the same constants the engine imports. And `make test` — 76 tests,
> including one asserting no rain ever enters the Langtang scenario, so the demonstration
> cannot be circular.

**"Can you show it on live data?"**
> Switch **Data source → Live feeds**. Ten real districts plus every live global hazard event.
> Usually calm regionally — say so. *"A warning system that's green on a quiet day is working."*
> The world map will not be calm; there is always something burning somewhere.

**"You said no prediction earlier, now you show 96%. Which is it?"**
> Both, and the distinction is the point. We forecast **hazard likelihood** from published
> forecast output — that's standard hydrometeorology. We do **not** forecast earthquakes.
> The aftershock number is conditional on a mainshock that already happened, which is a
> solved problem. And where a hazard genuinely can't be forecast — a glacier collapse — the
> system refuses to give a number and says so on screen.

**"How do you know your thresholds are right?"**
> The rainfall thresholds are IMD's published categories, not ours. The aftershock parameters
> are the standard Reasenberg-Jones generics. The terrain scaling and Channel B weights are
> reasoned, not validated — that's the honest answer. METHODOLOGY.md §8 lists it as the single
> most important gap: no measured hit rate or false-alarm rate, because that needs a labelled
> multi-year archive.

**"What about false alarms?"**
> Two guards. The proximity gate is multiplicative, so a distant M5.4 scores below 5 — that's
> a test. And the state machine damps only de-escalation: hysteresis, dwell and cooldown stop
> the siren flapping, while escalation is never suppressed. A system that cries wolf gets
> switched off, and a switched-off system detects nothing.

**"Are the translations actually correct?"**
> Structurally, yes — every one is validated at load to carry the same placeholders, and
> that's tested. Fluently? **They're machine-assisted and unreviewed, and the API reports
> exactly that.** Before any real deployment a fluent speaker of each variety has to read
> them. I'd rather show you that caveat than let you find it.

**"Why not use ML?"**
> We do, where it's honest — retrieval over a curated Hugging Face corpus, matching the live
> signature to documented events. What we don't do is claim a trained predictor, because with
> ten labelled incidents anything trained would be memorisation wearing a lab coat.

**"Why no WhatsApp/SMS?"**
> WhatsApp was built and then removed. It needed a third-party sandbox and a pre-registered
> number, which made the most visible channel the least reliable one. The webhook is the
> integration point, and every alert ships with all eleven translations attached so a PA
> controller or SMS gateway downstream needs no second round trip.

**"What would you build next?"**
> Validation against a real historical catalogue, first. Then native-speaker review of the
> translations, official DHM/CWC gauge feeds instead of gridded forecasts, dedicated
> ground-motion sensors instead of USGS, and the actual last mile — loudspeaker and SMS
> hardware. All in the README as roadmap, and not built, because I'd rather show you eight
> things that work than twenty that don't.

---

## If something breaks

| Symptom | Fix |
|---|---|
| No audio | Click **Test audio output** — browsers need a user gesture first |
| Speech is in the wrong language | Your OS lacks that TTS voice; the dropdown marks it `·no voice`. Pick another or install the voice |
| Dashboard blank | `make demo` again; check port 8000 is free |
| Map is empty rectangles | Tile CDN blocked. Expected. Say *"no basemap on this network — the geography is the river graph"* |
| World map empty | It falls back to a bundled snapshot; if that's missing run `make snapshots` |
| Nothing escalates | You're on **Live feeds** on a quiet day. Switch to a scenario, or hit **Trigger alert pipeline** |
| Siren won't stop | **Acknowledge**, or press Escape |
| Everything is on fire | **Trigger alert pipeline** on any zone works with no network, no scenario and no state. It is the one-button fallback demo. |
