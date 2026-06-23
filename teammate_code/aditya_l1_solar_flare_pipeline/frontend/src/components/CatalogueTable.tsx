import { useState, type ReactNode } from "react";
import type { ForecastAlert, MasterEvent } from "../api/types";
import { classColor, fmtSci, fmtTime, statusColor, statusLabel } from "../lib/format";

interface Props {
  events: MasterEvent[];
  alerts: ForecastAlert[];
}

export function CatalogueTable({ events, alerts }: Props) {
  const [tab, setTab] = useState<"catalogue" | "alerts">("catalogue");

  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="panel-head">
        <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-space-800/60 p-1">
          <TabButton active={tab === "catalogue"} onClick={() => setTab("catalogue")}>
            Nowcast Catalogue ({events.length})
          </TabButton>
          <TabButton active={tab === "alerts"} onClick={() => setTab("alerts")}>
            Forecast Alerts ({alerts.length})
          </TabButton>
        </div>
      </div>
      <div className="max-h-[420px] min-h-0 flex-1 overflow-auto">
        {tab === "catalogue" ? (
          <CatalogueRows events={events} />
        ) : (
          <AlertRows alerts={alerts} />
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded px-3 py-1.5 text-xs font-medium transition ${
        active ? "bg-sxr/20 text-sxr" : "text-slate-400 hover:text-slate-200"
      }`}
    >
      {children}
    </button>
  );
}

function CatalogueRows({ events }: { events: MasterEvent[] }) {
  const rows = [...events].reverse();
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-space-850 text-[10px] uppercase tracking-wider text-slate-500">
        <tr>
          <th className="table-cell">ID</th>
          <th className="table-cell">Status</th>
          <th className="table-cell">Class</th>
          <th className="table-cell">Onset (UTC)</th>
          <th className="table-cell text-right">Peak SXR</th>
          <th className="table-cell text-right">Peak HXR</th>
          <th className="table-cell text-right">HXR lead</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td className="table-cell text-slate-500" colSpan={7}>
              No events yet — run the pipeline.
            </td>
          </tr>
        )}
        {rows.map((e) => (
          <tr key={e.event_id} className="border-t border-white/5 hover:bg-white/[0.03]">
            <td className="table-cell font-mono text-slate-300">{e.event_id}</td>
            <td className="table-cell">
              <span
                className="chip text-[10px]"
                style={{ color: statusColor(e.status), borderColor: statusColor(e.status) + "55" }}
              >
                {statusLabel(e.status)}
              </span>
            </td>
            <td className="table-cell font-semibold" style={{ color: classColor(e.flare_class) }}>
              {e.flare_class ?? "—"}
            </td>
            <td className="table-cell font-mono text-slate-400">{fmtTime(e.onset_time)}</td>
            <td className="table-cell text-right font-mono text-slate-300">
              {fmtSci(e.peak_sxr_flux_w_m2)}
            </td>
            <td className="table-cell text-right font-mono text-slate-300">
              {fmtSci(e.peak_hxr_counts_s, 0)}
            </td>
            <td className="table-cell text-right font-mono text-hxr">
              {e.hxr_leads_sxr_minutes != null && e.hxr_leads_sxr_minutes !== ""
                ? `${e.hxr_leads_sxr_minutes}m`
                : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AlertRows({ alerts }: { alerts: ForecastAlert[] }) {
  const rows = [...alerts].reverse();
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-space-850 text-[10px] uppercase tracking-wider text-slate-500">
        <tr>
          <th className="table-cell">Alert</th>
          <th className="table-cell">Start (UTC)</th>
          <th className="table-cell">Peak (UTC)</th>
          <th className="table-cell text-right">Peak P</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td className="table-cell text-slate-500" colSpan={4}>
              No forecast alert episodes.
            </td>
          </tr>
        )}
        {rows.map((a, i) => (
          <tr key={a.alert_id ?? i} className="border-t border-white/5 hover:bg-white/[0.03]">
            <td className="table-cell font-mono text-slate-300">{a.alert_id ?? `A${i + 1}`}</td>
            <td className="table-cell font-mono text-slate-400">{fmtTime(a.start_time)}</td>
            <td className="table-cell font-mono text-slate-400">{fmtTime(a.peak_time)}</td>
            <td className="table-cell text-right font-mono text-fcast">
              {fmtSci(a.peak_probability, 2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
