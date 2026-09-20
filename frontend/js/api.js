/* REST + WebSocket client, plus the shared display vocabulary. */

export const LEVELS = ["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"];

export const LEVEL_COLOR = {
  NORMAL: "var(--lv-normal)", ADVISORY: "var(--lv-advisory)", WATCH: "var(--lv-watch)",
  WARNING: "var(--lv-warning)", EMERGENCY: "var(--lv-emergency)",
};

/* Hue never carries meaning alone — every band also ships this glyph. */
export const LEVEL_ICON = {
  NORMAL: "●", ADVISORY: "▲", WATCH: "▲", WARNING: "■", EMERGENCY: "✖",
};

/* Hazard categories. Nine categories is more than any palette separates under
   colour-vision deficiency at all-pairs, so the glyph and the label are not
   decoration — they are the primary channel, and the hue is the secondary one. */
export const HAZARD_STYLE = {
  flood:      { color: "var(--hz-flood)",   glyph: "≋" },
  earthquake: { color: "var(--hz-quake)",   glyph: "◈" },
  wildfire:   { color: "var(--hz-fire)",    glyph: "▮" },
  cyclone:    { color: "var(--hz-cyclone)", glyph: "◉" },
  volcano:    { color: "var(--hz-volcano)", glyph: "▲" },
  landslide:  { color: "var(--hz-slide)",   glyph: "◤" },
  heatwave:   { color: "var(--hz-heat)",    glyph: "☀" },
  drought:    { color: "var(--hz-drought)", glyph: "◌" },
  glof:       { color: "var(--hz-glof)",    glyph: "❄" },
  other:      { color: "var(--hz-other)",   glyph: "●" },
};

export const hazardStyle = (id) => HAZARD_STYLE[id] || HAZARD_STYLE.other;

export const FORECAST_BAND_COLOR = {
  LOW: "var(--lv-normal)", ELEVATED: "var(--lv-advisory)", HIGH: "var(--lv-watch)",
  VERY_HIGH: "var(--lv-warning)", IMMINENT: "var(--lv-warning)",
};

export const json = (path, opts) =>
  fetch(path, opts).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  });

export const post = (path) => json(path, { method: "POST" });

export const postBody = (path, body) =>
  json(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export function connect({ onState, onAlert, onStatus }) {
  let socket = null, attempt = 0, closed = false;
  const open = () => {
    if (closed) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws`);
    socket.onopen = () => { attempt = 0; onStatus("up"); };
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") onState(msg.payload);
      else if (msg.type === "alert") onAlert(msg.payload);
    };
    socket.onclose = () => {
      onStatus("down");
      if (closed) return;
      attempt += 1;
      setTimeout(open, Math.min(1000 * 2 ** attempt, 15000));
    };
    socket.onerror = () => socket && socket.close();
  };
  open();
  return () => { closed = true; socket && socket.close(); };
}

export function fmtEta(seconds) {
  if (seconds == null) return "—";
  if (seconds <= 0) return "IMPACT";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

export const fmtNum = (n) => (n == null ? "—" : n.toLocaleString("en-IN"));

export function timeAgo(iso) {
  const ms = Date.now() - new Date(iso).getTime();
  if (!isFinite(ms)) return "";
  const h = ms / 3600000;
  if (h < 1) return `${Math.max(1, Math.round(ms / 60000))}m ago`;
  if (h < 48) return `${Math.round(h)}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
