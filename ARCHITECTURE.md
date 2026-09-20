# Architecture

How Prahari is put together, and why each decision was made that way. Every choice
below traces back to one of three constraints: **it must be explainable to a district
officer**, **it must not fail on venue wifi**, and **it must not claim more than it does**.

---

## 1. System overview

```mermaid
flowchart TB
  subgraph EXT["External sources — all free, none require a key"]
    direction LR
    OM["<b>Open-Meteo Forecast</b><br/>precipitation, soil moisture<br/>72h past + 6h ahead"]
    GL["<b>Open-Meteo Flood</b><br/>ECMWF GloFAS<br/>modelled river discharge"]
    US["<b>USGS FDSN event</b><br/>M≥1.0, regional bbox<br/>24h rolling"]
    HFS["<b>Hugging Face</b><br/>dataset hub + inference router"]
  end

  subgraph ADP["Ingestion layer — backend/sources/"]
    direction TB
    BASE["<b>Source base</b><br/>TTL cache · circuit breaker<br/>never raises, never blocks"]
    WSRC["WeatherSource<br/><i>one batched call for 10 zones</i>"]
    DSRC["DischargeSource"]
    SSRC["SeismicSource"]
    HSRC["HuggingFaceSource"]
    REPL["<b>ReplayCursor</b><br/>recorded frames in the<br/>identical payload shape"]
  end

  subgraph ENGINE["Risk engine — backend/engine/ · deterministic"]
    direction TB
    HYD["<b>hydro.py</b> — Channel A<br/>5 weighted terms<br/>saturating curve vs IMD thresholds"]
    GEO["<b>geo.py</b> — Channel B<br/>4 weighted terms<br/>× multiplicative proximity gate"]
    CASC["<b>fusion.py :: compute_cascades</b><br/>walk basin graph<br/>per-reach travel time → ETA"]
    FUSE["<b>fusion.py :: fuse</b><br/>max + bounded cross-term<br/>+ confirmed-detachment floor"]
    LEG["<b>legacy counterfactual</b><br/>Channel A alone"]
    ANA["<b>analogue.py</b><br/>9-D cosine vs corpus"]
    EXP["<b>explain.py</b><br/>plain language + PA script"]
  end

  subgraph DEC["Decision — backend/engine/state.py"]
    SM["<b>AlertStateMachine</b><br/>escalate instantly<br/>de-escalate only after<br/>hysteresis + dwell"]
  end

  subgraph DEL["Delivery — backend/alerts/"]
    DISP["<b>dispatch_all</b><br/>concurrent fan-out<br/>one channel failing blocks none"]
  end

  subgraph SINK["Channels"]
    direction LR
    SIR["Browser siren<br/><i>Web Audio, synthesised</i>"]
    TTS["Speech synthesis<br/><i>PA relay script</i>"]
    SQL["SQLite alert log"]
    WSK["WebSocket push"]
    WHK["Webhook <i>(opt)</i>"]
    WAP["WhatsApp <i>(opt)</i>"]
  end

  UI["<b>Dashboard</b> — frontend/<br/>map · zones · trend · why · log<br/><i>no build step, vendored libs</i>"]

  OM --> WSRC; GL --> DSRC; US --> SSRC; HFS --> HSRC
  BASE -.- WSRC & DSRC & SSRC & HSRC
  WSRC & DSRC --> HYD
  SSRC --> GEO
  REPL -.->|offline · rehearsal| HYD & GEO
  GEO --> CASC --> FUSE
  HYD --> FUSE
  HYD --> LEG
  HYD & GEO --> ANA
  HSRC --> ANA
  FUSE & LEG --> SM
  FUSE --> EXP --> DISP
  SM --> DISP
  DISP --> SIR & TTS & SQL & WSK & WHK & WAP
  WSK --> UI
  ANA --> UI
```

---

## 2. The tick loop

One pass through `Orchestrator.tick()` produces one complete `SystemState`, which is what
both the REST snapshot and the WebSocket push serve. **Live and replay share this path
exactly** — nothing in the scoring knows or cares where a number came from. That is what
makes the stage demo a legitimate rehearsal rather than a puppet show.

