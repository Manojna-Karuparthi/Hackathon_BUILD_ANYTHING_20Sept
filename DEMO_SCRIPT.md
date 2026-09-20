# Demo runbook

Four minutes. The room decides in the first fifteen seconds and again at the siren.

---

## Before you present

```bash
make demo          # replay mode — zero network dependency
```

- [ ] Open **http://localhost:8000**, click **Test audio output** — browsers block audio
      until a user gesture, so this must happen *before* you present, not during.
- [ ] Set **Data source → Langtang Lirung collapse**, press **⟲ restart**.
- [ ] Volume up. The siren and the spoken alert are the demo.
- [ ] Second tab on `localhost:8000/api/methodology` for the "is it hardcoded" question.
- [ ] Phone on the same wifi at `http://<laptop-ip>:8000`, ready to hold up.
- [ ] Use `make demo` (replay), never `make run` (live), on stage. Live mode is for the
      Q&A, where "this is real current data" lands much harder as an *answer*.

---

## 0:00 — The opening (do not touch the laptop)

> *"On August 26, a glacier collapse in Nepal killed over 955 people and left almost 4,800
> missing. Nepal already had an early warning system. It didn't fail from lack of funding.
> It failed because it was listening for rain, not for the mountain moving.*
>
> ***We built a system that listens for both.***"

Say it with the dashboard already on screen behind you, sitting calm and green.

---

## 0:25 — Establish that it is real

Point at the **Feed health** panel and the map.

> *"Ten districts across Nepal and Assam. Live rainfall and modelled river discharge from
> Open-Meteo, live seismic from USGS, all free and key-less. Right now I'm in replay mode so
> this room's wifi can't ruin anyone's morning — but it's the same engine, the same code
> path. I'll switch it to live at the end."*

---

## 0:45 — Press **▶ Play**

Let it run. Narrate only over the transitions.

**Around step 6** — micro-seismicity begins:

> *"Shallow micro-seismicity at the headwall. No rain anywhere in Nepal — look at Channel A,
> it's flat. A rainfall-only system sees nothing here. Not a low reading. Nothing."*

**Step 8 — detachment. Let the siren fire. Do not talk over it.**

Let the sound and the spoken alert play in full. Three seconds of silence from you.

> *"That's the collapse. Ground motion only — still zero rainfall."*

---

## 1:30 — The countdowns (the emotional core)

Point at the zone list. The ETAs are ticking down in real time.

> *"Rasuwa: twenty-six minutes. Nuwakot: an hour forty. Chitwan: nine hours, seven hundred
> and twenty thousand people.*
>
> *Nobody is predicting anything here. The mountain already moved. We detected it at the
> slope and we're doing arithmetic on how fast water travels down a valley. That's it.
> Twenty-six minutes is the entire product."*

---

## 2:00 — The kill shot

Point at the red banner across the top.

> *"Sixteen lakh people at risk that a rainfall-only system reports as normal."*

Now hit **Legacy — rainfall only**.

Wait. Let the room watch every zone go green.

> *"That's the same data, same engine, one channel removed. This is the configuration that
> was live in the Trishuli valley that morning. The water is forty-five minutes downstream
> and the board is green.*
>
> *That's not our simulation of a failure. That's the failure, reproduced."*

Switch back to **Dual-channel**.

---

## 2:40 — Show it is not a black box

Click **Rasuwa**, point at the *Why is this at this level* panel.

> *"Every number traces back. M3.8, 1.2 km depth, in the slope-failure window, glacier ice
> upslope. Published IMD thresholds, fixed weights, no trained model anywhere — because we
> can't validate a trained flood model in a day and neither can anyone who says they did.*
>
> *And look at the closest documented analogues: Chamoli 2021, Seti River 2012. Both ice-rock
> avalanches. Both clear-sky floods. Both killed people who had no reason to expect water.
> That's retrieval over a Hugging Face dataset, not a prediction."*

---

## 3:10 — The honesty beat (this wins as many points as the kill shot)

