import { useState } from "react";

export function SummaryPanel({ summary }: { summary: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="panel">
      <button
        className="panel-head w-full cursor-pointer text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="panel-title">Pipeline Run Summary</span>
        <span className="text-xs text-slate-500">{open ? "▲ collapse" : "▼ expand"}</span>
      </button>
      {open && (
        <pre className="max-h-80 overflow-auto px-4 py-3 font-mono text-[11px] leading-relaxed text-slate-400">
          {summary?.trim() || "Run the pipeline to generate a summary report."}
        </pre>
      )}
    </div>
  );
}