```mermaid
sequenceDiagram
  autonumber
  participant L as poll_forever
  participant O as Orchestrator
  participant S as Sources / Replay
  participant E as Engine
  participant M as State machine
  participant D as Dispatcher
  participant W as WebSocket clients

  L->>O: tick(advance=True)
  O->>O: advance replay cursor (if playing)
  O->>S: gather inputs (asyncio.gather)
  alt live reachable
    S-->>O: weather · discharge · seismic
  else unreachable
    S-->>O: cached payload, or auto-fallback to replay
  end

  rect rgb(238,244,252)
  Note over O,E: Pass 1 — independent channels
  loop each of 10 zones
    O->>E: score_hydro(zone, weather, discharge)
    O->>E: score_geo(zone, seismic)
  end
  end

  rect rgb(240,248,242)
  Note over O,E: Pass 2 — propagate upstream mass movement
  O->>E: compute_cascades(geo_scores)
  E-->>O: {zone → CascadeAlert(eta, path, source)}
  end

  rect rgb(252,244,238)
  Note over O,E: Pass 3 — fuse, explain, counterfactual
  loop each zone
    O->>E: build_zone_risk(...) → fused + legacy + blindspot
    O->>E: find_analogues(...)
    O->>E: build_explanation(...)
  end
  end

  O->>O: persist score history (SQLite)

  rect rgb(250,240,240)
  Note over O,M: Pass 4 — decide and deliver
  loop each zone
    O->>M: evaluate(zone, score)
    M-->>O: level + should_notify
    opt should_notify
      O->>D: dispatch_all(record)
      D-->>O: delivered channel list
      O->>W: push {type: alert}
    end
  end
  end

  O->>W: push {type: state}
```

**Why four passes and not one.** Cascade cannot be computed until every zone's geo score
exists, and fusion cannot run until cascade is known. Collapsing the passes would mean a
zone's inherited threat depended on iteration order — a non-deterministic warning system,
which is disqualifying.

---

## 3. Channel fusion — the central decision

```mermaid
flowchart LR
  A["Channel A<br/>HYDRO<br/><b>0</b>"] --> MAX{{"max()"}}
  B["Channel B<br/>GEO<br/><b>72</b>"] --> MAX
  A --> MIN{{"min()"}}
  B --> MIN
  MAX -->|72| SUM((" + "))
  MIN -->|0| X["κ · (min/100) · (max/100) · 100<br/>κ = 0.35"] --> SUM
  SUM -->|72| FLOOR["confirmed-detachment floor<br/><i>distance decays the peak,<br/>not the certainty</i>"]
  FLOOR --> R["<b>R = 72 · WARNING</b>"]

  A -.-> MEAN["a mean would report<br/><b>36 · NORMAL</b>"]
  B -.-> MEAN
  MEAN -.-> BAD["☠ this is how the<br/>previous system stayed quiet"]

  style BAD fill:#fde8e8,stroke:#d03b3b,color:#7a1010
  style R fill:#e8f2fd,stroke:#2a78d6,color:#0d366b
```

Three properties this gives us, all of which are tested:

1. **A silent channel can never dilute a loud one.** `test_fusion_never_dilutes_a_loud_channel`
2. **Two moderate signals outrank one moderate signal.** `test_fusion_amplifies_two_moderate_channels`
3. **The result is bounded.** `test_fusion_is_bounded`

---

## 4. Cascade propagation

Channel B fires at the *source*. The people at risk are *downstream*. The bridge between
those two facts is the basin reach graph in `data/zones.json`.

```mermaid
flowchart LR
  H["Langtang headwall<br/>GEO 88 · EMERGENCY"]
  H -->|"22 km · 14.0 m/s<br/><b>26 min</b>"| R["Rasuwa<br/>43,300"]
  R -->|"41 km · 9.0 m/s<br/><b>1h 42m</b>"| N["Nuwakot<br/>277,500"]
  N -->|"33 km · 6.5 m/s<br/><b>3h 06m</b>"| D["Dhading<br/>325,700"]
  D -->|"38 km · 5.0 m/s<br/><b>5h 13m</b>"| G["Gorkha<br/>271,100"]
  G -->|"52 km · 3.5 m/s<br/><b>9h 20m</b>"| C["Chitwan<br/>719,900"]

  style H fill:#fde8e8,stroke:#d03b3b,color:#7a1010
```

**Travel time is summed per reach, not basin-wide.** A debris flood decelerates sharply as
the valley opens — 14 m/s in the gorge, 3.5 m/s across the Chitwan floodplain. A single
average velocity would put Chitwan's arrival hours off, and an arrival time that is wrong
is worse than no arrival time at all, because people plan around it.

**Score transfer:** `transferred = source_geo × 0.85 × exp(−km / 260)`.

