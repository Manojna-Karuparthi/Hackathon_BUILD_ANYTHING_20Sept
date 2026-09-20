---
license: cc-by-4.0
task_categories:
  - tabular-classification
  - feature-extraction
language:
  - en
tags:
  - disaster-response
  - early-warning
  - floods
  - glacial-hazards
  - himalaya
  - climate
size_categories:
  - n<1K
pretty_name: Himalayan & Brahmaputra Geohazard Incident Corpus
configs:
  - config_name: default
    data_files:
      - split: train
        path: incidents.jsonl
---

# Himalayan & Brahmaputra Geohazard Incident Corpus

A small, hand-curated corpus of documented flood and mass-movement disasters in
Nepal and north-east India, annotated with **why the early warning failed** and
encoded into a shared nine-dimensional signature space.

It exists because of a specific gap. Most flood datasets record *what the water
did*. Almost none record *what the monitoring system was listening to* — and
that is the variable that decides whether people get warned.

## Why this corpus

Of the 10 incidents here, 7 produced a detectable seismic signal and 5 were not
rainfall-driven at all. A warning system calibrated purely on rainfall is
structurally blind to that second group, which includes the deadliest events in
the set.

## Fields

| Field | Type | Description |
|---|---|---|
| `incident_id` | string | Stable identifier |
| `title`, `date`, `country`, `region` | string | Event identity |
| `mechanism` | string | Physical mechanism (e.g. `ice_rock_avalanche_debris_flood`) |
| `onset` | string | `minutes` / `hours` / `days` — the warning budget |
| `rain_driven` | bool | Was rainfall the primary driver? |
| `seismically_detectable` | bool | Did the initiating event radiate a seismic signal? |
| `deaths`, `missing`, `injured`, `damage_usd` | int/null | Reported impact |
| `features` | dict | Nine normalised 0–1 signature dimensions (below) |
| `outcome` | string | What physically happened |
| `lesson` | string | The monitoring/alerting lesson |
| `warning_failed` | bool | Did the operational warning fail? |
| `failure_mode` | string | Category of failure |
| `confidence` | string | `well_documented` / `reported` |
| `source_note` | string | Caveats on the figures |

### Signature space

`rain_24h`, `rain_intensity`, `discharge_anomaly`, `seismic_energy`,
`shallowness`, `mass_movement_signature`, `clustering`, `cryosphere`,
`onset_speed` — each normalised to 0–1.

These are the **same nine dimensions the Prahari risk engine computes for a live
zone**, which is what makes retrieval meaningful: a current zone state and a
1972-style historical record are directly comparable vectors.

## Usage

```python
from datasets import load_dataset

ds = load_dataset("json", data_files="incidents.jsonl", split="train")
clear_sky = ds.filter(lambda r: not r["rain_driven"] and r["seismically_detectable"])
print(clear_sky["title"])
```

## Failure modes represented

`single_channel_rainfall_only`, `no_ground_motion_monitoring`,
`monitoring_not_connected_to_alerting`, `compound_event_underestimated`,
`low_discharge_not_treated_as_signal`, `sediment_amplification_unmodelled`,
`last_mile_delivery`

## Limitations — please read before citing

- **Small and curated, not exhaustive.** 10 incidents chosen to span failure
  modes, not to be a complete regional catalogue. It is a retrieval corpus, not
  a training set, and it is far too small to fit a model on.
- **Casualty figures are secondary-source and vary.** Fields carry a
  `confidence` and a `source_note`; the 2026 entries are marked `reported` and
  should be checked against final official assessments before public use.
- **The `features` vectors are expert-assigned**, derived from published event
  descriptions rather than recovered instrument records. They encode a
  qualitative signature, not measurements.
- **Regional scope.** Nepal and north-east India only. Do not assume the
  thresholds transfer to other mountain or delta systems.

## Citation

Curated for the Prahari dual-channel early-warning project. Reuse freely under
CC-BY-4.0; please preserve the `source_note` caveats alongside any figure.
