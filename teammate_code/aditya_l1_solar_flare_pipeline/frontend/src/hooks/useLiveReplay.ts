import { useCallback, useEffect, useRef, useState } from "react";
import { liveSocketUrl } from "../api/client";
import type { LiveEvent, LiveFrame, LiveInit, LiveMessage } from "../api/types";

export type LiveStatus = "connecting" | "live" | "paused" | "ended" | "closed" | "error";

export interface FiredAlert extends LiveEvent {
  key: string;
  receivedAt: number;
}

export interface LiveHandlers {
  onInit?: (meta: LiveInit) => void;
  onFrame?: (frame: LiveFrame) => void;
  onReset?: () => void;
}

export interface LiveReplay {
  status: LiveStatus;
  meta: LiveInit | null;
  speed: number;
  progress: { cursor: number; total: number };
  latest: { time: string | null; sxr: number | null; hxr: number | null; prob: number | null };
  alerts: FiredAlert[];
  error: string | null;
  flashAt: number;
  play: () => void;
  pause: () => void;
  restart: () => void;
  setSpeed: (value: number) => void;
  reconnect: () => void;
}

const STATE_THROTTLE_MS = 120;
const MAX_ALERTS = 60;

export function useLiveReplay(handlers: LiveHandlers): LiveReplay {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  const wsRef = useRef<WebSocket | null>(null);
  const lastStateUpdate = useRef(0);
  const reconnectTimer = useRef<number | null>(null);

  const [status, setStatus] = useState<LiveStatus>("connecting");
  const [meta, setMeta] = useState<LiveInit | null>(null);
  const [speed, setSpeedState] = useState(4);
  const [progress, setProgress] = useState({ cursor: 0, total: 0 });
  const [latest, setLatest] = useState({
    time: null as string | null,
    sxr: null as number | null,
    hxr: null as number | null,
    prob: null as number | null,
  });
  const [alerts, setAlerts] = useState<FiredAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [flashAt, setFlashAt] = useState(0);

  const send = useCallback((payload: object) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }
    setStatus("connecting");
    setError(null);
    setAlerts([]);
    const ws = new WebSocket(liveSocketUrl());
    wsRef.current = ws;

    ws.onmessage = (raw) => {
      const msg = JSON.parse(raw.data) as LiveMessage;
      if (msg.type === "init") {
        setMeta(msg);
        setProgress({ cursor: 0, total: msg.total_frames });
        setStatus("live");
        handlersRef.current.onInit?.(msg);
      } else if (msg.type === "frame") {
        handlersRef.current.onFrame?.(msg);
        if (msg.fired_events.length) {
          const now = Date.now();
          setAlerts((prev) =>
            [
              ...msg.fired_events.map((e) => ({ ...e, key: `${e.event_id}-${now}`, receivedAt: now })),
              ...prev,
            ].slice(0, MAX_ALERTS),
          );
          setFlashAt(now);
        }
        const now = performance.now();
        if (now - lastStateUpdate.current > STATE_THROTTLE_MS) {
          lastStateUpdate.current = now;
          const last = msg.points[msg.points.length - 1];
          if (last) setLatest({ time: last.t, sxr: last.sxr, hxr: last.hxr, prob: last.prob });
          setProgress({ cursor: msg.to, total: msg.total });
          setSpeedState(msg.speed);
          setStatus(msg.paused ? "paused" : "live");
        }
      } else if (msg.type === "reset") {
        setProgress((p) => ({ cursor: 0, total: p.total }));
        setStatus("live");
        handlersRef.current.onReset?.();
      } else if (msg.type === "done") {
        setStatus("ended");
        setProgress((p) => ({ cursor: p.total, total: p.total }));
      } else if (msg.type === "error") {
        setError(msg.detail);
        setStatus("error");
      }
    };

    ws.onerror = () => setError((e) => e ?? "WebSocket connection error");
    ws.onclose = () => {
      setStatus((s) => (s === "error" ? s : "closed"));
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  const play = useCallback(() => {
    send({ action: "resume" });
    setStatus("live");
  }, [send]);

  const pause = useCallback(() => {
    send({ action: "pause" });
    setStatus("paused");
  }, [send]);

  const restart = useCallback(() => {
    setAlerts([]);
    send({ action: "restart" });
  }, [send]);

  const setSpeed = useCallback(
    (value: number) => {
      setSpeedState(value);
      send({ action: "speed", value });
    },
    [send],
  );

  return {
    status, meta, speed, progress, latest, alerts, error, flashAt,
    play, pause, restart, setSpeed, reconnect: connect,
  };
}
