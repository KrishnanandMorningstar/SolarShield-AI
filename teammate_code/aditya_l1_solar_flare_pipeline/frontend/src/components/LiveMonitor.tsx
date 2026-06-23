import { useEffect, useState, type RefObject } from "react";
import type { LiveChartHandle } from "./LiveChart";
import { LiveChart } from "./LiveChart";
import type { LiveReplay } from "../hooks/useLiveReplay";
import { fmtTime } from "../lib/format";

const SPEEDS = [1, 4, 8, 16, 32];

interface Props {
  live: LiveReplay;
  chartRef: RefObject<LiveChartHandle>;
}

export function LiveMonitor({ live, chartRef }: Props) {
  const { status, progress, speed, flashAt } = live;
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (!flashAt) return;
    setFlash(true);
    const id = window.setTimeout(() => setFlash(false), 900);
    return () => window.clearTimeout(id);
  }, [flashAt]);

  const pct = progress.total ? Math.min(100, (progress.cursor / progress.total) * 100) : 0;
  const playing = status === "live";
  const noData = status === "error";

  return (
    <section className="panel relative flex h-full flex-col overflow-hidden">
      <div className="panel-head">
        <div className="flex items-center gap-2">
          <span className="panel-title">Live X-ray Monitor</span>
          <span className="text-[11px] text-slate-500">SoLEXS · HEL1OS · Forecast</span>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <Legend color="#3fbdf0" label="SXR" />
          <Legend color="#f6a04d" label="HXR" />
          <Legend color="#a98bf5" label="P(flare)" />
          <Legend color="#ffc857" label="Alert thr." dash />
        </div>
      </div>

      {flash && (
        <div className="pointer-events-none absolute inset-0 z-10 animate-flash border-2 border-danger/60" />
      )}

      <div className="relative min-h-[360px] flex-1">
        {noData && (
          <div className="absolute inset-0 z-10 grid place-items-center px-6 text-center">
            <div>
              <p className="text-sm font-semibold text-danger">{live.error}</p>
              <p className="mt-1 text-xs text-slate-400">
                Run the pipeline first (synthetic showcase) to generate a light curve.
              </p>
            </div>
          </div>
        )}
        <LiveChart ref={chartRef} className="h-full w-full" />
      </div>

      {/* Transport controls */}
      <div className="flex flex-wrap items-center gap-3 border-t border-white/5 px-4 py-3">
        <button
          className="btn btn-primary"
          onClick={() => (playing ? live.pause() : live.play())}
          disabled={noData}
        >
          {playing ? "❚❚ Pause" : "▶ Play"}
        </button>
        <button className="btn" onClick={live.restart} disabled={noData}>
          ↻ Restart
        </button>

        <div className="flex items-center gap-1 rounded-lg border border-white/10 bg-space-800/60 p-1">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => live.setSpeed(s)}
              className={`rounded px-2 py-1 text-xs font-medium transition ${
                speed === s ? "bg-sxr/25 text-sxr" : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {s}×
            </button>
          ))}
        </div>

        <div className="ml-auto flex min-w-[180px] flex-1 items-center gap-3">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-space-700">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sxr to-fcast transition-[width] duration-200"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="font-mono text-xs text-slate-400">{pct.toFixed(0)}%</span>
        </div>
        <span className="font-mono text-xs text-slate-500">{fmtTime(live.latest.time)}</span>
      </div>
    </section>
  );
}

function Legend({ color, label, dash }: { color: string; label: string; dash?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 text-slate-400">
      <span
        className="inline-block h-0.5 w-4 rounded"
        style={{
          background: dash
            ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 7px)`
            : color,
        }}
      />
      {label}
    </span>
  );
}
