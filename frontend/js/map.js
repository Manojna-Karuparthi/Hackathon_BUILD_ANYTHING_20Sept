/* Leaflet map: zones as risk-coloured circles, basins as directed flow lines.

   Tiles are attempted but never required. If the venue blocks the tile CDN the
   map degrades to a clean schematic of the basin network on the panel surface -
   still readable, still correct, just without terrain. A demo must not depend
   on someone else's CDN. */

import { LEVEL_COLOR, LEVEL_ICON, fmtNum } from "./api.js";

const CSS = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || v;

export class RiskMap {
  constructor(elId, onSelect) {
    this.map = L.map(elId, { zoomControl: true, attributionControl: false })
      .setView([27.6, 89.0], 6);
    this.onSelect = onSelect;
    this.markers = new Map();
    this.flows = [];
    this.tilesOk = false;
    this.fitted = false;

    const tiles = L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 12, crossOrigin: true }
    );
    tiles.on("tileload", () => { this.tilesOk = true; });
    tiles.on("tileerror", () => {
      if (!this.tilesOk) this.map.removeLayer(tiles);
    });
    tiles.addTo(this.map);
  }

  /** Draw the static basin network once. */
  drawBasins(basins, zoneIndex) {
    this.flows.forEach((l) => this.map.removeLayer(l));
    this.flows = [];
    basins.forEach((b) => {
      b.reaches.forEach((r) => {
        const a = zoneIndex[r.from], c = zoneIndex[r.to];
        if (!a || !c) return;
        // The river network carries the map's geography when no basemap loads,
        // so it is drawn as a visible feature rather than a hairline hint.
        // Deliberately no national borders: this is a cross-border basin view
        // and hand-drawn boundaries would be both inaccurate and needless.
        L.polyline([[a.lat, a.lon], [c.lat, c.lon]], {
          color: CSS("--s-fused"), weight: 5, opacity: 0.16,
        }).addTo(this.map);
        const line = L.polyline([[a.lat, a.lon], [c.lat, c.lon]], {
          color: CSS("--s-fused"), weight: 2, opacity: 0.6, dashArray: "6 6",
        }).addTo(this.map);
        line.bindTooltip(
          `${a.name} → ${c.name}<br>${r.distance_km} km · ${r.velocity_ms} m/s (${r.gradient})`,
          { sticky: true }
        );
        this.flows.push(line);
      });
    });
  }

  /* Zones are drawn as NUMBERED markers keyed to the numbered zone list.
     Name labels were tried first and collide badly - the six Trishuli zones sit
     within ~180 km, so at any zoom that also shows Assam their labels overlap
     into mush. Numbers stay legible at every zoom and the list is the legend. */
  update(zones, selectedId) {
    zones.forEach((z, i) => {
      const color = CSS(LEVEL_COLOR[z.level].replace("var(", "").replace(")", ""));
      const active = z.level !== "NORMAL";
      const size = Math.round(20 + Math.sqrt(z.population) / 190);
      const sel = z.zone_id === selectedId;

      const html =
        `<div class="zmark ${active ? "is-active" : ""} ${sel ? "is-sel" : ""} ${z.blindspot ? "is-blind" : ""}"
              style="--zc:${color};width:${size}px;height:${size}px">
           <span>${i + 1}</span>
         </div>`;

      let m = this.markers.get(z.zone_id);
      if (!m) {
        m = L.marker([z.lat, z.lon]).addTo(this.map);
        m.on("click", () => this.onSelect(z.zone_id));
        this.markers.set(z.zone_id, m);
      }
      m.setIcon(L.divIcon({
        className: "zmark-wrap", html,
        iconSize: [size, size], iconAnchor: [size / 2, size / 2],
      }));
      m.setZIndexOffset(active ? 1000 : 0);

      const eta = z.cascade
        ? `<br><b>Arrival:</b> ${Math.round(z.cascade.eta_seconds / 60)} min from ${z.cascade.source_zone_name}`
        : "";
      const blind = z.blindspot
        ? `<br><span style="color:${CSS("--lv-warning")}"><b>BLIND SPOT</b> \u2014 rainfall-only would report ${z.legacy_level}</span>`
        : "";
      m.bindPopup(
        `<b>${i + 1}. ${z.name}</b><br>${z.admin}<br>` +
        `<b>${LEVEL_ICON[z.level]} ${z.level}</b> \u2014 ${Math.round(z.score)}/100<br>` +
        `Population ${fmtNum(z.population)}${eta}${blind}`
      );
      m.bindTooltip(`${i + 1}. ${z.name} \u2014 ${z.level}`, { direction: "top", offset: [0, -6] });
    });
  }

  /** Frame all zones once the first state has arrived. */
  fit(zones) {
    if (this.fitted || !zones.length) return;
    this.fitted = true;
    // Defer one frame: the first state can arrive before the panel has its
    // final size, and fitBounds against a half-laid-out container mis-frames.
    requestAnimationFrame(() => {
      this.map.invalidateSize();
      this.map.fitBounds(zones.map((z) => [z.lat, z.lon]), { padding: [40, 40] });
    });
  }

  focus(zone) {
    if (zone) this.map.panTo([zone.lat, zone.lon], { animate: true });
  }
}