**Then the floor.** Once the source score confirms a detachment (≥60), distance is not
allowed to drop a downstream zone below WATCH — or below WARNING within an hour of arrival.
Attenuation is a statement about peak discharge. It is not a statement about whether the
water is coming.

---

## 4b. The prediction layer

Detection answers "what is happening". Prediction answers "what happens next" — and the two
must never be confused on screen, because they carry different obligations.

```mermaid
flowchart TB
  subgraph IN["Inputs"]
    NWP["Open-Meteo forecast<br/>precipitation + temperature<br/><i>ECMWF / GFS output</i>"]
    CAT["USGS catalogue<br/><i>mainshock magnitude</i>"]
    ZON["Zone terrain<br/><i>slope, elevation, thresholds</i>"]
  end

  subgraph FC["Forecasters — each a published method"]
    F1["<b>Flood</b><br/>NWP threshold exceedance<br/>spread widens with lead time"]
    F2["<b>Aftershock</b><br/>Reasenberg-Jones 1989<br/>Omori-Utsu decay, Poisson"]
    F3["<b>Landslide</b><br/>Caine 1980 intensity-duration<br/><i>steep terrain only</i>"]
    F4["<b>Heat</b><br/>IMD criteria vs forecast max"]
  end

  DEC{"probability ≥<br/>alarm threshold<br/>(default 0.90)?"}
  ALARM["<b>FORECAST ALARM</b><br/>raised without waiting for<br/>conditions to cross a threshold"]
  SHOW["Probability card<br/>+ method + arithmetic"]

  DET["<b>DETECTED</b> card<br/>arrival countdown, no percentage<br/><i>'cannot be forecast,<br/>only detected'</i>"]
  CASC["Confirmed cascade<br/>from Channel B"]

  NWP --> F1 & F3 & F4
  CAT --> F2
  ZON --> F1 & F3 & F4
  F1 & F2 & F3 & F4 --> DEC
  DEC -->|yes| ALARM
  DEC -->|no| SHOW
  CASC --> DET

  style ALARM fill:#fde8e8,stroke:#d03b3b,color:#7a1010
  style DET fill:#fff4e6,stroke:#f07316,color:#7a3a00
```

Three decisions worth defending:

1. **The alarm threshold is a setting, not a constant.** It is the number that decides when
   people are told to move, so it belongs in configuration where an operating authority can
   own it — not buried in engine code.

2. **Forecast alarms fire before conditions do.** A 96% flood probability 24 hours out is
   more actionable than a threshold crossing measured after the fact. The state machine's
   cooldown still rate-limits them, so a sustained outlook does not re-alarm every tick.

3. **Refusing to forecast is part of the method.** A glacier collapse in motion has no
   probability — it is happening. Showing it as "2% flood" next to a real 96% would teach an
   operator to distrust both numbers. It gets a DETECTED card instead, and the UI states
   plainly that this hazard class can only be detected, never predicted. Every honest
   forecasting system needs a way to say "not this one", and most do not have one.

---

## 4c. Multi-hazard world view

```mermaid
flowchart LR
  EO["NASA EONET v3<br/>curated worldwide events<br/><i>no severity</i>"]
  GD["GDACS<br/>official alert levels<br/><i>Green / Orange / Red</i>"]
  US["USGS FDSN<br/>earthquake catalogue"]

  NORM["Normalisers<br/>→ one event shape"]
  DEDUP["De-duplicate<br/>(hazard, lat≈0.1°, lon≈0.1°)<br/><i>GDACS and USGS both carry<br/>the big earthquakes</i>"]
  AGE["Age filter<br/>30 days<br/><i>undated events KEPT</i>"]
  MAP["World map<br/>9 categories · filter chips<br/>glyph + label + hue"]

  EO & GD & US --> NORM --> DEDUP --> AGE --> MAP
```

The world feeds are **display and situational awareness only**. They never feed the zone risk
engine: a GDACS "Red" cyclone and an M6 earthquake both normalise onto 0–100, but those
numbers do not mean the same thing, and mixing them into a scored risk would be a category
error. Ranking and rendering is all they are used for.

Polled on a slower cadence than the zone engine — these feeds update in hours, not seconds.
They fall back to a bundled snapshot (`data/snapshots/`) when unreachable, clearly marked as
a snapshot, because a world map that silently shows month-old pins as live would be exactly
the dishonesty this project argues against.

---

## 4d. Language and voice

