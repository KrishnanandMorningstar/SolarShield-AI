import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { LiveChartHandle } from "./components/LiveChart";
import { AlertFeed } from "./components/AlertFeed";
import { CatalogueTable } from "./components/CatalogueTable";
import { ForecastGauge } from "./components/ForecastGauge";
import { KpiStrip } from "./components/KpiStrip";
import { LiveMonitor } from "./components/LiveMonitor";
import { RunControls } from "./components/RunControls";
import { SummaryPanel } from "./components/SummaryPanel";
import { TopBar } from "./components/TopBar";
import { useLiveReplay } from "./hooks/useLiveReplay";
import { usePoll } from "./hooks/usePoll";

export default function App() {
  const chartRef = useRef<LiveChartHandle>(null);
  const [version, setVersion] = useState<string>();

  const live = useLiveReplay({
    onInit: (m) => chartRef.current?.init(m),
    onFrame: (f) => chartRef.current?.pushFrame(f),
    onReset: () => chartRef.current?.reset(),
  });

  const metrics = usePoll(api.metrics, 4000);
  const catalogue = usePoll(api.catalogue, 6000);
  const alerts = usePoll(api.alerts, 6000);
  const runStatus = usePoll(api.runStatus, 3000);
  const files = usePoll(api.files, 10000);
  const [summary, setSummary] = useState<string | null>(null);

  useEffect(() => {
    api.health().then((h) => setVersion(h.version)).catch(() => {});
    api.summary().then(setSummary).catch(() => setSummary(null));
  }, []);

  // When a pipeline run finishes, refresh artifacts and reconnect the live feed
  // so it streams the freshly generated light curve.
  const lastFinished = useRef<string | null>(null);
  const wasRunning = useRef(false);
  useEffect(() => {
    const rs = runStatus.data;
    if (!rs) return;
    if (wasRunning.current && !rs.running) {
      metrics.refresh();
      catalogue.refresh();
      alerts.refresh();
      api.summary().then(setSummary).catch(() => setSummary(null));
      if (rs.finished_at !== lastFinished.current) {
        lastFinished.current = rs.finished_at;
        live.reconnect();
      }
    }
    wasRunning.current = rs.running;
  }, [runStatus.data, metrics, catalogue, alerts, live]);

  const refreshAll = () => {
    metrics.refresh();
    catalogue.refresh();
    alerts.refresh();
    runStatus.refresh();
    files.refresh();
  };

  const events = catalogue.data?.master ?? [];
  const alertList = alerts.data?.alerts ?? [];
  const threshold = live.meta?.threshold ?? 0.7;
  const horizon = live.meta?.horizon_min ?? 30;

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar
        status={live.status}
        source={live.meta?.source ?? null}
        replayTime={live.latest.time}
        version={version}
      />

      <main className="mx-auto w-full max-w-[1600px] flex-1 space-y-4 px-4 py-4 lg:px-6">
        <KpiStrip metrics={metrics.data} />

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="min-h-[520px] xl:col-span-2">
            <LiveMonitor live={live} chartRef={chartRef} />
          </div>
          <div className="flex flex-col gap-4">
            <ForecastGauge probability={live.latest.prob} threshold={threshold} horizonMin={horizon} />
            <div className="min-h-[260px] flex-1">
              <AlertFeed alerts={live.alerts} />
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <div className="xl:col-span-2">
            <CatalogueTable events={events} alerts={alertList} />
          </div>
          <RunControls runStatus={runStatus.data} files={files.data} onChanged={refreshAll} />
        </div>

        <SummaryPanel summary={summary} />

        <footer className="pb-4 pt-2 text-center text-[11px] text-slate-600">
          Aditya-L1 Solar Flare Operations · SoLEXS + HEL1OS · Problem Statement 15 ·
          nowcasting &amp; forecasting pipeline
        </footer>
      </main>
    </div>
  );
}
