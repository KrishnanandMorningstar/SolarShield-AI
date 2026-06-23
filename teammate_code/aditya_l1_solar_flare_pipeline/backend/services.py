"""
services.py
===========
Stateful helpers shared by the REST and WebSocket layers:

  * pipeline run orchestration (background thread + status/log state)
  * filesystem inventory and uploads for raw payload files
  * output-artifact readers (catalogues, alerts, summary)
  * light-curve loading + downsampling for plotting

Kept deliberately free of FastAPI types so it can be unit-tested in isolation.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from teammate_code.aditya_l1_solar_flare_pipeline.pipeline import config
from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.data_loader import _discover_payload_files
from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.run_pipeline import main as run_pipeline_main

# --------------------------------------------------------------------------
# Run state (single global pipeline run at a time)
# --------------------------------------------------------------------------
_RUN_LOCK = threading.Lock()
_RUN_STATE: dict[str, Any] = {
    "running": False,
    "source": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "log": "",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_run_state() -> dict[str, Any]:
    with _RUN_LOCK:
        return dict(_RUN_STATE)


def is_running() -> bool:
    with _RUN_LOCK:
        return bool(_RUN_STATE["running"])


def _run_job(source: str) -> None:
    with _RUN_LOCK:
        _RUN_STATE.update(
            running=True, source=source, started_at=_utc_now(),
            finished_at=None, error=None, log="",
        )

    log_buffer = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(log_buffer), contextlib.redirect_stderr(log_buffer):
            run_pipeline_main(source=source)
    except Exception as exc:  # surfaced to the UI run log
        error = str(exc)
    finally:
        with _RUN_LOCK:
            _RUN_STATE.update(
                running=False, finished_at=_utc_now(),
                error=error, log=log_buffer.getvalue(),
            )


def start_run(source: str) -> None:
    """Launch a pipeline run in a daemon thread. Raises if one is already active."""
    if source not in {"real", "synthetic"}:
        raise ValueError("source must be 'real' or 'synthetic'")
    with _RUN_LOCK:
        if _RUN_STATE["running"]:
            raise RuntimeError("Pipeline is already running")
    threading.Thread(target=_run_job, args=(source,), daemon=True).start()


# --------------------------------------------------------------------------
# Filesystem inventory + uploads
# --------------------------------------------------------------------------
def _file_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def list_payload_files() -> dict[str, Any]:
    return {
        "solexs_dir": str(config.SOLEXS_RAW_DIR),
        "hel1os_dir": str(config.HEL1OS_RAW_DIR),
        "solexs": [_file_info(p) for p in _discover_payload_files(config.SOLEXS_RAW_DIR)],
        "hel1os": [_file_info(p) for p in _discover_payload_files(config.HEL1OS_RAW_DIR)],
    }


def save_upload(payload: str, filename: str | None, fileobj) -> dict[str, Any]:
    if payload not in {"solexs", "hel1os"}:
        raise ValueError("payload must be 'solexs' or 'hel1os'")
    target_dir = config.SOLEXS_RAW_DIR if payload == "solexs" else config.HEL1OS_RAW_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(filename or "uploaded_payload").name
    target = target_dir / safe_name
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        target = target_dir / f"{target.stem}_{stamp}{target.suffix}"

    with target.open("wb") as out:
        shutil.copyfileobj(fileobj, out)
    return {"saved": str(target), "file": _file_info(target)}


# --------------------------------------------------------------------------
# Output-artifact readers
# --------------------------------------------------------------------------
def csv_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pd.read_csv(path).fillna("").to_dict(orient="records")


def read_catalogue() -> dict[str, Any]:
    out = config.OUTPUT_DIR
    return {
        "master": csv_records(out / "nowcast_master_catalogue.csv"),
        "sxr": csv_records(out / "nowcast_sxr_events.csv"),
        "hxr": csv_records(out / "nowcast_hxr_events.csv"),
    }


def read_alerts() -> list[dict[str, Any]]:
    return csv_records(config.OUTPUT_DIR / "forecast_alerts.csv")


def read_forecast_timeline() -> list[dict[str, Any]]:
    # Prefer the full-timeline probabilities; fall back to the test-only file.
    full = config.OUTPUT_DIR / "forecast_timeline.csv"
    if full.exists():
        return csv_records(full)
    return csv_records(config.OUTPUT_DIR / "forecast_probabilities.csv")


def read_summary() -> str | None:
    path = config.OUTPUT_DIR / "pipeline_summary.txt"
    return path.read_text() if path.exists() else None


def parsed_metrics() -> dict[str, Any]:
    """Best-effort structured KPIs derived from the generated artifacts."""
    cat = read_catalogue()["master"]
    alerts = read_alerts()
    metrics: dict[str, Any] = {
        "master_events": len(cat),
        "confirmed": sum(1 for e in cat if e.get("status") == "confirmed"),
        "sxr_only": sum(1 for e in cat if e.get("status") == "sxr_only"),
        "hxr_only": sum(1 for e in cat if e.get("status") == "hxr_only"),
        "alert_episodes": len(alerts),
        "tpr": None, "far": None, "median_lead_min": None,
        "val_auc": None, "test_auc": None,
    }
    summary = read_summary() or ""
    for line in summary.splitlines():
        low = line.lower().strip()
        try:
            if "true positive rate" in low:
                metrics["tpr"] = float(line.split(":")[1].split("%")[0].strip())
            elif "false alarm rate" in low:
                metrics["far"] = float(line.split(":")[1].split("%")[0].strip())
            elif "median lead time" in low:
                metrics["median_lead_min"] = float(line.split(":")[1].split("minutes")[0].strip())
            elif low.startswith("validation auc"):
                metrics["val_auc"] = float(line.split(":")[1].strip())
            elif "test auc" in low:
                metrics["test_auc"] = float(line.split(":")[1].strip())
        except (ValueError, IndexError):
            continue
    return metrics


# --------------------------------------------------------------------------
# Light-curve loading + downsampling
# --------------------------------------------------------------------------
def load_best_light_curve() -> tuple[str, pd.DataFrame]:
    """Return (source, dataframe). Real processed data wins over synthetic."""
    real_path = config.PROCESSED_REAL_LIGHT_CURVE
    synth_path = config.SAMPLE_DIR / "synthetic_light_curve.parquet"
    if real_path.exists():
        return "real", pd.read_parquet(real_path)
    if synth_path.exists():
        return "synthetic", pd.read_parquet(synth_path)
    raise FileNotFoundError("No processed real data or synthetic validation data found.")


def downsample(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    df = df.reset_index(drop=True)
    if len(df) <= max_points:
        return df
    bin_size = max(1, int(len(df) / max_points))
    grouped = df.groupby(df.index // bin_size)
    agg = grouped.agg({
        config.TIME_COL: "first",
        config.SXR_COL: "max",
        config.HXR_COL: "max",
        config.SXR_QUALITY_COL: "max",
        config.HXR_QUALITY_COL: "max",
    })
    return agg.reset_index(drop=True)