```mermaid
flowchart TB
  ALERT["Alert raised"]
  TPL["Template lookup<br/>data/i18n/languages.json"]
  VAL["<b>Placeholder validation</b><br/>every language must carry the<br/>exact placeholder set of English"]
  ALL["Render ALL 11 languages<br/><i>attached to the alert record</i>"]

  subgraph DELIV["Delivery"]
    UI["Dashboard<br/>switches instantly, no round trip"]
    TTS["Speech synthesis<br/>BCP-47 per language"]
    WH["Webhook<br/>PA / SMS gateway gets every language"]
  end

  FB["Voice fallback<br/><i>bho, mai → hi-IN</i><br/>declared, never silent"]

  ALERT --> TPL --> VAL --> ALL --> UI & TTS & WH
  TTS -.no engine for dialect.-> FB

  style VAL fill:#e8f2fd,stroke:#2a78d6,color:#0d366b
```

**Why templates rather than machine translation at send time.** A life-safety message must
be deterministic, auditable and available offline. A translation service in the alert path
is a dependency that fails exactly when the network does.

**Why placeholders are validated at load.** A translation that silently dropped `{eta}`
would produce a fluent, grammatical sentence missing the only number that matters — and that
failure is invisible to anyone who does not read the language. So it is asserted, not
trusted, in both `i18n.py` and `test_i18n.py`.

**Why all languages ship with every alert.** A PA controller in one district and an SMS
gateway in another need different languages from the same event. Sending all of them costs
a few kilobytes and removes a round trip from the critical path.

**Honesty about quality.** These strings are machine-assisted and unreviewed. The system
reports `UNREVIEWED_MACHINE_ASSISTED` through `/api/health` and `/api/languages`, and says so
in the data file and the README. Structural validity is not fluency, and a warning that
reads oddly in Maithili is a warning people may not act on.

---

## 4e. The situation assistant

```mermaid
flowchart TB
  Q["Question<br/><i>typed or spoken</i>"]
  SR["SpeechRecognition<br/><i>browser-native, nothing uploaded</i>"]
  INT["Intent match<br/>status · safety · action · eta ·<br/>why · forecast · hazards<br/><i>keywords in 11 languages<br/>+ romanised forms</i>"]
  RULES["<b>Tier 1 — rules</b><br/>answers from the SAME translated<br/>safety templates the sirens use<br/><i>offline, no token, every language</i>"]
  LLM["<b>Tier 2 — HF inference</b><br/>free-form only, grounded in a<br/>state snapshot, forbidden from<br/>inventing numbers"]
  OUT["Answer + speech<br/><i>read back in the chosen language</i>"]

  Q --> INT
  SR --> Q
  INT -->|specific intent| RULES --> OUT
  INT -->|open-ended AND token set| LLM --> OUT
  LLM -.unavailable.-> RULES

  style RULES fill:#e6f6ed,stroke:#0a8f0a,color:#064506
```

The tier order is the whole design. Someone asking *"should I leave"* must not depend on an
inference API being reachable, so that answer comes from a template that is already on disk.
The model only handles questions the rules tier has no specific intent for, and it can never
change a risk number — it reads state out loud, it does not decide.

Romanised keywords ("kya karu", "kab") are in the intent table because people type
Devanagari-language queries in Latin script constantly, and an assistant that only matches
native script would fail most real queries.

---

## 5. Alert state machine

```mermaid
stateDiagram-v2
  direction LR
  [*] --> NORMAL
  NORMAL --> ADVISORY: score ≥ 40
  ADVISORY --> WATCH: ≥ 55 · <b>notify</b>
  WATCH --> WARNING: ≥ 70 · <b>notify</b>
  WARNING --> EMERGENCY: ≥ 85 · <b>notify</b>

  EMERGENCY --> WARNING: < 77 AND held ≥ 90s
  WARNING --> WATCH: < 62 AND held ≥ 90s
  WATCH --> ADVISORY: < 47 AND held ≥ 90s
  ADVISORY --> NORMAL: < 32 AND held ≥ 90s

  note left of NORMAL
    Escalation is immediate and
    never suppressed.
    Every damping mechanism
    here is one-way.
  end note
```

Three mechanisms, all applying **only to de-escalation**:

| Mechanism | Value | Purpose |
|---|---|---|
| Hysteresis | 8 pts below the band edge | stops the siren flapping around a threshold |
| Minimum dwell | 90 s | stops a single quiet sample clearing an alert |
| Cooldown | 300 s | suppresses re-notifying an unchanged sustained level |

