# Methodology

The complete scoring method, its anchors, and its limits. Everything here is also served
as machine-readable JSON at **`GET /api/methodology`**, from the same constants the engine
imports — so this document cannot drift from the code without the endpoint disagreeing.

**There are no fitted parameters anywhere in this system.** Every weight is a fixed
published constant. Nothing was trained, so nothing can silently drift, and any term can be
recomputed by hand.

---

## 1. The normalisation curve

Every raw measurement becomes a 0–1 term through one function:

```
n(x, T) = 1 − exp(−1.6094 · x / T)
```

where `T` is the published threshold for that measurement in that zone.

The constant is `−ln(1 − 0.80)`, chosen so that **x = T maps to exactly 0.80**.

Why 0.80 and not 1.0: real events overshoot published thresholds by multiples. Kedarnath
and the Assam cloudbursts both ran far past "extremely heavy". If crossing the threshold
saturated the term, the score could no longer tell *heavy* from *catastrophic* — and the
difference between those two is the difference between a watch and an evacuation.

Properties: monotonic, bounded, never clips, smooth. A doubling of rainfall above the
threshold still moves the score (0.80 → 0.96).

---

## 2. Channel A — hydrological

### Terms and weights

| Term | Weight | Measured | Threshold anchor |
|---|---:|---|---|
| `rain_1h` | 0.22 | precipitation, last hour | IMD cloudburst **50 mm/h** × terrain factor |
| `rain_24h` | 0.28 | accumulation, last 24 h | IMD *very heavy* **115.6 mm/24h** × terrain factor |
| `trend` | 0.15 | last 6 h minus previous 6 h | 35 % of the 24 h threshold |
| `discharge` | 0.23 | GloFAS discharge ÷ seasonal mean | **2.5×** normal anchors a major flood |
| `saturation` | 0.12 | 72 h accumulation + soil moisture | 2.5 × the 24 h threshold |

Weights sum to 1.00. Accumulation and discharge carry the most because they are the two
variables official flood thresholds are actually *written against*; intensity and trend earn
their weight by providing lead time that accumulation alone cannot.

**Only rising trends contribute.** A falling trend contributes zero, never a negative — an
easing storm does not reduce the danger from water already in the channel.

### Published threshold basis

India Meteorological Department 24-hour rainfall categories:

| Category | mm / 24 h |
|---|---|
| Heavy | 64.5 – 115.5 |
| Very heavy | 115.6 – 204.4 |
| Extremely heavy | ≥ 204.5 |

Nepal's DHM uses closely comparable bands. We anchor on *very heavy* (115.6 mm) because
that is the category at which district response is typically activated.

### Terrain factor

The same rainfall is not the same flood. A steep glacial catchment converts far more of its
rain into peak discharge, and does it far faster, than a flat alluvial plain.

| Terrain | Factor | Effective 24 h threshold |
|---|---:|---:|
| High-mountain glacial | 0.55 | 64 mm |
| Mountain valley | 0.65 | 75 mm |
| Mid-hill valley | 0.78 – 0.85 | 90 – 98 mm |
| Terai / alluvial plain | 1.00 | 116 mm |

### Exposure multiplier

```
score_A = (Σ points) × (0.80 + 0.40 × vulnerability)
```

Bounded 0.80–1.20. Identical rainfall is not an identical emergency in a dense riverside
bazaar and an empty high valley. The bounds are deliberately tight: exposure *shades* a
hazard score, it must never be able to invent one.

---

## 3. Channel B — ground motion

### What it does and does not do

**It does not predict earthquakes.** It recognises, in a seismic catalogue, the signature
of a mass already in motion: a shallow, moderate, non-tectonic release inside a glaciated
or steeply-jointed catchment.

The Langtang collapse registered seismically but was not a tectonic earthquake. A monitoring
system filtering at the usual M4.5 "newsworthy earthquake" floor discards exactly that event
class. **We query at M1.0 and classify instead of filtering.**

