import type { LiveStatus } from "../hooks/useLiveReplay";
import { fmtTime } from "../lib/format";

const STATUS_META: Record<LiveStatus, { label: string; color: string; pulse: boolean }> = {
  connecting: { label: "Connecting", color: "#ffc857", pulse: true },
  live: { label: "Live", color: "#3ddc97", pulse: true },
  paused: { label: "Paused", color: "#ffc857", pulse: false },
  ended: { label: "Replay complete", color: "#7fa6d0", pulse: false },
  closed: { label: "Disconnected", color: "#ff5d6c", pulse: false },
  error: { label: "Error", color: "#ff5d6c", pulse: false },
};

interface Props {
  status: LiveStatus;
  source: string | null;
  replayTime: string | null;
  version?: string;
}

export function TopBar({ status, source, replayTime, version }: Props) {
  const meta = STATUS_META[status];
  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/5 bg-space-900/70 px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-gradient-to-br from-hxr/30 to-danger/30 shadow-glow">
          <img src="/sun.svg" alt="" className="h-7 w-7" />
        </div>
        <div>
          <h1 className="text-lg font-semibold leading-tight text-white">
            Aditya-L1 · Flare Operations Center
          </h1>
          <p className="text-xs text-slate-400">
            SoLEXS soft X-ray + HEL1OS hard X-ray · nowcasting &amp; forecasting
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-2 rounded-lg border border-white/5 bg-space-850/70 px-3 py-2 sm:flex">
          <span className="stat-label">Replay&nbsp;UTC</span>
          <span className="font-mono text-sm text-slate-100">{fmtTime(replayTime)}</span>
        </div>
        {source && (
          <span className="chip border-sxr/30 bg-sxr/10 text-sxr">
            {source === "real" ? "Real ISSDC data" : "Synthetic showcase"}
          </span>
        )}
        <div
          className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${
            meta.pulse ? "animate-pulsering" : ""
          }`}
          style={{ borderColor: meta.color + "55", background: meta.color + "12" }}
        >
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{ background: meta.color, boxShadow: `0 0 10px ${meta.color}` }}
          />
          <span className="text-sm font-semibold" style={{ color: meta.color }}>
            {meta.label}
          </span>
        </div>
        {version && <span className="hidden text-xs text-slate-500 md:inline">v{version}</span>}
      </div>
    </header>
  );
}
