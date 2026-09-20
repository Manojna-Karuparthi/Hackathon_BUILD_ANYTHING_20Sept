/* Prahari dashboard controller. */

import {
  connect, json, post, postBody, LEVEL_COLOR, LEVEL_ICON,
  hazardStyle, FORECAST_BAND_COLOR, fmtEta, fmtNum, timeAgo,
} from "./api.js";
import { playSiren, speak, stopSpeech, unlockAudio, availableVoiceLangs } from "./siren.js";
import { HazardMap } from "./map.js";
import { TrendChart } from "./charts.js";
import { Assistant } from "./assistant.js";

const $ = (id) => document.getElementById(id);

const S = {
  state: null, zoneIndex: {}, selected: "np-rasuwa", scenarios: [], hazards: [],
  languages: [], lang: "en", speechLang: "en-IN", history: [], alerts: [],
  mapMode: "regional", hazardFilter: new Set(), tableOpen: false, lastAlert: null,
};

/* ══════════════════════════════ boot ══════════════════════════════════ */
async function boot() {
  const [{ zones, basins }, scen, haz, langs] = await Promise.all([
    json("/api/zones"), json("/api/scenarios"), json("/api/hazards"), json("/api/languages"),
  ]);

  zones.forEach((z) => { S.zoneIndex[z.id] = z; });
  S.scenarios = scen.scenarios;
  S.hazards = haz.hazards;
  S.languages = langs.languages;
  S.lang = langs.active || "en";
  S.hazards.forEach((h) => S.hazardFilter.add(h.id));

  S.map = new HazardMap("map", selectZone);
  S.map.drawBasins(basins, S.zoneIndex);
  S.chart = new TrendChart("chart");
  S.assistant = new Assistant(() => S.lang);

  renderLanguages(langs);
  renderScenarioOptions(scen.active);
  renderDrillOptions(zones);
  renderMapLegend();
  wireControls();

  connect({ onState: (st) => { S.state = st; render(); }, onAlert: handleAlert, onStatus: setConn });
  await refreshAlerts();
  setInterval(tickCountdowns, 1000);
}

/* ═══════════════════════════ rendering ════════════════════════════════ */
function render() {
  const st = S.state;
  if (!st) return;

  $("nat-level-text").textContent = `${LEVEL_ICON[st.national_level]} ${st.national_level}`;
  $("nat-level").querySelector(".statchip-dot").style.background = LEVEL_COLOR[st.national_level];
  $("nat-clock").textContent = `${st.scenario_label} · ${new Date(st.clock).toLocaleTimeString("en-GB")}`;
  $("narrative").textContent = st.hf.narrative || "—";
  $("pop-at-risk").textContent = `${fmtNum(st.population_at_risk)} exposed`;

  renderBanners(st);
  renderHero(st);
  renderZones(st.zones);
  renderForecasts(st);
  renderHazardFilter(st);
  renderSources(st.sources);
  renderMapLegend();
  renderWhy();
  syncPlayback(st);

  if (S.mapMode === "regional") S.map.updateZones(st.zones, S.selected);
  else S.map.updateWorld(filteredEvents(st));
  $("map-count").textContent =
    S.mapMode === "regional" ? `${st.zones.length} zones` : `${filteredEvents(st).length} events`;

  refreshHistory();
}

function renderBanners(st) {
  const out = [];
  const blind = st.zones.filter((z) => z.blindspot);
  const alarms = st.zones.filter((z) => z.forecast_alarm);

  if (alarms.length) {
    const top = alarms.map((z) => z.forecasts[0]).sort((a, b) => b.probability - a.probability)[0];
    out.push(`<div class="banner" style="--bc:var(--lv-warning)">
      <span class="banner-glyph">◉</span>
      <div class="banner-body">
        <strong>FORECAST ALARM · ${alarms.length} zone${alarms.length > 1 ? "s" : ""} above the ${Math.round(st.hf.alarm_probability * 100)}% action threshold</strong>
        <span>Highest: ${top.percent}% probability of ${top.hazard} within ${Math.round(top.horizon_hours)}h — ${alarms.map((z) => z.name.split(" (")[0]).join(", ")}</span>
      </div></div>`);
  }
  if (blind.length) {
    const pop = blind.reduce((a, z) => a + z.population, 0);
    out.push(`<div class="banner" style="--bc:var(--lv-warning)">
      <span class="banner-glyph">⚠</span>
      <div class="banner-body">
        <strong>${blind.length} zones · ${fmtNum(pop)} people at risk that a rainfall-only system reports as NORMAL</strong>
        <span>${blind.map((z) => `${z.name.split(" (")[0]} ${Math.round(z.score)} vs ${Math.round(z.legacy_score)}`).join("  ·  ")}</span>
      </div></div>`);
  }
  $("banners").innerHTML = out.join("");
}

