import type { Metrics } from "../api/types";
import { fmtNum } from "../lib/format";

interface Card {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}

function Stat({ label, value, sub, accent }: Card) {
  return (
    <div className="panel px-4 py-3">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

export function KpiStrip({ metrics }: { metrics: Metrics | null }) {
  const m = metrics;
  const pct = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v.toFixed(1)}%`;
  const lead = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : `${v.toFixed(1)}m`;
  const auc = (v: number | null | undefined) =>
    v === null || v === undefined ? "—" : v.toFixed(3);

  const cards: Card[] = [
    { label: "Master Events", value: fmtNum(m?.master_events ?? 0, 0), sub: "nowcast catalogue" },
    { label: "Confirmed", value: fmtNum(m?.confirmed ?? 0, 0), accent: "#ff5d6c", sub: "SXR+HXR coincident" },
    { label: "SXR only", value: fmtNum(m?.sxr_only ?? 0, 0), accent: "#3fbdf0", sub: "thermal" },
    { label: "HXR only", value: fmtNum(m?.hxr_only ?? 0, 0), accent: "#f6a04d", sub: "impulsive" },
    { label: "Forecast Alerts", value: fmtNum(m?.alert_episodes ?? 0, 0), accent: "#a98bf5", sub: "episodes" },
    { label: "True Positive", value: pct(m?.tpr), accent: "#3ddc97", sub: "walk-forward" },
    { label: "False Alarm", value: pct(m?.far), accent: "#ffc857", sub: "walk-forward" },
    { label: "Median Lead", value: lead(m?.median_lead_min), accent: "#3fbdf0", sub: "before peak" },
    { label: "Test AUC", value: auc(m?.test_auc), sub: `val ${auc(m?.val_auc)}` },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9">
      {cards.map((c) => (
        <Stat key={c.label} {...c} />
      ))}
    </div>
  );
}
