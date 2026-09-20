/* Risk trend chart: the fused score against the rainfall-only counterfactual.

   One y-axis only (all four series are the same 0-100 unit, so there is no
   excuse for a second scale). Legend always on; the two headline series are
   also direct-labelled at the line end, so identity never rests on colour. */

const CSS = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/** Draws "PRAHARI 82 / LEGACY 3" at the right-hand end of each line. */
const endLabels = {
  id: "endLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.font = "600 11px system-ui, -apple-system, sans-serif";
    ctx.textBaseline = "middle";
    chart.data.datasets.forEach((ds, i) => {
      if (!ds.showLabel) return;
      const meta = chart.getDatasetMeta(i);
      const last = meta.data[meta.data.length - 1];
      if (!last) return;
      const val = ds.data[ds.data.length - 1];
      if (val == null) return;
      ctx.fillStyle = ds.borderColor;
      ctx.fillText(` ${Math.round(val)}`, last.x + 3, last.y);
    });
    ctx.restore();
  },
};

export class TrendChart {
  constructor(canvasId) {
    const ctx = document.getElementById(canvasId).getContext("2d");
    this.chart = new Chart(ctx, {
      type: "line",
      plugins: [endLabels],
      data: { labels: [], datasets: this._datasets() },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 220 },
        interaction: { mode: "index", intersect: false },
        layout: { padding: { right: 26 } },
        scales: {
          y: {
            min: 0, max: 100,
            ticks: { color: CSS("--ink-muted"), font: { size: 10 }, stepSize: 25 },
            grid: { color: CSS("--grid"), drawBorder: false },
            title: { display: true, text: "Risk score", color: CSS("--ink-muted"), font: { size: 10 } },
          },
          x: {
            ticks: { color: CSS("--ink-muted"), font: { size: 9 }, maxTicksLimit: 7, autoSkip: true },
            grid: { display: false },
          },
        },
        plugins: {
          legend: {
            display: true, position: "bottom",
            labels: {
              color: CSS("--ink-2"), boxWidth: 9, boxHeight: 9, usePointStyle: true,
              pointStyle: "rectRounded", font: { size: 10.5 }, padding: 12,
            },
          },
          tooltip: {
            backgroundColor: CSS("--surface-3"),
            titleColor: CSS("--ink"), bodyColor: CSS("--ink-2"),
            borderColor: CSS("--hairline"), borderWidth: 1, padding: 9,
            callbacks: { label: (c) => ` ${c.dataset.label}: ${Math.round(c.parsed.y)}` },
          },
        },
      },
    });
    this._bands();
  }

  _datasets() {
    const base = { tension: 0.3, pointRadius: 0, pointHoverRadius: 5, borderWidth: 2 };
    return [
      { ...base, label: "Prahari (dual-channel)", borderColor: CSS("--s-fused"),
        backgroundColor: "transparent", data: [], borderWidth: 2.5, showLabel: true },
      { ...base, label: "Legacy (rainfall only)", borderColor: CSS("--s-legacy"),
        backgroundColor: "transparent", data: [], borderDash: [5, 4], showLabel: true },
      { ...base, label: "Channel A · hydrology", borderColor: CSS("--s-hydro"),
        backgroundColor: "transparent", data: [], borderWidth: 1.5 },
      { ...base, label: "Channel B · ground motion", borderColor: CSS("--s-geo"),
        backgroundColor: "transparent", data: [], borderWidth: 1.5 },
    ];
  }

  /** Faint horizontal band markers at the alert thresholds. */
  _bands() {
    this.bandPlugin = {
      id: "bands",
      beforeDatasetsDraw: (chart) => {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        const marks = [
          [55, CSS("--lv-watch")], [70, CSS("--lv-warning")], [85, CSS("--lv-emergency")],
        ];
        ctx.save();
        marks.forEach(([v, c]) => {
          const y = scales.y.getPixelForValue(v);
          ctx.strokeStyle = c; ctx.globalAlpha = 0.22; ctx.lineWidth = 1;
          ctx.setLineDash([3, 4]);
          ctx.beginPath(); ctx.moveTo(chartArea.left, y); ctx.lineTo(chartArea.right, y); ctx.stroke();
        });
        ctx.restore();
      },
    };
    this.chart.config.plugins.push(this.bandPlugin);
  }

  update(history) {
    // Wall-clock labels are the most informative in live mode, but scenario
    // stepping can land many samples inside the same second, which renders as
    // a row of identical ticks. Fall back to a relative index when that happens.
    let labels = history.map((h) => new Date(h.created_at).toLocaleTimeString("en-GB", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }));
    if (new Set(labels).size < 3) {
      const n = history.length;
      labels = history.map((_, i) => (i === n - 1 ? "now" : `t−${n - 1 - i}`));
    }
    this.chart.data.labels = labels;
    this.chart.data.datasets[0].data = history.map((h) => h.score);
    this.chart.data.datasets[1].data = history.map((h) => h.legacy_score);
    this.chart.data.datasets[2].data = history.map((h) => h.hydro);
    this.chart.data.datasets[3].data = history.map((h) => h.geo);
    this.chart.update("none");
  }

  /** Accessible equivalent of the plot - required, not optional. */
  tableHTML(history) {
    if (!history.length) return '<p class="empty">No samples yet.</p>';
    const rows = history.slice(-30).reverse().map((h) => `
      <tr><td>${new Date(h.created_at).toLocaleTimeString("en-GB")}</td>
      <td>${Math.round(h.score)}</td><td>${Math.round(h.legacy_score)}</td>
      <td>${Math.round(h.hydro)}</td><td>${Math.round(h.geo)}</td><td>${h.level}</td></tr>`).join("");
    return `<table><thead><tr><th>Time</th><th>Prahari</th><th>Legacy</th>
      <th>Hydro</th><th>Geo</th><th>Level</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
}
