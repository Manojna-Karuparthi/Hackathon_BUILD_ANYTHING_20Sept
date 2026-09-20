/* Prahari dashboard controller. */

import { connect, json, post, LEVEL_COLOR, LEVEL_ICON, fmtEta, fmtNum } from "./api.js";
import { playSiren, speak, stopSpeech, unlockAudio } from "./siren.js";
import { RiskMap } from "./map.js";
import { TrendChart } from "./charts.js";

const $ = (id) => document.getElementById(id);

const S = {
  state: null,
  zoneIndex: {},
  selected: null,
  scenarios: [],
  history: [],
  alerts: [],
  tableOpen: false,
};

/* ------------------------------------------------------------------ boot */
async function boot() {
  const [{ zones, basins }, scen] = await Promise.all([
    json("/api/zones"),
    json("/api/scenarios"),
  ]);

  zones.forEach((z) => { S.zoneIndex[z.id] = z; });
  S.selected = "np-rasuwa";
  S.scenarios = scen.scenarios;

  S.map = new RiskMap("map", selectZone);
  S.map.drawBasins(basins, S.zoneIndex);
  S.chart = new TrendChart("chart");

  renderLegend();
  renderScenarioOptions(scen.active);
  renderDrillOptions(zones);
  wireControls();

  connect({
    onState: (st) => { S.state = st; render(); },
    onAlert: handleAlert,
    onStatus: setConnStatus,
  });

  await refreshAlerts();
  setInterval(tickCountdowns, 1000);
}

/* -------------------------------------------------------------- rendering */
function render() {
  const st = S.state;
  if (!st) return;

  // National level badge
  $("nat-level-text").textContent = `${LEVEL_ICON[st.national_level]} ${st.national_level}`;
  $("nat-level").querySelector(".natlevel-dot").style.background = LEVEL_COLOR[st.national_level];
  $("nat-clock").textContent =
    `${st.scenario_label} · ${new Date(st.clock).toLocaleTimeString("en-GB")}`;

  // Blind-spot banner - the headline claim, computed live
  const blind = st.zones.filter((z) => z.blindspot);
  const bar = $("blindbar");
  if (blind.length) {
    const pop = blind.reduce((a, z) => a + z.population, 0);
    bar.hidden = false;
    $("blind-headline").textContent =
      `${blind.length} zone${blind.length > 1 ? "s" : ""} · ${fmtNum(pop)} people at risk that a rainfall-only system reports as NORMAL`;
    $("blind-detail").textContent =
      blind.map((z) => `${z.name} ${Math.round(z.score)} vs ${Math.round(z.legacy_score)}`).join("  ·  ");
  } else {
    bar.hidden = true;
  }

  $("pop-at-risk").textContent = `${fmtNum(st.population_at_risk)} exposed`;
  $("narrative").textContent = st.hf.narrative || "—";

  renderZones(st.zones);
  S.map.update(st.zones, S.selected);
  S.map.fit(st.zones);
  renderSources(st.sources);
  renderWhy();
  syncPlayback(st);
  refreshHistory();
}

function renderZones(zones) {
  const ul = $("zonelist");
  ul.innerHTML = zones.map((z, i) => {
    const eta = z.cascade
      ? `<span class="zone-eta" data-eta="${z.cascade.eta_iso}">${fmtEta(z.cascade.eta_seconds)}</span>`
      : "";
    const blind = z.blindspot ? `<span class="zone-blind">BLIND SPOT</span>` : "";
    return `
      <li class="zone ${z.zone_id === S.selected ? "is-sel" : ""}" data-zone="${z.zone_id}">
        <span class="zone-bar" style="background:${LEVEL_COLOR[z.level]}"></span>
        <div class="zone-main">
          <div class="zone-name"><span class="zone-num">${i + 1}</span>${z.name}</div>
          <div class="zone-meta">${z.river} · ${fmtNum(z.population)} people</div>
        </div>
        <div class="zone-right">
          <span class="zone-score" style="color:${LEVEL_COLOR[z.level]}">${Math.round(z.score)}</span>
          <span class="zone-level" style="color:${LEVEL_COLOR[z.level]}">${LEVEL_ICON[z.level]} ${z.level}</span>
          ${eta}${blind}
        </div>
      </li>`;
  }).join("");

  ul.querySelectorAll(".zone").forEach((el) =>
    el.addEventListener("click", () => selectZone(el.dataset.zone))
  );
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

  $("contribs").innerHTML = contribs.length
    ? contribs.map((c) => `
        <div class="contrib">
          <div class="contrib-head">
            <span class="contrib-label">${c.label}
              <span style="color:var(--ink-muted)">· ${c.chan === "hydro" ? "Channel A" : "Channel B"}</span>
            </span>
            <span class="contrib-pts">${c.points.toFixed(1)} pts</span>
          </div>
          <div class="contrib-track">
            <div class="contrib-fill is-${c.chan}" style="width:${Math.min(100, c.points / 34 * 100)}%"></div>
          </div>
          <div class="contrib-detail">${c.detail}</div>
        </div>`).join("")
    : '<p class="empty">No active inputs for this zone.</p>';

  $("analogues").innerHTML = z.analogues.length
    ? z.analogues.map((a) => `
        <div class="analogue">
          <div class="analogue-head">
            <span class="analogue-title">${a.title}</span>
            <span class="analogue-sim">${(a.similarity * 100).toFixed(0)}% match</span>
          </div>
          <div class="analogue-meta">${a.date} · ${a.mechanism}</div>
          <div class="analogue-lesson">${a.lesson}</div>
        </div>`).join("")
    : '<p class="empty">Conditions are too quiet to match a historical signature.</p>';
}