function renderHero(st) {
  const alarms = st.zones.filter((z) => z.forecast_alarm).length;
  const topP = Math.max(0, ...st.zones.map((z) => z.top_probability || 0));
  const worldRed = (st.global_events || []).filter((e) => e.alert_level === "Red").length;
  const cells = [
    { label: "National level", value: `${LEVEL_ICON[st.national_level]} ${st.national_level}`,
      sub: `${st.zones.length} zones monitored`, color: LEVEL_COLOR[st.national_level] },
    { label: "People exposed", value: fmtNum(st.population_at_risk),
      sub: "at WATCH or above", color: st.population_at_risk ? "var(--lv-watch)" : "var(--lv-normal)" },
    { label: "Highest probability", value: `${Math.round(topP * 100)}%`,
      sub: `next ${Math.round(st.hf.forecast_horizon_h || 24)}h · ${alarms} alarm${alarms === 1 ? "" : "s"}`,
      color: topP >= (st.hf.alarm_probability || 0.9) ? "var(--lv-warning)" : "var(--s-fused)" },
    { label: "World hazards live", value: String((st.global_events || []).length),
      sub: `${worldRed} at red alert · ${Object.keys(st.hazard_counts || {}).length} categories`,
      color: "var(--s-legacy)" },
  ];
  $("herorow").innerHTML = cells.map((c) => `
    <div class="hero" style="--hc:${c.color}">
      <span class="hero-label">${c.label}</span>
      <div class="hero-value">${c.value}</div>
      <span class="hero-sub">${c.sub}</span>
    </div>`).join("");
}

function renderZones(zones) {
  $("zonelist").innerHTML = zones.map((z, i) => {
    const eta = z.cascade
      ? `<span class="zone-eta" data-eta="${z.cascade.eta_iso}">${fmtEta(z.cascade.eta_seconds)}</span>` : "";
    const tags = [];
    if (z.blindspot) tags.push('<span class="zone-tag is-blind">BLIND SPOT</span>');
    if (z.forecast_alarm) tags.push(`<span class="zone-tag is-fc">${z.forecasts[0].percent}% FORECAST</span>`);
    return `<li class="zone ${z.zone_id === S.selected ? "is-sel" : ""}" data-zone="${z.zone_id}">
        <span class="zone-bar" style="background:${LEVEL_COLOR[z.level]}"></span>
        <div class="zone-main">
          <div class="zone-name"><span class="zone-num">${i + 1}</span>${z.name}</div>
          <div class="zone-meta">${z.river} · ${fmtNum(z.population)} people</div>
        </div>
        <div class="zone-right">
          <span class="zone-score" style="color:${LEVEL_COLOR[z.level]}">${Math.round(z.score)}</span>
          <span class="zone-level" style="color:${LEVEL_COLOR[z.level]}">${LEVEL_ICON[z.level]} ${z.level}</span>
          ${eta}<div class="zone-tags">${tags.join("")}</div>
        </div></li>`;
  }).join("");
  $("zonelist").querySelectorAll(".zone").forEach((el) =>
    el.addEventListener("click", () => selectZone(el.dataset.zone)));
}

