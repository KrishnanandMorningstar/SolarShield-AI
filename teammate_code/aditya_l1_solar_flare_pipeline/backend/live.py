"""
live.py
========
WebSocket "live replay" engine.

Real Aditya-L1 L1 data is not a live stream on a laptop, so for an operations
demo we replay the already-processed light curve through a WebSocket in
accelerated time. The client watches the SoLEXS/HEL1OS traces advance and sees
nowcast detections and forecast-probability crossings fire live — exactly the
behaviour an operator would see against a real downlink.

Protocol (server -> client):
  {"type": "init",  ...}    once, on connect: bounds, threshold, full event list
  {"type": "frame", ...}    repeatedly: a batch of new light-curve points
  {"type": "done"}          replay reached the end

Protocol (client -> server):
  {"action": "pause" | "resume" | "restart"}
  {"action": "speed", "value": <int>}   # frames emitted per 30 Hz tick
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import numpy as np
import pandas as pd
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from teammate_code.aditya_l1_solar_flare_pipeline.pipeline import config
from . import services

TARGET_FRAMES = 3000          # replay resolution (downsampled from native cadence)
TICK_HZ = 30                  # wall-clock tick rate
DEFAULT_SPEED = 4             # light-curve points emitted per tick
MAX_SPEED = 64


def _iso(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    return None if pd.isna(ts) else ts.isoformat()


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def _prepare_replay() -> dict[str, Any]:
    """Build the full replay payload once: frames, events, metadata."""
    source, df = services.load_best_light_curve()
    df = services.downsample(df, TARGET_FRAMES)
    df[config.TIME_COL] = pd.to_datetime(df[config.TIME_COL], utc=True)

    # Attach full-timeline forecast probability (nearest decision window).
    prob_records = services.read_forecast_timeline()
    threshold = config.ALERT_PROBABILITY_THRESHOLD
    horizon = config.FORECAST_HORIZON_MIN
    if prob_records:
        prob_df = pd.DataFrame(prob_records)
        prob_df["time"] = pd.to_datetime(prob_df["time"], utc=True, errors="coerce")
        prob_df = prob_df.dropna(subset=["time"]).sort_values("time")
        if "threshold" in prob_df.columns and len(prob_df):
            threshold = float(prob_df["threshold"].iloc[0])
        if "forecast_horizon_min" in prob_df.columns and len(prob_df):
            horizon = float(prob_df["forecast_horizon_min"].iloc[0])
        merged = pd.merge_asof(
            df[[config.TIME_COL]].sort_values(config.TIME_COL),
            prob_df[["time", "probability"]].rename(columns={"time": config.TIME_COL}),
            on=config.TIME_COL, direction="nearest",
            tolerance=pd.Timedelta(minutes=5),
        )
        prob_series = merged["probability"].to_numpy()
    else:
        prob_series = np.full(len(df), np.nan)

    times = df[config.TIME_COL].to_numpy()
    sxr = df[config.SXR_COL].to_numpy()
    hxr = df[config.HXR_COL].to_numpy()

    frames = [
        {"t": _iso(times[i]), "sxr": _num(sxr[i]), "hxr": _num(hxr[i]), "prob": _num(prob_series[i])}
        for i in range(len(df))
    ]

    # Master catalogue events, with onset bucketed to the frame at which they fire.
    events = []
    cat = services.read_catalogue()["master"]
    frame_times = pd.to_datetime(df[config.TIME_COL], utc=True).reset_index(drop=True)
    for ev in cat:
        onset = pd.to_datetime(ev.get("onset_time"), utc=True, errors="coerce")
        fire_idx = int(frame_times.searchsorted(onset)) if not pd.isna(onset) else None
        if fire_idx is not None and fire_idx >= len(frames):
            fire_idx = len(frames) - 1
        events.append({
            "event_id": ev.get("event_id"),
            "status": ev.get("status"),
            "confidence": ev.get("confidence"),
            "flare_class": ev.get("flare_class"),
            "onset_time": _iso(ev.get("onset_time")),
            "peak_time_sxr": _iso(ev.get("peak_time_sxr")),
            "peak_time_hxr": _iso(ev.get("peak_time_hxr")),
            "end_time": _iso(ev.get("end_time")),
            "peak_sxr_flux_w_m2": _num(ev.get("peak_sxr_flux_w_m2")),
            "peak_hxr_counts_s": _num(ev.get("peak_hxr_counts_s")),
            "hxr_leads_sxr_minutes": _num(ev.get("hxr_leads_sxr_minutes")),
            "fire_idx": fire_idx,
        })

    return {
        "source": source,
        "threshold": threshold,
        "horizon_min": horizon,
        "class_thresholds": config.FLARE_CLASS_THRESHOLDS,
        "t_start": frames[0]["t"] if frames else None,
        "t_end": frames[-1]["t"] if frames else None,
        "total_frames": len(frames),
        "frames": frames,
        "events": events,
    }


class _Controls:
    """Mutable shared control state driven by inbound client messages."""

    def __init__(self) -> None:
        self.paused = False
        self.speed = DEFAULT_SPEED
        self.restart = False
        self.closed = False


async def _receive_loop(ws: WebSocket, controls: _Controls) -> None:
    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")
            if action == "pause":
                controls.paused = True
            elif action == "resume":
                controls.paused = False
            elif action == "restart":
                controls.restart = True
                controls.paused = False
            elif action == "speed":
                try:
                    controls.speed = max(1, min(MAX_SPEED, int(msg.get("value", DEFAULT_SPEED))))
                except (TypeError, ValueError):
                    pass
    except (WebSocketDisconnect, RuntimeError):
        controls.closed = True


async def run_live_replay(ws: WebSocket) -> None:
    await ws.accept()
    try:
        payload = await asyncio.to_thread(_prepare_replay)
    except FileNotFoundError as exc:
        await ws.send_json({"type": "error", "detail": str(exc)})
        await ws.close()
        return

    frames = payload.pop("frames")
    events_by_frame: dict[int, list[dict]] = {}
    for ev in payload["events"]:
        idx = ev.get("fire_idx")
        if idx is not None:
            events_by_frame.setdefault(idx, []).append(ev)

    await ws.send_json({"type": "init", **payload})

    controls = _Controls()
    receiver = asyncio.create_task(_receive_loop(ws, controls))
    tick = 1.0 / TICK_HZ

    try:
        cursor = 0
        ended = False
        while not controls.closed:
            if controls.restart:
                controls.restart = False
                cursor = 0
                ended = False
                await ws.send_json({"type": "reset"})

            if controls.paused or ended:
                # Idle: hold the final frame (or paused state) until a control
                # message (resume / restart) or disconnect arrives.
                await asyncio.sleep(tick)
                continue

            step = max(1, controls.speed)
            end = min(len(frames), cursor + step)
            fired = [ev for i in range(cursor, end) for ev in events_by_frame.get(i, [])]
            await ws.send_json({
                "type": "frame",
                "from": cursor,
                "to": end,
                "total": len(frames),
                "points": frames[cursor:end],
                "fired_events": fired,
                "speed": controls.speed,
                "paused": controls.paused,
            })
            cursor = end
            if cursor >= len(frames):
                ended = True
                await ws.send_json({"type": "done"})
            await asyncio.sleep(tick)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        receiver.cancel()
        with contextlib.suppress(Exception):
            await receiver
        if ws.application_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(RuntimeError):
                await ws.close()