A warning system that cries wolf gets switched off, and a switched-off system has a
detection rate of zero. Damping is a safety feature — but damping an *escalation* would
be lethal, which is why the asymmetry is absolute.

---

## 6. Degradation model

The system has four operating modes and always tells you which one it is in, in the
**Feed health** panel.

```mermaid
flowchart TB
  START["tick()"] --> Q1{"source mode"}
  Q1 -->|replay| RP["<b>REPLAY</b><br/>bundled frames<br/><i>guaranteed offline</i>"]
  Q1 -->|live / auto| FETCH["fetch with timeout"]
  FETCH --> Q2{"succeeded?"}
  Q2 -->|yes| LIVE["<b>LIVE</b>"]
  Q2 -->|no, cache warm| CACHE["<b>CACHE</b><br/>last good payload<br/>confidence downgraded"]
  Q2 -->|no, cache cold, auto| RP
  Q2 -->|no, cache cold, live| DOWN["<b>DOWN</b><br/>zone marked inputs_stale<br/>shown on the dashboard"]

  LIVE --> BRK{"3 consecutive<br/>failures?"}
  BRK -->|yes| OPEN["breaker OPEN 120s<br/>stop hammering a dead API"]
  OPEN -->|probe| FETCH

  style RP fill:#ede9fd,stroke:#4a3aa7,color:#241a5e
  style LIVE fill:#e6f6ed,stroke:#0a8f0a,color:#064506
  style DOWN fill:#fde8e8,stroke:#d03b3b,color:#7a1010
```

A degraded feed is never silently hidden. `ChannelScore.confidence` drops to 0.45 on stale
input and the zone carries `inputs_stale`. An early-warning system that cannot distinguish
*"nothing is happening"* from *"I cannot see"* is dangerous, and that ambiguity is close to
what happened at Langtang when the upstream stations were destroyed.

---

## 7. Frontend

No build step, no framework, no bundler. Plain ES modules, Leaflet and Chart.js **vendored
into the repo** (404 KB) rather than pulled from a CDN.

| Module | Responsibility |
|---|---|
| `api.js` | fetch helpers, WebSocket with backoff reconnect, level + hazard tokens |
| `map.js` | Leaflet; dual mode — numbered regional zones, categorised world hazards |
| `charts.js` | Chart.js; fused vs legacy vs both channels, band markers, table view |
| `siren.js` | Web Audio two-tone sweep + multilingual speech synthesis with voice fallback |
| `assistant.js` | chat panel, SpeechRecognition input, read-aloud output |
| `app.js` | state → DOM, hero tiles, forecast cards, countdown interpolation, controls |

Three deliberate decisions:

- **Vendored libraries.** A CDN is a dependency on someone else's uptime and on the venue's
  firewall. 404 KB in the repo removes both.
- **Numbered map markers, not name labels.** Name labels were tried and collide badly — the
  six Trishuli zones sit within 186 km, so at any zoom that also shows Assam the labels
  overlap into mush. Numbers stay legible at every zoom, and the numbered zone list is the
  legend. The map also degrades gracefully with no basemap: the river network carries the
  geography. **No national borders are drawn** — this is a cross-border basin view, and
  hand-drawn boundaries would be both inaccurate and unnecessary.
- **Client-side countdown interpolation.** The server sends an absolute arrival timestamp;
  the browser ticks every second between polls. A countdown that jumps in 20-second steps
  looks broken, and this one is the emotional core of the demo.

### Accessibility

Risk level is **never carried by colour alone** — every band ships with its name, a numeric
score 0–100, and a glyph. The chart has a table view. Series are direct-labelled at the line
end as well as in the legend. `prefers-reduced-motion` disables the siren flash. The status
palette follows the green/yellow/orange/red convention IMD and district operators already
read; its worst adjacent pair measures ΔE 12.8 under deuteranopia simulation, above the
CVD floor — the normal-vision separation sits marginally under the usual target, which is
inherent to that four-hue severity ramp and is why the label-plus-number pairing is
mandatory rather than decorative.

---

## 8. Data model