function renderForecasts(st) {
  const thr = st.hf.alarm_probability || 0.9;
  $("forecast-meta").textContent =
    `${Math.round(st.hf.forecast_horizon_h || 24)}h · alarm at ${Math.round(thr * 100)}%`;

  const cards = [];

  /* Detected-not-forecast cards come first.

     A confirmed ice-rock avalanche already in motion has no meaningful
     "probability" - it is happening. Showing it as a 2% forecast alongside
     real probabilities would be actively misleading, so it gets its own card
     type that says DETECTED and shows the arrival countdown instead. This is
     also the honest statement of the limit: this hazard class cannot be
     forecast, only detected, which is exactly why Channel B exists. */
  st.zones
    .filter((z) => z.cascade && z.cascade.transferred_score > z.geo.score)
    .sort((a, b) => a.cascade.eta_seconds - b.cascade.eta_seconds)
    .forEach((z) => {
      const hz = hazardStyle("glof");
      cards.push(`<div class="fc is-detected" style="--hc:${hz.color}">
        <div class="fc-top">
          <div>
            <div class="fc-where">${hz.glyph} ${z.name.split(" (")[0]}</div>
            <div class="fc-haz">mass-movement debris flood · inbound</div>
          </div>
          <div><div class="fc-pct fc-eta" data-eta="${z.cascade.eta_iso}">${fmtEta(z.cascade.eta_seconds)}</div>
            <span class="fc-band" style="color:var(--lv-warning)">DETECTED</span></div>
        </div>
        <div class="fc-method">Not a forecast — a confirmed detachment already in motion.</div>
        <div class="fc-basis">Ground motion detected at ${z.cascade.source_zone_name}, ${z.cascade.distance_km.toFixed(0)} km upstream, travelling at ${z.cascade.velocity_ms.toFixed(1)} m/s average. This hazard class cannot be predicted in advance; it can only be detected and then outrun.</div>
      </div>`);
    });

  const rows = [];
  st.zones.forEach((z) => (z.forecasts || []).forEach((f) => rows.push({ z, f })));
  rows.sort((a, b) => b.f.probability - a.f.probability);

  // Below 10% a forecast is noise, and ten identical "2%" cards bury the one
  // number that matters. Keep at least one so the panel is never empty.
  const meaningful = rows.filter((r) => r.f.probability >= 0.10);
  const shown = (meaningful.length ? meaningful : rows.slice(0, 1)).slice(0, 8);

  shown.forEach(({ z, f }) => {
    const hz = hazardStyle(f.hazard);
    cards.push(`<div class="fc ${f.actionable ? "is-alarm" : ""}" style="--hc:${hz.color}">
      <div class="fc-top">
        <div>
          <div class="fc-where">${hz.glyph} ${z.name.split(" (")[0]}</div>
          <div class="fc-haz">${f.hazard} · next ${Math.round(f.horizon_hours)}h</div>
        </div>
        <div><div class="fc-pct">${f.percent}%</div>
          <span class="fc-band" style="color:${FORECAST_BAND_COLOR[f.band]}">${f.band.replace("_", " ")}</span></div>
      </div>
      <div class="fc-track">
        <div class="fc-fill" style="width:${f.percent}%"></div>
        <div class="fc-thresh" style="left:${Math.round(thr * 100)}%" title="alarm threshold"></div>
      </div>
      <div class="fc-method">Method: ${f.method}</div>
      <div class="fc-basis">${f.basis}</div>
    </div>`);
  });

  const hidden = rows.length - shown.length;
  $("forecasts").innerHTML = cards.join("") || '<p class="empty">No forecasts available.</p>';
  $("forecast-note").textContent =
    (hidden > 0 ? `${hidden} forecast${hidden === 1 ? "" : "s"} below 10% hidden. ` : "") +
    "Probabilities come from published forecast methods, not a trained model. " +
    "Aftershock probability is conditional on an earthquake that has already happened — " +
    "no system can forecast a first earthquake, and no system can forecast a glacier collapse.";
}

function renderHazardFilter(st) {
  const counts = st.hazard_counts || {};
  const show = S.mapMode === "world";
  $("hazfilter").hidden = !show;
  if (!show) return;
  $("hazfilter").innerHTML = S.hazards
    .filter((h) => counts[h.id])
    .map((h) => {
      const style = hazardStyle(h.id);
      const on = S.hazardFilter.has(h.id);
      return `<button class="hchip ${on ? "is-on" : ""}" data-haz="${h.id}" style="--hc:${style.color}"
        aria-pressed="${on}" title="${h.description}">
        <span class="hchip-glyph">${style.glyph}</span>${h.label}<span class="hchip-n">${counts[h.id]}</span>
      </button>`;
    }).join("");
  $("hazfilter").querySelectorAll(".hchip").forEach((el) =>
    el.addEventListener("click", () => {
      const id = el.dataset.haz;
      S.hazardFilter.has(id) ? S.hazardFilter.delete(id) : S.hazardFilter.add(id);
      render();
    }));
}

const filteredEvents = (st) =>
  (st.global_events || []).filter((e) => S.hazardFilter.has(e.hazard));