### Terms and weights

| Term | Weight | Curve |
|---|---:|---|
| `energy` | 0.28 | `(M − 1.0) / 4.5`, clamped |
| `shallow` | 0.22 | `exp(−depth_km / 8)` |
| `signature` | 0.34 | composite, below |
| `cluster` | 0.16 | `n(events_1h, 4)` |

### The mass-movement signature

The decisive term. Additive components, clamped to 1.0:

| Indicator | Contribution | Reasoning |
|---|---:|---|
| M in 1.8 – 4.8 | +0.30 | the slope-failure window; above it, a real tectonic event |
| Depth ≤ 10 km | +0.30 × (1 − d/10) | mass detaching is a surface process |
| Glacier ice upslope | +0.25 | ice-rock avalanche and GLOF precondition |
| Steep catchment (no ice) | +0.12 | slope instability without a cryospheric trigger |
| Catalogued as non-earthquake | +0.15 | the catalogue itself says it is not tectonic |

### The proximity gate — multiplicative, never additive

```
score_B = (Σ points) × exp(−distance_km / 45)
```

This is the false-positive guard, and it is the reason Channel B can be trusted enough to
leave switched on. An M5.4 two hundred kilometres away scores **below 5**. If proximity were
an additive term instead, every regional earthquake would nudge every watched zone upward,
and within a week an operator would mute the channel.

Verified by `test_geo_ignores_distant_tectonic_quake`.

Zones outside the geo-watch set (low-relief, no upslope ice or unstable mass) score a hard
zero on this channel. Risk there arrives by river, not by slope.

---

## 4. Fusion

```
R = min(100, max(A, B) + κ · (min(A,B)/100) · (max(A,B)/100) · 100)      κ = 0.35
```

**Why not a mean.** With A = 0 and B = 72, a mean reports 36 — NORMAL. That is not a
hypothetical: it is the arithmetic shape of how a multi-input system talks itself out of an
alarm. The maximum guarantees a silent channel can never dilute a loud one. The bounded
cross-term still rewards corroboration: 58 and 61 fuse to 73.4, higher than either alone.

**Why not a sum.** A sum would saturate on any two moderate readings and lose all resolution
in the range where decisions are actually made.

### Confirmed-detachment floor

When an upstream source score ≥ 60, every zone in the flow path is floored at **WATCH**, and
at **WARNING** within one hour of estimated arrival.

Spatial decay models the attenuation of *peak discharge*. It does not model the *certainty*
that water is coming. Those are different quantities, and conflating them is how 719,900
people in Chitwan end up at NORMAL with a confirmed surge inbound. When the floor is applied
the UI says so explicitly, in the explanation text and in the fusion note — a level set by
policy rather than by measurement must never look like a measurement.

---

## 5. Cascade timing

```
eta_total = Σ_reaches (distance_km × 1000 / debris_velocity_ms)
transferred = source_geo × 0.85 × exp(−cumulative_km / 260)
```

Velocities are assigned per reach by gradient class:

| Gradient | m/s | Rationale |
|---|---:|---|
| Steep gorge | 9 – 14 | confined channel, high gradient |
| Moderate | 5 – 6.5 | widening valley |
| Low / floodplain | 1.6 – 3.5 | energy dissipating across the plain |

Debris flows are documented in the 5–20 m/s range in steep confined channels. The reported
detail that floodwaters reached the Gyirong crossing in about seven minutes is consistent
with the upper end of that range in the steepest reach.

**These are order-of-magnitude estimates, not a hydraulic model.** They are good enough to
tell a district officer "tens of minutes" versus "several hours", which is the decision that
matters. They are *not* good enough to plan a road closure to the minute, and the UI should
never be read as if they were.

---

## 6. Alert bands and the state machine