function renderSources(sources) {
  const hf = S.state.hf || {};
  const rows = sources.map((s) =>
    `<li><span class="src-dot src-${s.mode}"></span>
       <span class="src-name">${s.name}</span>
       <span class="src-mode">${s.mode}${s.latency_ms ? ` ${Math.round(s.latency_ms)}ms` : ""}</span></li>`
  );
  rows.push(
    `<li><span class="src-dot ${hf.token_present ? "src-live" : "src-cache"}"></span>
       <span class="src-name">huggingface · corpus + briefing</span>
       <span class="src-mode">${hf.token_present ? "token set" : "local"}</span></li>`
  );
  $("sources").innerHTML = rows.join("");
}

function renderLegend() {
  $("legend").innerHTML = ["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"]
    .map((l) => `<span class="legend-item">
        <span class="legend-sw" style="background:${LEVEL_COLOR[l]}"></span>${LEVEL_ICON[l]} ${l}
      </span>`).join("");
}

function renderScenarioOptions(active) {
  $("scenario").innerHTML = S.scenarios
    .map((s) => `<option value="${s.id}" ${s.id === active ? "selected" : ""}>${s.label}</option>`)
    .join("");
  updateScenarioHint();
}

function updateScenarioHint() {
  const s = S.scenarios.find((x) => x.id === $("scenario").value);
  $("scenario-hint").textContent = s ? s.teaches : "";
  $("playback-block").style.display = s && s.is_live ? "none" : "";
  if (s && !s.is_live) $("scrubber").max = Math.max(0, s.duration_steps - 1);
}

function renderDrillOptions(zones) {
  $("drill-zone").innerHTML = zones
    .map((z) => `<option value="${z.id}" ${z.id === "np-rasuwa" ? "selected" : ""}>${z.name}</option>`)
    .join("");
}

