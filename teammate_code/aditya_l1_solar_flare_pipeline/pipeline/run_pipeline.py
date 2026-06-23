"""
run_pipeline.py
================
Single entry point that runs the ENTIRE pipeline end to end:

  1. Load data (real ISSDC data by default; synthetic only when requested)
  2. Preprocess (background, smoothing, derived features)
  3. Nowcasting (detect flares in SXR + HXR, build master catalogue)
  4. Forecasting (train precursor model, evaluate lead time / TPR / FAR)
  5. Dashboard (write interactive HTML visualization)

Usage:
    python run_pipeline.py
    python run_pipeline.py --source synthetic
    python run_pipeline.py --source real

All outputs are written to outputs/:
    nowcast_master_catalogue.csv   - combined flare detections
    nowcast_sxr_events.csv         - SXR-channel-only detections
    nowcast_hxr_events.csv         - HXR-channel-only detections
    forecast_probabilities.csv     - per-window forecast probabilities
    forecast_alerts.csv            - debounced forecast alert episodes
    forecaster_model.joblib        - trained forecasting model
    dashboard.html                 - interactive visualization
    pipeline_summary.txt           - this run's key metrics, human-readable
"""

import argparse
import sys
import pandas as pd

from . import config
from .data_loader import load_light_curve
from .preprocessing import build_feature_frame
from .nowcasting import run_nowcasting_pipeline
from .forecasting import train_forecaster, walk_forward_evaluate, build_forecast_alert_catalogue
from .dashboard import build_dashboard


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the Aditya-L1 SoLEXS+HEL1OS flare nowcast/forecast pipeline."
    )
    parser.add_argument(
        "--source",
        choices=["real", "synthetic"],
        default=None,
        help=(
            "Data source for this run. Defaults to pipeline/config.py. "
            "Use 'synthetic' only for validation when real PRADAN data is unavailable."
        ),
    )
    return parser.parse_args()


