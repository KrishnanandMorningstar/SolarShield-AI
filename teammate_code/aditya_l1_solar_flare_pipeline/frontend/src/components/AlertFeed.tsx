import type { FiredAlert } from "../hooks/useLiveReplay";
import { classColor, fmtSci, fmtTime, statusColor, statusLabel } from "../lib/format";

export function AlertFeed({ alerts }: { alerts: FiredAlert[] }) {
  return (
    <div className="panel flex min-h-0 flex-col">
      <div className="panel-head">
        <span className="panel-title">Live Nowcast Feed</span>
        <span className="chip border-white/10 text-slate-400">{alerts.length}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {alerts.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-slate-500">
            Detections will appear here as the replay reaches each flare onset.
          </p>
        ) : (
          <ul className="space-y-2">
            {alerts.map((a) => (
              <li
                key={a.key}
                className="rounded-lg border-l-2 bg-space-800/50 px-3 py-2"
                style={{ borderColor: statusColor(a.status) }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className="chip text-[10px]"
                      style={{
                        color: classColor(a.flare_class),
                        borderColor: classColor(a.flare_class) + "66",
                        background: classColor(a.flare_class) + "14",
                      }}
                    >
                      {a.flare_class ?? "—"}
                    </span>
                    <span className="text-xs font-semibold text-slate-200">{a.event_id}</span>
                  </div>
                  <span
                    className="text-[10px] font-medium uppercase tracking-wide"
                    style={{ color: statusColor(a.status) }}
                  >
                    {statusLabel(a.status)}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-slate-400">
                  <span>onset {fmtTime(a.onset_time)}</span>
                  {a.peak_sxr_flux_w_m2 != null && (
                    <span>SXR {fmtSci(a.peak_sxr_flux_w_m2)} W/m²</span>
                  )}
                  {a.peak_hxr_counts_s != null && (
                    <span>HXR {fmtSci(a.peak_hxr_counts_s, 0)} cts/s</span>
                  )}
                  {a.hxr_leads_sxr_minutes != null && (
                    <span className="text-hxr">HXR leads {a.hxr_leads_sxr_minutes}m</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