function renderMapLegend() {
  // The legend must describe what is actually on the map. In world mode the
  // filter chips above already carry every category with its glyph and count,
  // so repeating a risk-band legend there would be describing the wrong thing.
  if (S.mapMode === "world") {
    $("maplegend").innerHTML =
      '<span class="legend-item">Pins show hazard category — filter with the chips above. ' +
      'A thicker border marks a red-level alert.</span>';
    return;
  }
  $("maplegend").innerHTML = ["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"]
    .map((l) => `<span class="legend-item"><span class="legend-sw" style="background:${LEVEL_COLOR[l]}"></span>${LEVEL_ICON[l]} ${l}</span>`)
    .join("");
}

function renderWhy() {
  const z = currentZone();
  if (!z) return;
  $("why-zone").textContent = z.name;
  $("chart-zone").textContent = z.name;
  $("why-text").textContent = z.explanation;
  $("fusion-note").textContent = z.fusion_note;

  const contribs = [
    ...z.hydro.contributions.map((c) => ({ ...c, chan: "hydro" })),
    ...z.geo.contributions.map((c) => ({ ...c, chan: "geo" })),
  ].sort((a, b) => b.points - a.points);

  $("contribs").innerHTML = contribs.length ? contribs.map((c) => `
      <div class="contrib">
        <div class="contrib-head">
          <span class="contrib-label">${c.label} <span style="color:var(--ink-muted)">· ${c.chan === "hydro" ? "Channel A" : "Channel B"}</span></span>
          <span class="contrib-pts">${c.points.toFixed(1)} pts</span>
        </div>
        <div class="contrib-track"><div class="contrib-fill is-${c.chan}" style="width:${Math.min(100, c.points / 34 * 100)}%"></div></div>
        <div class="contrib-detail">${c.detail}</div>
      </div>`).join("") : '<p class="empty">No active inputs for this zone.</p>';

  $("analogues").innerHTML = z.analogues.length ? z.analogues.map((a) => `
      <div class="analogue">
        <div class="analogue-head"><span class="analogue-title">${a.title}</span>
          <span class="analogue-sim">${(a.similarity * 100).toFixed(0)}% match</span></div>
        <div class="analogue-meta">${a.date} · ${a.mechanism}</div>
        <div class="analogue-lesson">${a.lesson}</div>
      </div>`).join("") : '<p class="empty">Conditions are too quiet to match a historical signature.</p>';
}

function renderSources(sources) {
  const hf = S.state.hf || {};
  const rows = sources.map((s) =>
    `<li><span class="src-dot src-${s.mode}"></span><span class="src-name">${s.name}</span>
      <span class="src-mode">${s.mode}${s.latency_ms ? ` ${Math.round(s.latency_ms)}ms` : ""}</span></li>`);
  rows.push(`<li><span class="src-dot ${hf.token_present ? "src-live" : "src-cache"}"></span>
    <span class="src-name">huggingface · corpus + briefing</span>
    <span class="src-mode">${hf.token_present ? "token set" : "local"}</span></li>`);
  $("sources").innerHTML = rows.join("");
}

function renderLanguages(langs) {
  const have = availableVoiceLangs();
  // An empty voice list means the engine has not reported yet (or this is a
  // headless browser) - NOT that every language is unsupported. Claiming
  // "no voice" for everything would be wrong, so we say nothing instead.
  const known = have.size > 0;
  $("language").innerHTML = S.languages.map((l) => {
    const voiced = have.has(l.speech_primary.toLowerCase()) ||
      [...have].some((v) => v.startsWith(l.speech_primary.split("-")[0]));
    const mark = l.dialect_of ? " (dialect)" : (known && !voiced ? " ·no voice" : "");
    return `<option value="${l.code}" ${l.code === S.lang ? "selected" : ""}>${l.native}${mark}</option>`;
  }).join("");
  const active = S.languages.find((l) => l.code === S.lang);
  S.speechLang = active ? active.speech_primary : "en-IN";
  $("as-lang-note").textContent = active
    ? `Answers in ${active.native}. Voice: ${active.speech_primary}${active.voice_fallback ? " (fallback voice — no dedicated engine for this dialect)" : ""}.`
    : "";
}