def main(source=None):
    if source is not None:
        config.USE_SYNTHETIC = source == "synthetic"

    print("=" * 70)
    print("ADITYA-L1 SOLAR FLARE NOWCASTING & FORECASTING PIPELINE")
    print("=" * 70)
    print(f"Data source: {'SYNTHETIC (sample data)' if config.USE_SYNTHETIC else 'REAL ISSDC DATA'}")
    print()

    # ------------------------------------------------------------
    # 1. Load + preprocess
    # ------------------------------------------------------------
    print("[1/5] Loading light curve data...")
    df = load_light_curve()
    print(f"      Loaded {len(df):,} samples "
          f"({df[config.TIME_COL].iloc[0]} to {df[config.TIME_COL].iloc[-1]})")

    print("[2/5] Preprocessing (background estimation, smoothing, derived features)...")
    feat = build_feature_frame(df)

    # ------------------------------------------------------------
    # 2. Nowcasting
    # ------------------------------------------------------------
    print("[3/5] Running nowcasting (real-time flare detection)...")
    master, sxr_events, hxr_events = run_nowcasting_pipeline(feat, save=True)
    n_confirmed = (master["status"] == "confirmed").sum() if len(master) else 0
    print(f"      SXR-channel events: {len(sxr_events)}")
    print(f"      HXR-channel events: {len(hxr_events)}")
    print(f"      Master catalogue: {len(master)} events ({n_confirmed} high-confidence/confirmed)")

    # ------------------------------------------------------------
    # 3. Forecasting
    # ------------------------------------------------------------
    print("[4/5] Training forecasting model (precursor pattern detection)...")
    ground_truth_path = config.SAMPLE_DIR / "ground_truth_flares.csv"
    if (not config.USE_SYNTHETIC) and config.EXTERNAL_FLARE_CATALOGUE_PATH.exists():
        catalogue_for_training = pd.read_csv(config.EXTERNAL_FLARE_CATALOGUE_PATH)
        print(f"      Training labels derived from external catalogue: {config.EXTERNAL_FLARE_CATALOGUE_PATH}")
    elif config.USE_SYNTHETIC and ground_truth_path.exists():
        catalogue_for_training = pd.read_csv(ground_truth_path)
        print("      (Training labels derived from synthetic ground truth.")
        print("       With real data, the nowcast master catalogue itself")
        print("       becomes the label source - see README 'Switching to")
        print("       Real Data' section.)")
    else:
        # With real data there is no separate ground truth file - the
        # nowcast master catalogue IS the source of truth for training labels.
        catalogue_for_training = master.rename(columns={"flare_class": "class"})
        print("      Training labels derived from the nowcast master catalogue.")

    results = train_forecaster(feat, catalogue_for_training, save=True)
    print(f"      Validation AUC: {results['val_auc']:.3f}")
    print(f"      Test AUC:       {results['test_auc']:.3f}")
    _, _, t_test = results["splits"]["test"]
    forecast_probability_df = pd.DataFrame({
        "time": pd.to_datetime(t_test).to_numpy(),
        "probability": results["test_proba"],
        "threshold": config.ALERT_PROBABILITY_THRESHOLD,
        "forecast_horizon_min": config.FORECAST_HORIZON_MIN,
    })
    forecast_probability_df.to_csv(config.OUTPUT_DIR / "forecast_probabilities.csv", index=False)

    # Full-timeline forecast probability for the live monitor / dashboard so the
    # probability trace tracks the entire light curve, not only the test slice.
    forecast_timeline_df = pd.DataFrame({
        "time": pd.to_datetime(results["all_times"]).to_numpy(),
        "probability": results["all_proba"],
        "threshold": config.ALERT_PROBABILITY_THRESHOLD,
        "forecast_horizon_min": config.FORECAST_HORIZON_MIN,
    })
    forecast_timeline_df.to_csv(config.OUTPUT_DIR / "forecast_timeline.csv", index=False)
    forecast_alerts = build_forecast_alert_catalogue(t_test, results["test_proba"])
    forecast_alerts.to_csv(config.OUTPUT_DIR / "forecast_alerts.csv", index=False)
    print(f"      Forecast alert episodes: {len(forecast_alerts)}")

    print("      Running walk-forward evaluation (robust TPR/FAR/lead-time estimate)...")
    wf = walk_forward_evaluate(feat, catalogue_for_training, n_folds=4)

    # ------------------------------------------------------------
    # 4. Dashboard
    # ------------------------------------------------------------
    print("[5/5] Building interactive dashboard...")
    dashboard_path = config.OUTPUT_DIR / "dashboard.html"
    build_dashboard(
        feat, master,
        forecast_times=t_test, forecast_proba=results["test_proba"],
        save_path=dashboard_path,
    )
    print(f"      Dashboard written to {dashboard_path}")

    # ------------------------------------------------------------
    # 5. Summary report
    # ------------------------------------------------------------
    summary_lines = [
        "ADITYA-L1 SOLAR FLARE PIPELINE - RUN SUMMARY",
        "=" * 50,
        f"Data source: {'synthetic sample data' if config.USE_SYNTHETIC else 'real ISSDC data'}",
        f"Samples processed: {len(df):,}",
        f"Time range: {df[config.TIME_COL].iloc[0]} to {df[config.TIME_COL].iloc[-1]}",
        "",
        "NOWCASTING",
        "-" * 50,
        f"SXR-channel detections: {len(sxr_events)}",
        f"HXR-channel detections: {len(hxr_events)}",
        f"Master catalogue events: {len(master)}",
        f"  confirmed (high confidence): {(master['status']=='confirmed').sum() if len(master) else 0}",
        f"  sxr_only (medium confidence): {(master['status']=='sxr_only').sum() if len(master) else 0}",
        f"  hxr_only (low confidence): {(master['status']=='hxr_only').sum() if len(master) else 0}",
        "",
        "FORECASTING",
        "-" * 50,
        f"Forecast horizon: {config.FORECAST_HORIZON_MIN} minutes",
        f"Lookback window: {config.LOOKBACK_WINDOW_MIN} minutes",
        f"Minimum class forecasted: {config.MIN_FLARE_CLASS_FOR_POSITIVE}-class and above",
        f"Validation AUC: {results['val_auc']:.3f}",
        f"Test AUC (single chronological split): {results['test_auc']:.3f}",
        f"Forecast alert episodes: {len(forecast_alerts)}",
        "",
        f"Walk-forward evaluation (n_folds={4}, threshold={config.ALERT_PROBABILITY_THRESHOLD}):",
        f"  True Positive Rate: {wf['overall_true_positive_rate']:.1%} "
        f"({wf['total_detected']}/{wf['total_qualifying']} flares detected)",
        f"  False Alarm Rate:   {wf['overall_false_alarm_rate']:.1%}",
        f"  Median Lead Time:   {wf['median_lead_time_min']:.1f} minutes",
        f"  Mean Lead Time:     {wf['mean_lead_time_min']:.1f} minutes",
        "",
        "OUTPUT FILES (outputs/)",
        "-" * 50,
        "  nowcast_master_catalogue.csv",
        "  nowcast_sxr_events.csv",
        "  nowcast_hxr_events.csv",
        "  forecast_probabilities.csv",
        "  forecast_alerts.csv",
        "  forecaster_model.joblib",
        "  dashboard.html",
    ]
    summary_text = "\n".join(summary_lines)
    with open(config.OUTPUT_DIR / "pipeline_summary.txt", "w") as f:
        f.write(summary_text)

    print()
    print(summary_text)


if __name__ == "__main__":
    args = parse_args()
    main(source=args.source)
