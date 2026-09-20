/* Two maps in one panel.

   REGIONAL: the ten deeply-monitored zones, numbered to match the zone list,
   with the basin river network drawn as a real feature. Numbers rather than
   name labels because the six Trishuli zones sit within 186 km and any zoom
   that also shows Assam turns name labels into mush.

   WORLD: every live hazard event from NASA EONET, GDACS and USGS, categorised.
   Each pin carries its category glyph, so the category survives both
   colour-vision deficiency and a monochrome projector.

   Tiles are attempted but never required — if the CDN is blocked the maps
   degrade to clean schematics rather than blank rectangles. */

import { LEVEL_COLOR, LEVEL_ICON, hazardStyle, fmtNum, timeAgo } from "./api.js";

const CSS = (v) =>
  getComputedStyle(document.documentElement).getPropertyValue(v.replace("var(", "").replace(")", "")).trim() || v;

export class HazardMap {
  constructor(elId, onSelectZone) {
    this.map = L.map(elId, { zoomControl: true, attributionControl: false, worldCopyJump: true })
      .setView([20, 60], 3);
    this.onSelectZone = onSelectZone;
    this.mode = "regional";
    this.zoneLayer = L.layerGroup().addTo(this.map);
    this.worldLayer = L.layerGroup();
    this.flowLayer = L.layerGroup().addTo(this.map);
    this.zoneMarkers = new Map();
    this.fitted = { regional: false, world: false };

    const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12, crossOrigin: true,
    });
    let ok = false;
    tiles.on("tileload", () => { ok = true; });
    tiles.on("tileerror", () => { if (!ok) this.map.removeLayer(tiles); });
    tiles.addTo(this.map);
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    if (mode === "world") {
      this.map.removeLayer(this.zoneLayer);
      this.map.removeLayer(this.flowLayer);
      this.worldLayer.addTo(this.map);
      this.map.setView([18, 40], 2);
    } else {
      this.map.removeLayer(this.worldLayer);
      this.zoneLayer.addTo(this.map);
      this.flowLayer.addTo(this.map);
      this.fitted.regional = false;
    }
  }

  drawBasins(basins, zoneIndex) {
    this.flowLayer.clearLayers();
    basins.forEach((b) =>
      b.reaches.forEach((r) => {
        const a = zoneIndex[r.from], c = zoneIndex[r.to];
        if (!a || !c) return;
        const pts = [[a.lat, a.lon], [c.lat, c.lon]];
        // Drawn as a visible feature: with no basemap the river network is
        // the only geography on screen. Deliberately no national borders —
        // this is a cross-border basin view and hand-drawn boundaries would
        // be both inaccurate and unnecessary.
        L.polyline(pts, { color: CSS("--s-fused"), weight: 6, opacity: 0.15 }).addTo(this.flowLayer);
        L.polyline(pts, { color: CSS("--s-fused"), weight: 2, opacity: 0.6, dashArray: "6 6" })
          .bindTooltip(`${a.name} → ${c.name}<br>${r.distance_km} km · ${r.velocity_ms} m/s`, { sticky: true })
          .addTo(this.flowLayer);
      })
    );
  }

  updateZones(zones, selectedId) {
    zones.forEach((z, i) => {
      const color = CSS(LEVEL_COLOR[z.level]);
      const active = z.level !== "NORMAL";
      const size = Math.round(20 + Math.sqrt(z.population) / 190);
      const sel = z.zone_id === selectedId;

      const html = `<div class="zmark ${active ? "is-active" : ""} ${sel ? "is-sel" : ""} ${z.blindspot ? "is-blind" : ""}"
        style="--zc:${color};width:${size}px;height:${size}px"><span>${i + 1}</span></div>`;

      let m = this.zoneMarkers.get(z.zone_id);
      if (!m) {
        m = L.marker([z.lat, z.lon]).addTo(this.zoneLayer);
        m.on("click", () => this.onSelectZone(z.zone_id));
        this.zoneMarkers.set(z.zone_id, m);
      }
      m.setIcon(L.divIcon({ className: "zmark-wrap", html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] }));
      m.setZIndexOffset(active ? 1000 : 0);

      const eta = z.cascade
        ? `<br><b>Arrival:</b> ${Math.round(z.cascade.eta_seconds / 60)} min from ${z.cascade.source_zone_name}` : "";
      const blind = z.blindspot
        ? `<br><span style="color:${CSS("--lv-warning")}"><b>BLIND SPOT</b> — rainfall-only would report ${z.legacy_level}</span>` : "";
      const fc = (z.forecasts || [])[0]
        ? `<br><b>Forecast:</b> ${z.forecasts[0].percent}% ${z.forecasts[0].hazard} in ${Math.round(z.forecasts[0].horizon_hours)}h` : "";
      m.bindPopup(
        `<b>${i + 1}. ${z.name}</b><br>${z.admin}<br><b>${LEVEL_ICON[z.level]} ${z.level}</b> — ${Math.round(z.score)}/100<br>Population ${fmtNum(z.population)}${eta}${fc}${blind}`
      );
    });

    if (!this.fitted.regional && zones.length && this.mode === "regional") {
      this.fitted.regional = true;
      requestAnimationFrame(() => {
        this.map.invalidateSize();
        this.map.fitBounds(zones.map((z) => [z.lat, z.lon]), { padding: [40, 40] });
      });
    }
  }

  updateWorld(events) {
    this.worldLayer.clearLayers();
    events.forEach((ev) => {
      const st = hazardStyle(ev.hazard);
      const red = ev.alert_level === "Red";
      const html = `<div class="hmark ${red ? "is-red" : ""}" style="--hc:${CSS(st.color)}">${st.glyph}</div>`;
      const mag = ev.magnitude != null ? ` · ${ev.magnitude}${ev.magnitude_unit}` : "";
      const alert = ev.alert_level ? `<br>Alert level: <b>${ev.alert_level}</b>` : "";
      L.marker([ev.lat, ev.lon], {
        icon: L.divIcon({ className: "zmark-wrap", html, iconSize: [22, 22], iconAnchor: [11, 11] }),
      })
        .bindPopup(
          `<b>${st.glyph} ${ev.title}</b><br><span style="opacity:.7">${ev.hazard} · ${ev.source}</span>` +
          `<br>${timeAgo(ev.time)}${mag}${alert}` +
          (ev.url ? `<br><a href="${ev.url}" target="_blank" rel="noopener">Details</a>` : "")
        )
        .bindTooltip(`${st.glyph} ${ev.title}`, { direction: "top" })
        .addTo(this.worldLayer);
    });

    if (!this.fitted.world && events.length && this.mode === "world") {
      this.fitted.world = true;
      requestAnimationFrame(() => this.map.invalidateSize());
    }
  }

  focus(zone) {
    if (zone && this.mode === "regional") this.map.panTo([zone.lat, zone.lon], { animate: true });
  }
}