function renderScenarioOptions(active) {
  $("scenario").innerHTML = S.scenarios
    .map((s) => `<option value="${s.id}" ${s.id === active ? "selected" : ""}>${s.label}</option>`).join("");
  updateScenarioHint();
}
function updateScenarioHint() {
  const s = S.scenarios.find((x) => x.id === $("scenario").value);
  $("scenario-hint").textContent = s ? s.teaches : "";
  $("playback-block").hidden = !!(s && s.is_live);
  if (s && !s.is_live) $("scrubber").max = Math.max(0, s.duration_steps - 1);
}
function renderDrillOptions(zones) {
  $("drill-zone").innerHTML = zones
    .map((z) => `<option value="${z.id}" ${z.id === "np-rasuwa" ? "selected" : ""}>${z.name}</option>`).join("");
}
function syncPlayback(st) {
  const hf = st.hf || {};
  $("step-label").textContent = hf.replay_total ? `step ${hf.replay_step + 1} / ${hf.replay_total}` : "live";
  if (hf.replay_total) {
    $("scrubber").max = hf.replay_total - 1;
    if (document.activeElement !== $("scrubber")) $("scrubber").value = hf.replay_step;
  }
  $("btn-play").textContent = hf.replay_playing ? "❚❚ Pause" : "▶ Play";
  $("eng-dual").classList.toggle("is-on", st.engine_mode === "dual");
  $("eng-legacy").classList.toggle("is-on", st.engine_mode === "legacy");
  $("eng-dual").setAttribute("aria-checked", String(st.engine_mode === "dual"));
  $("eng-legacy").setAttribute("aria-checked", String(st.engine_mode === "legacy"));
}

/* ═════════════════════════ countdowns & alerts ════════════════════════ */
function tickCountdowns() {
  document.querySelectorAll("[data-eta]").forEach((el) => {
    const secs = (new Date(el.dataset.eta) - Date.now()) / 1000;
    el.textContent = fmtEta(secs);
    if (secs <= 0) el.style.color = "var(--lv-warning)";
  });
  document.querySelectorAll(".fc-eta[data-eta]").forEach((el) => {
    el.textContent = fmtEta((new Date(el.dataset.eta) - Date.now()) / 1000);
  });
  const box = $("siren-eta-value");
  if (box && box.dataset.eta) box.textContent = fmtEta((new Date(box.dataset.eta) - Date.now()) / 1000);
}

function handleAlert(alert) {
  S.alerts.unshift(alert);
  renderAlertLog();
  showSiren(alert);
}

function localisedSpoken(alert) {
  return (alert.translations && alert.translations[S.lang]) || alert.spoken;
}

function showSiren(alert) {
  S.lastAlert = alert;
  $("siren-level").textContent = alert.level;
  $("siren-head").textContent = alert.headline;
  $("siren-body").textContent = alert.body;

  const spoken = localisedSpoken(alert);
  const lang = S.languages.find((l) => l.code === S.lang);
  $("siren-spoken").textContent = spoken;
  $("siren-spoken").classList.toggle("is-rtl", !!(lang && lang.rtl));

  const chans = alert.dispatched.map((c) => `<span class="chip">${c}</span>`).join("");
  $("siren-channels").innerHTML = chans +
    (alert.trigger === "forecast" ? '<span class="chip is-fc">forecast-triggered</span>' : "") +
    (alert.simulated ? '<span class="chip is-sim">simulated</span>' : "");

  const zone = S.state && S.state.zones.find((z) => z.zone_id === alert.zone_id);
  if (zone && zone.cascade) {
    $("siren-eta").hidden = false;
    $("siren-eta-value").dataset.eta = zone.cascade.eta_iso;
    $("siren-eta-value").textContent = fmtEta(zone.cascade.eta_seconds);
  } else {
    $("siren-eta").hidden = true;
    delete $("siren-eta-value").dataset.eta;
  }

  $("siren").hidden = false;
  if ($("opt-siren").checked) playSiren(3);
  if ($("opt-speech").checked) setTimeout(() => speak(spoken, { lang: S.speechLang }), 1200);
}

async function refreshAlerts() {
  const { alerts } = await json("/api/alerts?limit=40");
  S.alerts = alerts;
  renderAlertLog();
}

function renderAlertLog() {
  $("log-count").textContent = S.alerts.length;
  $("alertlog").innerHTML = S.alerts.length ? S.alerts.slice(0, 40).map((a) => `
      <li class="alert-item" style="border-left-color:${LEVEL_COLOR[a.level]}">
        <div class="alert-head">
          <span class="alert-level" style="color:${LEVEL_COLOR[a.level]}">${LEVEL_ICON[a.level]} ${a.level}</span>
          <span class="alert-time">${new Date(a.created_at).toLocaleTimeString("en-GB")}</span>
        </div>
        <div class="alert-headline">${a.headline}</div>
        <div class="alert-chans">
          ${(a.dispatched || []).map((c) => `<span class="chip">${c}</span>`).join("")}
          ${a.trigger === "forecast" ? '<span class="chip is-fc">forecast</span>' : ""}
          ${a.simulated ? '<span class="chip is-sim">simulated</span>' : ""}
        </div></li>`).join("")
    : '<p class="empty">No alerts yet. Run a scenario or trigger a drill.</p>';
}

