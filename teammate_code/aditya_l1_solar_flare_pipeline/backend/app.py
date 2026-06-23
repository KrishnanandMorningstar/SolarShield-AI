"""
app.py
=======
FastAPI application: REST API + live-replay WebSocket + static SPA hosting.

Run (production / demo, serves the built React app):
    uvicorn backend.app:app --host 127.0.0.1 --port 8000

Run (development, with frontend dev server on :5173 proxying here):
    uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from teammate_code.aditya_l1_solar_flare_pipeline.pipeline import config
from . import services
from .live import run_live_replay

ROOT_DIR = config.ROOT_DIR
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

app = FastAPI(title="Aditya-L1 Solar Flare Operations API", version="1.0.0")

# Allow the Vite dev server (localhost:5173) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    source: str = "synthetic"


# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "service": "aditya-l1-flare-operations", "version": app.version}


@app.get("/api/files")
def files():
    return services.list_payload_files()


@app.post("/api/upload/{payload}")
def upload(payload: str, file: UploadFile = File(...)):
    try:
        return services.save_upload(payload, file.filename, file.file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/run")
def run(req: RunRequest):
    try:
        services.start_run(req.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"started": True, "source": req.source}


@app.get("/api/run-status")
def run_status():
    return services.get_run_state()


@app.get("/api/metrics")
def metrics():
    return services.parsed_metrics()


@app.get("/api/catalogue")
def catalogue():
    return services.read_catalogue()


@app.get("/api/alerts")
def alerts():
    return {"alerts": services.read_alerts()}


@app.get("/api/forecast-timeline")
def forecast_timeline(max_points: int = 3000):
    # Full-resolution timeline is ~20k rows/14 days; stride-sample for plotting.
    points = services.read_forecast_timeline()
    cap = max(200, min(max_points, 20000))
    if len(points) > cap:
        stride = (len(points) // cap) + 1
        points = points[::stride]
    return {"points": points}


@app.get("/api/light-curve")
def light_curve(max_points: int = 3000):
    try:
        source, df = services.load_best_light_curve()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    import pandas as pd
    df = services.downsample(df, max(100, min(max_points, 12000)))
    df[config.TIME_COL] = pd.to_datetime(df[config.TIME_COL], utc=True).astype(str)
    cols = [config.TIME_COL, config.SXR_COL, config.HXR_COL,
            config.SXR_QUALITY_COL, config.HXR_QUALITY_COL]
    return {"source": source, "points": df[cols].to_dict(orient="records")}


@app.get("/api/summary", response_class=PlainTextResponse)
def summary():
    text = services.read_summary()
    if text is None:
        raise HTTPException(status_code=404, detail="No pipeline summary found")
    return text


@app.get("/api/dashboard")
def generated_dashboard():
    path = config.OUTPUT_DIR / "dashboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Generated dashboard does not exist yet")
    return FileResponse(path)


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await run_live_replay(websocket)


@app.exception_handler(Exception)
def unhandled_exception(_, exc):
    print(f"Unhandled API error: {exc}", file=sys.stderr)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# --------------------------------------------------------------------------
# Static SPA hosting (built React app). Mounted LAST so /api and /ws win.
# When the frontend has not been built yet, a helpful placeholder is served.
# --------------------------------------------------------------------------
if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="spa")
else:
    @app.get("/")
    def _frontend_not_built():
        return PlainTextResponse(
            "Frontend has not been built yet.\n\n"
            "  cd frontend && npm install && npm run build\n\n"
            "Then restart this server, or use the Vite dev server:\n"
            "  cd frontend && npm run dev   (http://localhost:5173)\n",
            status_code=503,
        )
