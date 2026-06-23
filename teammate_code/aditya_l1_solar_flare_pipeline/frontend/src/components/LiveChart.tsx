import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import type { LiveEvent, LiveFrame, LiveInit } from "../api/types";
import { statusColor } from "../lib/format";

export interface LiveChartHandle {
  init: (meta: LiveInit) => void;
  pushFrame: (frame: LiveFrame) => void;
  reset: () => void;
}

const COLORS = {
  sxr: "#3fbdf0",
  hxr: "#f6a04d",
  prob: "#a98bf5",
  grid: "rgba(120,140,170,0.14)",
  axis: "#8aa0c0",
  threshold: "#ffc857",
  cursor: "rgba(255,255,255,0.55)",
};

function bandFill(status: string): string {
  const c = statusColor(status);
  return c + "22"; // ~13% alpha
}

export const LiveChart = forwardRef<LiveChartHandle, { className?: string }>(
  function LiveChart({ className }, ref) {
    const elRef = useRef<HTMLDivElement | null>(null);
    const metaRef = useRef<LiveInit | null>(null);
    const drawnEvents = useRef<Set<string>>(new Set());
    const baseShapes = useRef<any[]>([]);
    const eventShapes = useRef<any[]>([]);
    const cursorRef = useRef<string | null>(null);
    const lastCursorRelayout = useRef(0);

    const buildLayout = (meta: LiveInit) => {
      const classLines = Object.entries(meta.class_thresholds)
        .filter(([letter]) => ["C", "M", "X"].includes(letter))
        .map(([, value]) => ({
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: "y",
          y0: value,
          y1: value,
          line: { color: "rgba(255,200,87,0.25)", width: 1, dash: "dot" },
        }));
      const classAnnotations = Object.entries(meta.class_thresholds)
        .filter(([letter]) => ["C", "M", "X"].includes(letter))
        .map(([letter, value]) => ({
          xref: "paper",
          x: 0.004,
          yref: "y",
          y: value,
          text: letter,
          showarrow: false,
          font: { size: 10, color: "rgba(255,200,87,0.65)" },
          xanchor: "left",
          yanchor: "bottom",
        }));
      const thresholdLine = {
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        yref: "y3",
        y0: meta.threshold,
        y1: meta.threshold,
        line: { color: COLORS.threshold, width: 1.4, dash: "dash" },
      };
      baseShapes.current = [...classLines, thresholdLine];

      return {
        margin: { l: 64, r: 18, t: 10, b: 30 },
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(10,16,28,0.35)",
        font: { color: COLORS.axis, family: "Inter, system-ui", size: 11 },
        showlegend: false,
        hovermode: "x unified",
        xaxis: {
          type: "date",
          domain: [0, 1],
          anchor: "y3",
          range: [meta.t_start, meta.t_end],
          gridcolor: COLORS.grid,
          zeroline: false,
          showspikes: true,
          spikemode: "across",
          spikethickness: 1,
          spikecolor: "rgba(255,255,255,0.25)",
        },
        yaxis: {
          domain: [0.68, 1],
          type: "log",
          title: { text: "SoLEXS SXR (W/m²)", font: { size: 10 } },
          gridcolor: COLORS.grid,
          zeroline: false,
        },
        yaxis2: {
          domain: [0.35, 0.63],
          type: "log",
          title: { text: "HEL1OS HXR (cts/s)", font: { size: 10 } },
          gridcolor: COLORS.grid,
          zeroline: false,
        },
        yaxis3: {
          domain: [0, 0.27],
          range: [0, 1.02],
          title: { text: "P(flare ≤ horizon)", font: { size: 10 } },
          gridcolor: COLORS.grid,
          zeroline: false,
        },
        annotations: classAnnotations,
        shapes: baseShapes.current,
      };
    };

    const composeShapes = () => {
      const shapes = [...baseShapes.current, ...eventShapes.current];
      if (cursorRef.current) {
        shapes.push({
          type: "line",
          xref: "x",
          x0: cursorRef.current,
          x1: cursorRef.current,
          yref: "paper",
          y0: 0,
          y1: 1,
          line: { color: COLORS.cursor, width: 1 },
        });
      }
      return shapes;
    };

    const revealEvent = (ev: LiveEvent) => {
      if (!ev.onset_time || drawnEvents.current.has(ev.event_id)) return;
      drawnEvents.current.add(ev.event_id);
      const end = ev.end_time ?? ev.onset_time;
      eventShapes.current.push({
        type: "rect",
        xref: "x",
        x0: ev.onset_time,
        x1: end,
        yref: "paper",
        y0: 0,
        y1: 1,
        fillcolor: bandFill(ev.status),
        line: { width: 0 },
        layer: "below",
      });
      // Peak marker line on the SXR lane.
      if (ev.peak_time_sxr) {
        eventShapes.current.push({
          type: "line",
          xref: "x",
          x0: ev.peak_time_sxr,
          x1: ev.peak_time_sxr,
          yref: "paper",
          y0: 0.68,
          y1: 1,
          line: { color: statusColor(ev.status), width: 1, dash: "dot" },
        });
      }
    };

    useImperativeHandle(ref, () => ({
      init(meta) {
        metaRef.current = meta;
        drawnEvents.current = new Set();
        eventShapes.current = [];
        cursorRef.current = meta.t_start;
        const traces = [
          {
            name: "SXR",
            x: [] as string[],
            y: [] as number[],
            xaxis: "x",
            yaxis: "y",
            type: "scattergl",
            mode: "lines",
            line: { color: COLORS.sxr, width: 1.4 },
            hovertemplate: "SXR %{y:.2e} W/m²<extra></extra>",
          },
          {
            name: "HXR",
            x: [] as string[],
            y: [] as number[],
            xaxis: "x",
            yaxis: "y2",
            type: "scattergl",
            mode: "lines",
            line: { color: COLORS.hxr, width: 1.4 },
            hovertemplate: "HXR %{y:.1f} cts/s<extra></extra>",
          },
          {
            name: "P",
            x: [] as string[],
            y: [] as number[],
            xaxis: "x",
            yaxis: "y3",
            type: "scattergl",
            mode: "lines",
            line: { color: COLORS.prob, width: 1.8 },
            fill: "tozeroy",
            fillcolor: "rgba(169,139,245,0.12)",
            hovertemplate: "P %{y:.2f}<extra></extra>",
          },
        ];
        Plotly.react(elRef.current, traces, buildLayout(meta), {
          responsive: true,
          displayModeBar: false,
        });
      },

      pushFrame(frame) {
        if (!elRef.current || !metaRef.current) return;
        const xs: (string | null)[] = [];
        const ysS: (number | null)[] = [];
        const xsH: (string | null)[] = [];
        const ysH: (number | null)[] = [];
        const xsP: (string | null)[] = [];
        const ysP: (number | null)[] = [];
        for (const p of frame.points) {
          xs.push(p.t);
          ysS.push(p.sxr);
          xsH.push(p.t);
          ysH.push(p.hxr);
          xsP.push(p.t);
          ysP.push(p.prob ?? null);
          if (p.t) cursorRef.current = p.t;
        }
        Plotly.extendTraces(
          elRef.current,
          { x: [xs, xsH, xsP], y: [ysS, ysH, ysP] },
          [0, 1, 2],
        );

        let needShapes = false;
        for (const ev of frame.fired_events) {
          revealEvent(ev);
          needShapes = true;
        }
        const now = performance.now();
        if (needShapes || now - lastCursorRelayout.current > 90) {
          lastCursorRelayout.current = now;
          Plotly.relayout(elRef.current, { shapes: composeShapes() });
        }
      },

      reset() {
        if (!elRef.current) return;
        drawnEvents.current = new Set();
        eventShapes.current = [];
        cursorRef.current = metaRef.current?.t_start ?? null;
        Plotly.restyle(elRef.current, { x: [[], [], []], y: [[], [], []] }, [0, 1, 2]);
        Plotly.relayout(elRef.current, { shapes: composeShapes() });
      },
    }));

    useEffect(() => {
      const el = elRef.current;
      return () => {
        if (el) Plotly.purge(el);
      };
    }, []);

    return <div ref={elRef} className={className} />;
  },
);