/* ═══════════════════════════ misc & controls ══════════════════════════ */
async function refreshHistory() {
  if (!S.selected) return;
  const { history } = await json(`/api/zone/${S.selected}/history?limit=80`);
  S.history = history;
  S.chart.update(history);
  if (S.tableOpen) $("table-view").innerHTML = S.chart.tableHTML(history);
}
const currentZone = () => S.state && S.state.zones.find((z) => z.zone_id === S.selected);
function selectZone(id) { S.selected = id; render(); S.map.focus(S.zoneIndex[id]); }
function setConn(status) {
  $("conn-badge").classList.toggle("is-up", status === "up");
  $("conn-badge").classList.toggle("is-down", status === "down");
  $("conn-text").textContent = status === "up" ? "live" : "reconnecting";
}

function wireControls() {
  $("scenario").addEventListener("change", async (e) => {
    updateScenarioHint();
    await post(`/api/scenario/${e.target.value}`);
    await refreshAlerts();
  });
  $("btn-play").addEventListener("click", async () => {
    unlockAudio();
    await post(`/api/playback/${S.state && S.state.hf.replay_playing ? "pause" : "play"}`);
  });
  $("btn-step").addEventListener("click", () => post("/api/playback/step"));
  $("btn-restart").addEventListener("click", async () => {
    await post("/api/playback/restart"); await refreshAlerts();
  });
  $("scrubber").addEventListener("change", (e) => post(`/api/playback/seek?step=${e.target.value}`));

  $("eng-dual").addEventListener("click", () => post("/api/engine/dual"));
  $("eng-legacy").addEventListener("click", () => post("/api/engine/legacy"));

  $("btn-drill").addEventListener("click", async () => {
    unlockAudio();
    await post(`/api/simulate/${$("drill-zone").value}?level=EMERGENCY`);
  });
  $("btn-test-audio").addEventListener("click", () => {
    unlockAudio(); playSiren(1);
    setTimeout(() => speak("Audio check. Prahari alert system is ready.", { rate: .95, lang: S.speechLang }), 900);
  });

  $("language").addEventListener("change", async (e) => {
    S.lang = e.target.value;
    const l = S.languages.find((x) => x.code === S.lang);
    S.speechLang = l ? l.speech_primary : "en-IN";
    S.assistant.setSpeechLang(S.speechLang);
    renderLanguages({ active: S.lang });
    await post(`/api/language/${S.lang}`);
    if (S.lastAlert && !$("siren").hidden) showSiren(S.lastAlert);
  });

  $("tab-regional").addEventListener("click", () => setMapMode("regional"));
  $("tab-world").addEventListener("click", () => setMapMode("world"));

  $("siren-close").addEventListener("click", () => { $("siren").hidden = true; stopSpeech(); });
  $("siren-replay").addEventListener("click", () => {
    if (S.lastAlert) speak(localisedSpoken(S.lastAlert), { lang: S.speechLang });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("siren").hidden) { $("siren").hidden = true; stopSpeech(); }
  });

  $("btn-table").addEventListener("click", () => {
    S.tableOpen = !S.tableOpen;
    $("table-view").hidden = !S.tableOpen;
    document.querySelector(".chart-wrap").hidden = S.tableOpen;
    $("btn-table").setAttribute("aria-expanded", String(S.tableOpen));
    $("btn-table").textContent = S.tableOpen ? "Chart view" : "Table view";
    if (S.tableOpen) $("table-view").innerHTML = S.chart.tableHTML(S.history);
  });
}

function setMapMode(mode) {
  S.mapMode = mode;
  $("tab-regional").classList.toggle("is-on", mode === "regional");
  $("tab-world").classList.toggle("is-on", mode === "world");
  $("tab-regional").setAttribute("aria-selected", String(mode === "regional"));
  $("tab-world").setAttribute("aria-selected", String(mode === "world"));
  S.map.setMode(mode);
  render();
}

boot().catch((err) => {
  $("narrative").textContent = `Startup failed: ${err.message}`;
  console.error(err);
});
