/* REST + WebSocket client. Reconnects with backoff so a dropped socket during
   a demo heals itself instead of freezing the dashboard on a stale frame. */

export const LEVELS = ["NORMAL", "ADVISORY", "WATCH", "WARNING", "EMERGENCY"];

export const LEVEL_COLOR = {
  NORMAL: "var(--lv-normal)",
  ADVISORY: "var(--lv-advisory)",
  WATCH: "var(--lv-watch)",
  WARNING: "var(--lv-warning)",
  EMERGENCY: "var(--lv-emergency)",
};

/* Hue never carries meaning alone - every band also ships this glyph. */
export const LEVEL_ICON = {
  NORMAL: "●", ADVISORY: "▲", WATCH: "▲", WARNING: "■", EMERGENCY: "✖",
};

export const json = (path, opts) =>
  fetch(path, opts).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  });

export const post = (path) => json(path, { method: "POST" });

export function connect({ onState, onAlert, onStatus }) {
  let socket = null;
  let attempt = 0;
  let closed = false;

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
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

export const fmtNum = (n) => (n == null ? "—" : n.toLocaleString("en-IN"));
