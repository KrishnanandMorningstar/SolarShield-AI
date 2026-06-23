import { useRef, useState, type RefObject } from "react";
import { api } from "../api/client";
import type { FilesResponse, RunStatus } from "../api/types";
import { fmtTime } from "../lib/format";

interface Props {
  runStatus: RunStatus | null;
  files: FilesResponse | null;
  onChanged: () => void;
}

export function RunControls({ runStatus, files, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const solexsRef = useRef<HTMLInputElement>(null);
  const hel1osRef = useRef<HTMLInputElement>(null);
  const running = runStatus?.running ?? false;

  const act = async (fn: () => Promise<void>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const doUpload = async (payload: "solexs" | "hel1os", input: HTMLInputElement | null) => {
    const file = input?.files?.[0];
    if (!file) {
      setMsg(`Choose a ${payload.toUpperCase()} file first`);
      return;
    }
    await act(async () => {
      await api.upload(payload, file);
      if (input) input.value = "";
    }, `Uploaded ${file.name}`);
  };

  return (
    <div className="panel flex flex-col">
      <div className="panel-head">
        <span className="panel-title">Pipeline Control</span>
        <span
          className={`chip ${
            running
              ? "border-warn/40 bg-warn/10 text-warn animate-pulsering"
              : runStatus?.error
                ? "border-danger/40 bg-danger/10 text-danger"
                : "border-good/40 bg-good/10 text-good"
          }`}
        >
          {running ? `Running ${runStatus?.source ?? ""}` : runStatus?.error ? "Last run failed" : "Idle"}
        </span>
      </div>

      <div className="space-y-3 p-4">
        <div className="flex flex-wrap gap-2">
          <button
            className="btn btn-primary"
            disabled={busy || running}
            onClick={() => act(() => api.run("synthetic"), "Synthetic run started")}
          >
            ▶ Run Synthetic
          </button>
          <button
            className="btn"
            disabled={busy || running}
            onClick={() => act(() => api.run("real"), "Real run started")}
          >
            ▶ Run Real
          </button>
          <a className="btn" href="/api/dashboard" target="_blank" rel="noreferrer">
            ⤢ Plotly Dashboard
          </a>
        </div>

        <div className="grid grid-cols-1 gap-2 border-t border-white/5 pt-3 sm:grid-cols-2">
          <UploadRow
            label="SoLEXS L1"
            count={files?.solexs.length ?? 0}
            inputRef={solexsRef}
            onUpload={() => doUpload("solexs", solexsRef.current)}
            disabled={busy}
          />
          <UploadRow
            label="HEL1OS L1"
            count={files?.hel1os.length ?? 0}
            inputRef={hel1osRef}
            onUpload={() => doUpload("hel1os", hel1osRef.current)}
            disabled={busy}
          />
        </div>

        {msg && <p className="text-xs text-slate-400">{msg}</p>}

        <button
          className="text-[11px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
          onClick={() => setShowLog((s) => !s)}
        >
          {showLog ? "Hide" : "Show"} run log
          {runStatus?.finished_at ? ` · finished ${fmtTime(runStatus.finished_at)}` : ""}
        </button>
        {showLog && (
          <pre className="max-h-48 overflow-auto rounded-lg border border-white/5 bg-space-950/70 p-3 font-mono text-[11px] leading-relaxed text-slate-400">
            {runStatus?.log?.trim() || "No run has been started in this server session."}
          </pre>
        )}
      </div>
    </div>
  );
}

function UploadRow({
  label,
  count,
  inputRef,
  onUpload,
  disabled,
}: {
  label: string;
  count: number;
  inputRef: RefObject<HTMLInputElement>;
  onUpload: () => void;
  disabled: boolean;
}) {
  return (
    <div className="rounded-lg border border-white/5 bg-space-800/40 p-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[11px] font-medium text-slate-300">{label}</span>
        <span className="chip border-white/10 text-[10px] text-slate-400">{count} files</span>
      </div>
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          type="file"
          aria-label={`Choose ${label} file to upload`}
          className="block w-full text-[11px] text-slate-400 file:mr-2 file:rounded file:border-0 file:bg-space-600 file:px-2 file:py-1 file:text-[11px] file:text-slate-200"
        />
        <button className="btn px-2 py-1 text-xs" onClick={onUpload} disabled={disabled}>
          Upload
        </button>
      </div>
    </div>
  );
}