```mermaid
erDiagram
  BASIN ||--o{ REACH : "ordered head→mouth"
  REACH }o--|| ZONE : from
  REACH }o--|| ZONE : to
  ZONE ||--o{ WARD : contains
  ZONE ||--|| ZONERISK : "scored each tick"
  ZONERISK ||--|| CHANNELSCORE : hydro
  ZONERISK ||--|| CHANNELSCORE : geo
  CHANNELSCORE ||--o{ CONTRIBUTION : "named, weighted terms"
  ZONERISK ||--o| CASCADEALERT : "inherited threat"
  ZONERISK ||--o{ ANALOGUE : "retrieved"
  ZONERISK ||--o{ ALERTRECORD : raises
  ALERTRECORD ||--o{ DISPATCH : "delivered to"

  ZONE {
    string id PK
    float lat
    float lon
    int population
    float terrain_factor "scales published thresholds"
    float vulnerability "exposure multiplier 0.80-1.20"
    bool geo_watch "in the ground-motion watch set"
    json cryosphere "glacier area, lake count"
  }
  CONTRIBUTION {
    string key
    float raw "the measured value"
    float normalised "0-1 after the curve"
    float weight "fixed, published"
    float points "what reached the score"
    string detail "the sentence shown in the UI"
  }
  CASCADEALERT {
    string source_zone_id
    float distance_km
    float eta_seconds
    float source_score
    bool floored
  }
```

`Contribution` is the load-bearing type. Every number on screen is one of these, carrying
its raw measurement, the threshold it was compared against, its fixed weight, and a
human-readable sentence. **Explainability is a data-structure decision, not a UI feature** —
which is why it cannot rot as the UI changes.

---

## 9. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | complete current system state |
| GET | `/api/zones` | zone + basin registry with thresholds |
| GET | `/api/zone/{id}/history` | score history for the trend chart |
| GET | `/api/alerts` | alert log |
| GET | `/api/scenarios` | available scenarios + playback position |
| GET | `/api/health` | per-source health, breaker state, HF status, corpus provenance |
| GET | `/api/methodology` | **the entire scoring formula, as data** |
| POST | `/api/scenario/{id}` | switch data source |
| POST | `/api/playback/{play\|pause\|step\|restart\|seek}` | replay control |
| POST | `/api/engine/{dual\|legacy}` | switch to the counterfactual engine |
| POST | `/api/simulate/{zone}` | fire the alert pipeline on demand |
| GET | `/api/hazards` | the 9-category hazard taxonomy with glyphs |
| GET | `/api/global-events` | live worldwide events, filterable by category |
| GET | `/api/forecasts` | every zone forecast with its method and basis |
| GET | `/api/languages` | supported languages, voice tags, review status |
| POST | `/api/language/{code}` | set the alert language |
| GET | `/api/assistant/starters` | suggested questions |
| POST | `/api/assistant` | ask a question, get a localised answer |
| WS | `/ws` | push `state` and `alert` frames |

`/api/methodology` exists because "is that hardcoded?" is the first question a technical
judge asks. The answer is `curl localhost:8000/api/methodology` — every weight, curve,
anchor and band edge, served from the same constants the engine imports.

---

## 10. Testing

40 tests. They are written as **assertions of the claims the pitch makes**, so that if a
sentence in the README becomes false, CI says so:

| Test | Claim it defends |
|---|---|
| `test_fusion_never_dilutes_a_loud_channel` | the central design argument |
| `test_geo_ignores_distant_tectonic_quake` | the false-positive guard |
| `test_langtang_blindspot_appears_after_collapse` | the headline number |
| `test_legacy_engine_misses_langtang_entirely` | the stage toggle |
| `test_langtang_stays_dry_throughout` | the argument is not circular |
| `test_assam_both_engines_agree` | we are not overselling against legacy systems |
| `test_cascade_gives_rasuwa_usable_lead_time` | 26 minutes is real |
| `test_escalation_is_immediate` | damping is one-way |
| `test_basin_graph_is_acyclic` | no zone is downstream of itself |
| `test_aftershock_matches_published_behaviour` | the Omori-Utsu maths is right, not just plausible |
| `test_flood_probability_decays_with_lead_time` | a 48h call is less certain than a 6h one |
| `test_landslide_only_forecast_on_steep_terrain` | we refuse to forecast where it would be noise |
| `test_every_language_preserves_every_placeholder` | no alert can silently lose its `{eta}` |
| `test_review_status_is_declared_honestly` | translations do not claim to be reviewed |
| `test_messaging_app_channel_is_gone` | the unreliable channel stayed removed |

`test_langtang_stays_dry_throughout` is the one that matters most for integrity: it asserts
that no rain ever creeps into the Langtang scenario. Without it, the whole demonstration
could quietly become circular.