| Level | Score | Action |
|---|---:|---|
| NORMAL | < 40 | routine monitoring |
| ADVISORY | 40 | inform ward focal points |
| WATCH | 55 | alert focal points, pre-position teams, warn riverside households |
| WARNING | 70 | activate public address, move people off the floodplain |
| EMERGENCY | 85 | immediate evacuation; assume no further warning time |

Damping applies to **de-escalation only**: hysteresis 8 points, minimum dwell 90 s,
re-notification cooldown 300 s. Escalation is immediate and can never be suppressed.

---

## 7. Analogue retrieval

Cosine similarity between the live 9-vector and each corpus incident, with
mechanism-discriminating dimensions weighted up:

```
rain_24h 1.0 · rain_intensity 0.9 · discharge 1.0 · seismic_energy 1.25
shallowness 1.25 · mass_movement_signature 1.6 · clustering 1.0
cryosphere 1.1 · onset_speed 1.2
```

Without that weighting every monsoon event looks alike and drowns out the rarer, deadlier
signatures — which are precisely the ones an operator has never seen before and most needs
the precedent for.

Returns the top 3 above a 0.55 floor; returns nothing when the live vector is near zero,
because an analogue for "nothing is happening" is noise.

**This is retrieval, not prediction.** No claim is made that the matched incident will
recur. The claim is only that the *measured signature* resembles a documented one, and
here is what that one did.

---

## 8. Known limitations

Stated plainly, because a warning system that oversells itself is the failure mode this
project is about.

1. **Rainfall is a gridded forecast, not a gauge.** Open-Meteo interpolates; a real
   deployment needs DHM/CWC station data. Convective cloudbursts are exactly what gridded
   products smooth out — a known weakness for the Assam mechanism.
2. **GloFAS is modelled discharge, not a river gauge**, on a coarse grid, and it is
   unreliable on small tributaries like the Dikhow.
3. **USGS catalogues with a delay and a detection floor.** The Langtang-class signal sits
   near that floor. Production needs a dedicated regional ground-motion network; USGS is a
   proof-of-concept for the channel, not an operational source for it.
4. **Cascade timing assumes a clear channel.** Landslide dams, channel avulsion and
   temporary impoundments can delay a surge by hours and then release it far larger. Jure
   2014 is in the corpus precisely as that counter-example.
5. **The corpus has 10 incidents.** It is a retrieval set, far too small to train on, and
   curated to span failure modes rather than to be a complete regional catalogue.
6. **Feature vectors are expert-assigned**, derived from published event descriptions rather
   than recovered instrument records. They encode a qualitative signature.
7. **Thresholds are regional.** IMD categories and these terrain factors apply to the
   Himalaya and the Brahmaputra basin. Do not assume they transfer.
8. **2026 figures are as reported**, carried with `confidence: reported` and a `source_note`.
   Verify against final official assessments before public use.
9. **The scenario replays are authored frames**, not simulated physics. The arrival times
   come from the real reach graph; the rainfall and seismic values were written by hand to
   reproduce the documented event shape.
10. **No validation against a historical event catalogue.** We have not measured a hit rate
    or a false-alarm rate, because doing that honestly needs a labelled multi-year archive
    and instrument records we do not have. **This is the single most important piece of
    missing work**, and no deployment decision should be made without it.

---

## 9. Reproducing any number on screen

Every displayed figure is traceable:

```bash
curl localhost:8000/api/methodology | jq        # every weight, curve and band edge
curl localhost:8000/api/state | jq '.zones[1].hydro.contributions'
curl localhost:8000/api/zones | jq '.zones[1].rain_24h_threshold_mm'
```

Each `Contribution` carries its raw measurement, the threshold it was compared against, its
normalised value, its fixed weight, the points it contributed, and the sentence shown in the
UI. Multiply `normalised × weight × 100` and you get `points`. Sum the points, apply the
exposure multiplier, and you get the channel score.

Nothing is hidden, and nothing is generated by a model.