function syncPlayback(st) {
  const hf = st.hf || {};
  $("step-label").textContent = hf.replay_total
    ? `step ${hf.replay_step + 1} / ${hf.replay_total}`
    : "live";
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

/* ------------------------------------------------------------- countdowns */
/* The server sends an absolute arrival time; the client interpolates between
   ticks so the countdown moves every second rather than every poll. */
function tickCountdowns() {
  document.querySelectorAll("[data-eta]").forEach((el) => {
    const secs = (new Date(el.dataset.eta) - Date.now()) / 1000;
    el.textContent = fmtEta(secs);
    if (secs <= 0) el.style.color = "var(--lv-warning)";
  });
  const box = $("siren-eta-value");
  if (box && box.dataset.eta) {
    box.textContent = fmtEta((new Date(box.dataset.eta) - Date.now()) / 1000);
  }
}

/* ----------------------------------------------------------------- alerts */
function handleAlert(alert) {
  S.alerts.unshift(alert);
  renderAlertLog();
  showSiren(alert);
}

function showSiren(alert) {
  $("siren-level").textContent = alert.level;
  $("siren-head").textContent = alert.headline;
  $("siren-body").textContent = alert.body;
  $("siren-channels").innerHTML = alert.dispatched
    .map((c) => `<span class="chip">${c}</span>`).join("") +
    (alert.simulated ? '<span class="chip is-sim">simulated</span>' : "");

  const etaBox = $("siren-eta");
  const zone = S.state && S.state.zones.find((z) => z.zone_id === alert.zone_id);
  if (zone && zone.cascade) {
    etaBox.hidden = false;
    $("siren-eta-value").dataset.eta = zone.cascade.eta_iso;
    $("siren-eta-value").textContent = fmtEta(zone.cascade.eta_seconds);
  } else {
    etaBox.hidden = true;
    delete $("siren-eta-value").dataset.eta;
  }

  $("siren").hidden = false;
  if ($("opt-siren").checked) playSiren(3);
  if ($("opt-speech").checked) setTimeout(() => speak(alert.spoken), 1200);
}

async function refreshAlerts() {
  const { alerts } = await json("/api/alerts?limit=40");
  S.alerts = alerts;
  renderAlertLog();
}

function renderAlertLog() {
  $("log-count").textContent = S.alerts.length;
  $("alertlog").innerHTML = S.alerts.length
    ? S.alerts.slice(0, 40).map((a) => `
        <li class="alert-item" style="border-left-color:${LEVEL_COLOR[a.level]}">
          <div class="alert-head">
            <span class="alert-level" style="color:${LEVEL_COLOR[a.level]}">${LEVEL_ICON[a.level]} ${a.level}</span>
            <span class="alert-time">${new Date(a.created_at).toLocaleTimeString("en-GB")}</span>
          </div>
          <div class="alert-headline">${a.headline}</div>
          <div class="alert-chans">
            ${(a.dispatched || []).map((c) => `<span class="chip">${c}</span>`).join("")}
            ${a.simulated ? '<span class="chip is-sim">simulated</span>' : ""}
          </div>
        </li>`).join("")
    : '<p class="empty">No alerts yet. Run a scenario or trigger a drill.</p>';
}

/* ---------------------------------------------------------------- history */
async function refreshHistory() {
  if (!S.selected) return;
  const { history } = await json(`/api/zone/${S.selected}/history?limit=80`);
  S.history = history;
  S.chart.update(history);
  if (S.tableOpen) $("table-view").innerHTML = S.chart.tableHTML(history);
}

function currentZone() {
  return S.state && S.state.zones.find((z) => z.zone_id === S.selected);
}

function selectZone(id) {
  S.selected = id;
  render();
  S.map.focus(S.zoneIndex[id]);
}

function setConnStatus(status) {
  const el = $("conn-badge");
  el.classList.toggle("is-up", status === "up");
  el.classList.toggle("is-down", status === "down");
  $("conn-text").textContent = status === "up" ? "live" : "reconnecting";
}

/* --------------------------------------------------------------- controls */
function wireControls() {
  $("scenario").addEventListener("change", async (e) => {
    updateScenarioHint();
    await post(`/api/scenario/${e.target.value}`);
    await refreshAlerts();
  });

  $("btn-play").addEventListener("click", async () => {
    unlockAudio();
    const playing = S.state && S.state.hf.replay_playing;
    await post(`/api/playback/${playing ? "pause" : "play"}`);
  });
  $("btn-step").addEventListener("click", () => post("/api/playback/step"));
  $("btn-restart").addEventListener("click", async () => {
    await post("/api/playback/restart");
    await refreshAlerts();
  });
  $("scrubber").addEventListener("change", (e) =>
    post(`/api/playback/seek?step=${e.target.value}`)
  );

  $("eng-dual").addEventListener("click", () => post("/api/engine/dual"));
  $("eng-legacy").addEventListener("click", () => post("/api/engine/legacy"));

  $("btn-drill").addEventListener("click", async () => {
    unlockAudio();
    await post(`/api/simulate/${$("drill-zone").value}?level=EMERGENCY`);
  });

  $("btn-test-audio").addEventListener("click", () => {
    unlockAudio();
    playSiren(1);
    setTimeout(() => speak("Audio check. Prahari alert system is ready.", { rate: 0.95 }), 900);
  });

  $("siren-close").addEventListener("click", () => {
    $("siren").hidden = true;
    stopSpeech();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("siren").hidden) {
      $("siren").hidden = true;
      stopSpeech();
    }
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

boot().catch((err) => {
  document.getElementById("narrative").textContent = `Startup failed: ${err.message}`;
  console.error(err);
});