Switch **Data source → Assam tributary floods**, seek to ~step 18.

> *"Here's the Assam mechanism — rainfall-driven, slow onset. Watch what happens when I flip
> to legacy."*

Flip it. **Nothing changes.**

> *"Identical. Zero blind spots. We are not claiming existing systems are useless — on their
> home mechanism they work, and we show that on purpose. We're claiming they have one
> specific blind spot, and that blind spot just killed a thousand people."*

---

## 3:40 — The last mile

Point at the **Audio** panel, then hold up your phone showing the same dashboard.

> *"The alert channel is a browser siren and speech synthesis — no Twilio, no sandbox, no
> pre-joined number, nothing that can fail on stage. And that's not a shortcut, it's the
> design: this text is written to be relayed over a village loudspeaker, for people who have
> no smartphone at all. 'Do not wait for rain' is in the script, because in a clear-sky flood
> the absence of rain is exactly what kills people.*
>
> *Runs on a phone. Works offline. Zero API keys."*

---

## 4:00 — Land it

> *"Prahari. Two channels, because the last system only had one."*

---

## Q&A — the questions you will actually get

**"Is any of this hardcoded?"**
> `curl localhost:8000/api/methodology` — every weight, curve, anchor and band edge, served
> from the same constants the engine imports. And `make test` — forty tests, including one
> asserting no rain ever enters the Langtang scenario, so the demonstration can't be circular.

**"Can you show it on live data?"**
> Switch **Data source → Live feeds**. Ten real districts, current conditions, real USGS
> events. Usually calm — say so. *"A warning system that's green on a quiet day is working."*

**"Isn't this just earthquake prediction, which is impossible?"**
> No, and that distinction matters. We detect mass movement that has **already started**,
> from its seismic signature — the collapse radiates a signal, and we're racing it downhill.
> Water travels slower than a seismic wave. That gap is the warning.

**"How do you know your thresholds are right?"**
> The rainfall thresholds are IMD's published categories, not ours. The terrain scaling and
> the Channel B weights are reasoned, not validated — and that's the honest answer.
> METHODOLOGY.md §8 lists it as the single most important piece of missing work: we have no
> measured hit rate or false-alarm rate, because that needs a labelled multi-year archive.
> Anyone claiming they validated one over a hackathon is telling you something else.

**"What about false alarms?"**
> Two guards. The proximity gate is multiplicative, so a distant M5.4 scores below 5 — that's
> a test. And the state machine only damps de-escalation: hysteresis, dwell and cooldown stop
> the siren flapping, while escalation is never suppressed. A system that cries wolf gets
> switched off, and a switched-off system detects nothing.

**"Why not use ML?"**
> We do, where it's honest — retrieval over a curated Hugging Face corpus, matching the live
> signature to documented events. What we don't do is claim a trained predictor, because with
> ten labelled incidents anything trained would be memorisation wearing a lab coat.

**"What would you build next?"**
> Validation first, against a real historical catalogue. Then dedicated ground-motion sensors
> instead of USGS, official DHM/CWC gauge feeds instead of gridded forecasts, and the actual
> last mile — loudspeaker and SMS integration. Those are in the README as roadmap, and not
> built, because I'd rather show you five things that work than fifteen that don't.

---

## If something breaks

| Symptom | Fix |
|---|---|
| No audio | Click **Test audio output** — browsers need a user gesture first |
| Dashboard blank | `make demo` again; check port 8000 is free |
| Map is empty rectangles | Tile CDN is blocked. Expected. The numbered markers and river network still carry it — say *"no basemap on this network, the geography is the river graph"* |
| Nothing escalates | You're on **Live feeds** and it's a quiet day. Switch to a scenario, or hit **Trigger alert pipeline** |
| Siren won't stop | **Acknowledge**, or press Escape |
| Everything is on fire | **Trigger alert pipeline** on any zone works with no network, no scenario and no state. It is the one-button fallback demo. |
