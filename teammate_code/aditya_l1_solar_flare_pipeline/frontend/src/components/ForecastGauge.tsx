interface Props {
  probability: number | null;
  threshold: number;
  horizonMin: number;
}

export function ForecastGauge({ probability, threshold, horizonMin }: Props) {
  const p = probability ?? 0;
  const pctVal = Math.max(0, Math.min(1, p));
  const armed = p >= threshold;
  const radius = 52;
  const circ = 2 * Math.PI * radius;
  const dash = circ * pctVal;
  const color = armed ? "#ff5d6c" : p > threshold * 0.6 ? "#ffc857" : "#3ddc97";

  return (
    <div className="panel flex flex-col">
      <div className="panel-head">
        <span className="panel-title">Forecast Probability</span>
        <span className="text-[11px] text-slate-500">next {horizonMin || 30} min</span>
      </div>
      <div className="flex items-center gap-4 p-4">
        <div className="relative grid h-32 w-32 shrink-0 place-items-center">
          <svg viewBox="0 0 120 120" className="h-32 w-32 -rotate-90">
            <circle cx="60" cy="60" r={radius} fill="none" stroke="#1b2740" strokeWidth="10" />
            <circle
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={color}
              strokeWidth="10"
              strokeLinecap="round"
              strokeDasharray={`${dash} ${circ}`}
              style={{ transition: "stroke-dasharray 0.2s linear, stroke 0.3s" }}
            />
          </svg>
          <div className="absolute text-center">
            <div className="font-mono text-2xl font-semibold" style={{ color }}>
              {probability === null ? "—" : (p * 100).toFixed(0)}
              <span className="text-sm">%</span>
            </div>
          </div>
        </div>
        <div className="flex-1 space-y-2 text-sm">
          <div
            className={`chip ${
              armed
                ? "border-danger/50 bg-danger/15 text-danger animate-pulsering"
                : "border-good/40 bg-good/10 text-good"
            }`}
          >
            {armed ? "⚠ ALERT ARMED" : "● Nominal"}
          </div>
          <div className="text-xs text-slate-400">
            Alert threshold
            <span className="ml-2 font-mono text-slate-200">{(threshold * 100).toFixed(0)}%</span>
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500">
            Probability that a C-class or stronger flare begins within the next{" "}
            {horizonMin || 30} minutes, from SXR/HXR precursor features.
          </p>
        </div>
      </div>
    </div>
  );
}
