"""
forecasting.py
===============
Predictive modelling: Objective 2 of the brief - "identify precursor
patterns in soft and hard X-ray light curves BEFORE the actual flare
occurs" and "predict the probability of a flare occurring in the next
N minutes" (config.FORECAST_HORIZON_MIN).

APPROACH
--------
This is framed as SUPERVISED BINARY CLASSIFICATION on a sliding window:

  For every minute t in the light curve:
    X(t) = features summarizing the LOOKBACK_WINDOW_MIN minutes
           ending at t (both SXR and HXR channels)
    y(t) = 1 if a flare of class >= MIN_FLARE_CLASS_FOR_POSITIVE has its
           ONSET within (t, t + FORECAST_HORIZON_MIN]
           else 0

This directly operationalizes "predict probability of a flare in the next
N minutes" and lets us report LEAD TIME (one of the explicit evaluation
criteria) as: (predicted alert time) -> (actual onset time).

WHY THESE FEATURES (the "precursor pattern" the brief asks us to learn)
--------------------------------------------------------------------------
Real flares are frequently preceded by:
  - slow brightening / micro-fluctuations in soft X-ray ("pre-flare" rise)
  - small impulsive hard X-ray spikes (micro-bursts / energy release
    "testing" before the main eruption)
  - increased VARIABILITY (std) in both channels just before onset
  - a positive SLOPE trend even before crossing detection thresholds

So the feature window computes, per channel, per lookback window:
  mean, std, max, slope (linear trend), max single-step jump,
  number of micro-bursts (small threshold crossings),
  ratio of current value to window-start value (trend strength)
plus CROSS-channel features (SXR-HXR correlation in the window), since
the brief explicitly wants COMBINED soft+hard X-ray forecasting, not two
separate models bolted together.

MODEL
-----
Gradient Boosted Trees (scikit-learn HistGradientBoostingClassifier).
Chosen over deep sequence models (LSTM/Transformer) deliberately:
  - Tabular sliding-window features + boosted trees are a strong,
    well-evidenced baseline for solar flare forecasting in the published
    literature (e.g. flare forecasting using SDO/HMI features), and far
    more data-efficient than deep nets - important since real Aditya-L1
    SoLEXS/HEL1OS history is still being accumulated.
  - It is fast to train/retrain as new data streams in (important for an
    operational pipeline) and naturally outputs calibrated-ish
    probabilities + feature importances for explainability (useful for a
    space-weather operations team that needs to trust/audit alerts).
  - Easy to swap for an LSTM/TCN later (see NOTE at bottom of file) once
    enough real flare history exists to justify a deep model.

EVALUATION
----------
Chronological train/val/test split (NEVER random shuffling - that would
leak future information backward, which is a common mistake in
time-series forecasting). Reports the brief's explicit criteria:
  - True Positive Rate (recall) and False Alarm Rate at the chosen
    probability threshold
  - Lead time distribution: minutes between first alert crossing and the
    actual flare onset, for each correctly-forecasted flare
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, precision_recall_curve
import joblib

from . import config


def _linear_slope(y):
    """OLS slope of y against sample index; fast, robust precursor-trend feature."""
    n = len(y)
    if n < 2 or np.all(np.isnan(y)):
        return 0.0
    x = np.arange(n)
    valid = ~np.isnan(y)
    if valid.sum() < 2:
        return 0.0
    x, y = x[valid], y[valid]
    return np.polyfit(x, y, 1)[0]


def _count_microbursts(excess, threshold):
    """Count discrete local-max crossings above `threshold` - candidate precursor spikes."""
    above = excess > threshold
    # count rising edges
    return int(np.sum(above[1:].to_numpy() & ~above[:-1].to_numpy())) if len(above) > 1 else 0


def build_sliding_window_features(feat: pd.DataFrame, step_min=None) -> pd.DataFrame:
    """
    Build the (X, timestamp) feature table at FEATURE_STEP_MIN cadence.
    This downsamples the 1-second light curve to a coarser "decision
    cadence" appropriate for minute-scale forecasting, which both keeps
    the model fast and matches the timescale of real precursor physics.
    """
    step_min = step_min or config.FEATURE_STEP_MIN
    lookback_min = config.LOOKBACK_WINDOW_MIN
    cadence = config.RESAMPLE_CADENCE_S

    step_samples = max(1, int(step_min * 60 / cadence))
    lookback_samples = max(1, int(lookback_min * 60 / cadence))

    sxr_excess = feat["sxr_excess"].to_numpy()
    hxr_excess = feat["hxr_excess"].to_numpy()
    sxr_ratio = feat["sxr_ratio"].to_numpy()
    hxr_ratio = feat["hxr_ratio"].to_numpy()
    times = feat[config.TIME_COL].to_numpy()

    sxr_microburst_thresh = np.nanpercentile(sxr_excess, 90)
    hxr_microburst_thresh = np.nanpercentile(hxr_excess, 90)

    rows = []
    idxs = list(range(lookback_samples, len(feat), step_samples))
    for end_idx in idxs:
        start_idx = end_idx - lookback_samples
        sxr_win = sxr_excess[start_idx:end_idx]
        hxr_win = hxr_excess[start_idx:end_idx]
        sxr_ratio_win = sxr_ratio[start_idx:end_idx]
        hxr_ratio_win = hxr_ratio[start_idx:end_idx]

        sxr_win_s = pd.Series(sxr_win)
        hxr_win_s = pd.Series(hxr_win)

        row = {
            "time": pd.Timestamp(times[end_idx]),
            "sxr_mean": np.nanmean(sxr_win),
            "sxr_std": np.nanstd(sxr_win),
            "sxr_max": np.nanmax(sxr_win),
            "sxr_slope": _linear_slope(sxr_win),
            "sxr_max_jump": np.nanmax(np.abs(np.diff(sxr_win))) if len(sxr_win) > 1 else 0.0,
            "sxr_microbursts": _count_microbursts(sxr_win_s, sxr_microburst_thresh),
            "sxr_ratio_mean": np.nanmean(sxr_ratio_win),
            "sxr_ratio_max": np.nanmax(sxr_ratio_win),
            "hxr_mean": np.nanmean(hxr_win),
            "hxr_std": np.nanstd(hxr_win),
            "hxr_max": np.nanmax(hxr_win),
            "hxr_slope": _linear_slope(hxr_win),
            "hxr_max_jump": np.nanmax(np.abs(np.diff(hxr_win))) if len(hxr_win) > 1 else 0.0,
            "hxr_microbursts": _count_microbursts(hxr_win_s, hxr_microburst_thresh),
            "hxr_ratio_mean": np.nanmean(hxr_ratio_win),
            "hxr_ratio_max": np.nanmax(hxr_ratio_win),
            # cross-channel: correlation between SXR and HXR excess within window
            "cross_corr": (np.corrcoef(sxr_win, hxr_win)[0, 1]
                           if len(sxr_win) > 2 and np.nanstd(sxr_win) > 0 and np.nanstd(hxr_win) > 0
                           else 0.0),
        }
        rows.append(row)

    feature_df = pd.DataFrame(rows).fillna(0.0)
    return feature_df


def label_windows(feature_df: pd.DataFrame, flare_catalogue: pd.DataFrame) -> pd.Series:
    """
    y(t) = 1 if a qualifying flare's onset falls within
           (t, t + FORECAST_HORIZON_MIN], else 0.

    flare_catalogue must have an 'onset_time' column and a 'class' (or
    'flare_class') column starting with the GOES letter (A/B/C/M/X).
    """
    horizon = pd.Timedelta(minutes=config.FORECAST_HORIZON_MIN)
    min_class = config.MIN_FLARE_CLASS_FOR_POSITIVE
    order = config.FLARE_CLASS_ORDER
    min_rank = order.index(min_class)

    class_col = "class" if "class" in flare_catalogue.columns else "flare_class"
    qualifying = flare_catalogue[
        flare_catalogue[class_col].astype(str).str[0].apply(
            lambda c: c in order and order.index(c) >= min_rank
        )
    ]
    onset_times = pd.to_datetime(qualifying["onset_time"], utc=True).sort_values().to_numpy()

    times = feature_df["time"].to_numpy()
    labels = np.zeros(len(times), dtype=int)
    for i, t in enumerate(times):
        window_end = t + horizon
        in_window = (onset_times > t) & (onset_times <= window_end)
        if in_window.any():
            labels[i] = 1
    return pd.Series(labels, index=feature_df.index, name="label")


def chronological_split(feature_df: pd.DataFrame, labels: pd.Series):
    n = len(feature_df)
    train_end = int(n * config.TRAIN_FRACTION)
    val_end = int(n * (config.TRAIN_FRACTION + config.VAL_FRACTION))

    X = feature_df.drop(columns=["time"])
    splits = {
        "train": (X.iloc[:train_end], labels.iloc[:train_end], feature_df["time"].iloc[:train_end]),
        "val": (X.iloc[train_end:val_end], labels.iloc[train_end:val_end], feature_df["time"].iloc[train_end:val_end]),
        "test": (X.iloc[val_end:], labels.iloc[val_end:], feature_df["time"].iloc[val_end:]),
    }
    return splits


def train_forecaster(feat: pd.DataFrame, flare_catalogue: pd.DataFrame, save=True):
    """Full training pipeline: build features, label, split, train, evaluate."""
    feature_df = build_sliding_window_features(feat)
    labels = label_windows(feature_df, flare_catalogue)
    splits = chronological_split(feature_df, labels)

    X_train, y_train, _ = splits["train"]
    X_val, y_val, _ = splits["val"]
    X_test, y_test, t_test = splits["test"]

    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.06,
        max_depth=4,
        l2_regularization=1.0,
        random_state=config.RANDOM_SEED,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    val_auc = roc_auc_score(y_val, model.predict_proba(X_val)[:, 1]) if y_val.nunique() > 1 else float("nan")
    test_proba = model.predict_proba(X_test)[:, 1]
    test_auc = roc_auc_score(y_test, test_proba) if y_test.nunique() > 1 else float("nan")

    if save:
        joblib.dump(model, config.OUTPUT_DIR / "forecaster_model.joblib")

    results = {
        "model": model,
        "feature_columns": list(X_train.columns),
        "val_auc": val_auc,
        "test_auc": test_auc,
        "splits": splits,
        "test_proba": test_proba,
        # Full-timeline forecast probability (every decision window, not just
        # the held-out test slice). Used by the live monitor / dashboard so the
        # probability trace tracks the entire light curve.
        "feature_df": feature_df,
        "all_times": feature_df["time"],
        "all_proba": model.predict_proba(feature_df.drop(columns=["time"]))[:, 1],
    }
    return results


def evaluate_lead_time(
    feature_df_test_time: pd.Series,
    test_proba: np.ndarray,
    flare_catalogue: pd.DataFrame,
    probability_threshold: float = None,
    debounce_min: float = None,
):
    """
    For each qualifying flare in the test period, find the FIRST timestamp
    where predicted probability crosses `probability_threshold` within the
    forecast horizon before onset, and report lead time = onset - alert_time.
    Also computes True Positive Rate and False Alarm Rate at this threshold.

    DEBOUNCING: a real alerting system fires ONE alert when probability
    first crosses the threshold, then stays "armed" (not re-alerting) while
    probability remains elevated - exactly like a smoke alarm doesn't beep
    once per second while smoke is present. Without this, every sample in
    a multi-minute elevated-probability period would count as a separate
    "alert", artificially inflating the false alarm rate. debounce_min
    defaults to FORECAST_HORIZON_MIN (an operator is re-alerted at most
    once per forecast horizon).
    """
    debounce_min = debounce_min if debounce_min is not None else config.FORECAST_HORIZON_MIN
    debounce = pd.Timedelta(minutes=debounce_min)
    probability_threshold = (probability_threshold if probability_threshold is not None
                              else config.ALERT_PROBABILITY_THRESHOLD)

    times = pd.to_datetime(feature_df_test_time).reset_index(drop=True)
    proba = pd.Series(test_proba).reset_index(drop=True)
    raw_alert_times = times[proba >= probability_threshold].sort_values().reset_index(drop=True)

    # Debounced alert stream is used ONLY for counting "how many distinct
    # alert events fired" (false alarm rate denominator) - a real operator
    # is paged once per elevated-probability episode, not once per second.
    debounced_alerts = []
    last_alert = None
    for t in raw_alert_times:
        if last_alert is None or (t - last_alert) > debounce:
            debounced_alerts.append(t)
            last_alert = t
    debounced_alerts = pd.Series(debounced_alerts)

    order = config.FLARE_CLASS_ORDER
    min_rank = order.index(config.MIN_FLARE_CLASS_FOR_POSITIVE)
    class_col = "class" if "class" in flare_catalogue.columns else "flare_class"
    qualifying = flare_catalogue[
        flare_catalogue[class_col].astype(str).str[0].apply(
            lambda c: c in order and order.index(c) >= min_rank
        )
    ].copy()
    qualifying["onset_time"] = pd.to_datetime(qualifying["onset_time"], utc=True)

    test_start, test_end = times.iloc[0], times.iloc[-1]
    qualifying = qualifying[(qualifying["onset_time"] >= test_start) & (qualifying["onset_time"] <= test_end)]

    horizon = pd.Timedelta(minutes=config.FORECAST_HORIZON_MIN)
    lead_times = []
    detected_flares = 0
    matched_raw_alert_indices = set()
    for _, row in qualifying.iterrows():
        onset = row["onset_time"]
        # Detection uses the RAW (non-debounced) alert stream: we only need
        # the alert to have fired at least once inside the valid horizon
        # window before onset, regardless of how many times it re-fired.
        window_mask = (raw_alert_times > onset - horizon) & (raw_alert_times <= onset)
        window_alerts = raw_alert_times[window_mask]
        if len(window_alerts):
            first_alert = window_alerts.min()
            lead_minutes = (onset - first_alert).total_seconds() / 60.0
            lead_times.append(lead_minutes)
            detected_flares += 1
            matched_raw_alert_indices.update(raw_alert_times[window_mask].index)

    n_qualifying = len(qualifying)
    true_positive_rate = detected_flares / n_qualifying if n_qualifying else float("nan")

    # False alarm rate: (debounced) alert EVENTS not followed by any
    # qualifying flare onset within horizon. Using the debounced stream
    # here means a 10-minute-long elevated-probability episode with no
    # following flare counts as ONE false alarm, not dozens.
    false_alerts = 0
    for t in debounced_alerts:
        followed = ((qualifying["onset_time"] > t) & (qualifying["onset_time"] <= t + horizon)).any()
        if not followed:
            false_alerts += 1
    false_alarm_rate = false_alerts / len(debounced_alerts) if len(debounced_alerts) else 0.0

    return {
        "n_qualifying_flares_in_test": n_qualifying,
        "n_detected": detected_flares,
        "true_positive_rate": true_positive_rate,
        "false_alarm_rate": false_alarm_rate,
        "lead_times_min": lead_times,
        "mean_lead_time_min": float(np.mean(lead_times)) if lead_times else float("nan"),
        "median_lead_time_min": float(np.median(lead_times)) if lead_times else float("nan"),
    }


def sweep_thresholds(feature_df_test_time, test_proba, flare_catalogue, thresholds=None):
    """Evaluate lead-time metrics across a range of probability thresholds,
    to help pick an operating point that balances TPR vs false alarm rate."""
    thresholds = thresholds if thresholds is not None else np.arange(0.3, 0.95, 0.05)
    rows = []
    for th in thresholds:
        m = evaluate_lead_time(feature_df_test_time, test_proba, flare_catalogue, probability_threshold=th)
        rows.append({
            "threshold": round(float(th), 2),
            "true_positive_rate": m["true_positive_rate"],
            "false_alarm_rate": m["false_alarm_rate"],
            "n_detected": m["n_detected"],
            "n_qualifying": m["n_qualifying_flares_in_test"],
            "median_lead_time_min": m["median_lead_time_min"],
        })
    return pd.DataFrame(rows)


def build_forecast_alert_catalogue(
    forecast_times: pd.Series,
    forecast_proba: np.ndarray,
    probability_threshold: float = None,
    debounce_min: float = None,
) -> pd.DataFrame:
    """
    Convert per-window forecast probabilities into an operator-friendly
    alert catalogue. Consecutive above-threshold samples are collapsed into
    one alert episode with start/end/peak probability.
    """
    probability_threshold = (
        probability_threshold
        if probability_threshold is not None
        else config.ALERT_PROBABILITY_THRESHOLD
    )
    debounce_min = debounce_min if debounce_min is not None else config.FORECAST_HORIZON_MIN
    debounce = pd.Timedelta(minutes=debounce_min)

    times = pd.to_datetime(pd.Series(forecast_times), utc=True).reset_index(drop=True)
    proba = pd.Series(forecast_proba).reset_index(drop=True)
    above = proba >= probability_threshold

    rows = []
    episode_start = None
    episode_end = None
    peak_time = None
    peak_probability = None
    last_above = None

    for t, p, is_above in zip(times, proba, above):
        if not is_above:
            continue
        if episode_start is None or (last_above is not None and (t - last_above) > debounce):
            if episode_start is not None:
                rows.append({
                    "alert_id": f"ALERT_{len(rows)+1:04d}",
                    "start_time": episode_start,
                    "end_time": episode_end,
                    "peak_time": peak_time,
                    "peak_probability": peak_probability,
                    "threshold": probability_threshold,
                    "forecast_horizon_min": config.FORECAST_HORIZON_MIN,
                })
            episode_start = t
            episode_end = t
            peak_time = t
            peak_probability = float(p)
        else:
            episode_end = t
            if float(p) > peak_probability:
                peak_time = t
                peak_probability = float(p)
        last_above = t

    if episode_start is not None:
        rows.append({
            "alert_id": f"ALERT_{len(rows)+1:04d}",
            "start_time": episode_start,
            "end_time": episode_end,
            "peak_time": peak_time,
            "peak_probability": peak_probability,
            "threshold": probability_threshold,
            "forecast_horizon_min": config.FORECAST_HORIZON_MIN,
        })

    return pd.DataFrame(rows)


def walk_forward_evaluate(feat: pd.DataFrame, flare_catalogue: pd.DataFrame, n_folds: int = 4,
                            probability_threshold: float = None):
    """
    With a limited number of real (or synthetic) flares, a single
    chronological train/val/test split can leave very few flares in the
    test fold, making TPR/FAR estimates noisy (as seen with n=3 above).

    Walk-forward (expanding window) cross-validation mitigates this:
    fold k trains on data [0, k/n_folds) and tests on the NEXT slice
    [k/n_folds, (k+1)/n_folds) - still fully chronological/causal (no
    leakage), but aggregates metrics over several test folds instead of
    one, giving a more statistically reliable TPR/FAR/lead-time estimate.
    This is the standard practice for evaluating time-series forecasters
    when event counts are limited, and is recommended here as the metric
    to report rather than the single-split numbers.
    """
    feature_df = build_sliding_window_features(feat)
    labels = label_windows(feature_df, flare_catalogue)
    n = len(feature_df)
    fold_size = n // (n_folds + 1)  # first fold_size block reserved as initial training seed
    probability_threshold = (probability_threshold if probability_threshold is not None
                              else config.ALERT_PROBABILITY_THRESHOLD)

    all_lead_times = []
    total_detected, total_qualifying, total_alerts, total_false_alerts = 0, 0, 0, 0
    fold_summaries = []

    for k in range(1, n_folds + 1):
        train_end = k * fold_size
        test_end = min((k + 1) * fold_size, n)
        if train_end >= test_end:
            continue

        X_train = feature_df.drop(columns=["time"]).iloc[:train_end]
        y_train = labels.iloc[:train_end]
        X_test = feature_df.drop(columns=["time"]).iloc[train_end:test_end]
        t_test = feature_df["time"].iloc[train_end:test_end]

        if y_train.nunique() < 2:
            continue

        model = HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.06, max_depth=4,
            l2_regularization=1.0, random_state=config.RANDOM_SEED,
            class_weight="balanced",
        )
        model.fit(X_train, y_train)
        proba = model.predict_proba(X_test)[:, 1]

        m = evaluate_lead_time(t_test, proba, flare_catalogue, probability_threshold=probability_threshold)
        fold_summaries.append({"fold": k, **{kk: vv for kk, vv in m.items() if kk != "lead_times_min"}})
        all_lead_times.extend(m["lead_times_min"])
        total_detected += m["n_detected"]
        total_qualifying += m["n_qualifying_flares_in_test"]

    overall_tpr = total_detected / total_qualifying if total_qualifying else float("nan")
    fold_df = pd.DataFrame(fold_summaries)
    overall_far = fold_df["false_alarm_rate"].mean() if len(fold_df) else float("nan")

    return {
        "fold_summaries": fold_df,
        "overall_true_positive_rate": overall_tpr,
        "overall_false_alarm_rate": overall_far,
        "total_detected": total_detected,
        "total_qualifying": total_qualifying,
        "all_lead_times_min": all_lead_times,
        "mean_lead_time_min": float(np.mean(all_lead_times)) if all_lead_times else float("nan"),
        "median_lead_time_min": float(np.median(all_lead_times)) if all_lead_times else float("nan"),
    }


if __name__ == "__main__":
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.data_loader import load_light_curve
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.preprocessing import build_feature_frame

    df = load_light_curve()
    feat = build_feature_frame(df)
    catalogue = pd.read_csv(config.SAMPLE_DIR / "ground_truth_flares.csv")

    results = train_forecaster(feat, catalogue)
    print(f"Validation AUC: {results['val_auc']:.3f}")
    print(f"Test AUC:       {results['test_auc']:.3f}")

    _, _, t_test = results["splits"]["test"]

    print("\nThreshold sweep (single chronological test split - small sample, noisy):")
    sweep_df = sweep_thresholds(t_test, results["test_proba"], catalogue)
    print(sweep_df.to_string(index=False))

    print("\n" + "=" * 70)
    print("WALK-FORWARD EVALUATION (recommended metric - aggregates across")
    print("multiple chronological folds for a statistically robust estimate)")
    print("=" * 70)
    wf = walk_forward_evaluate(feat, catalogue, n_folds=4)
    print(f"(using config.ALERT_PROBABILITY_THRESHOLD = {config.ALERT_PROBABILITY_THRESHOLD})")
    print(wf["fold_summaries"][["fold", "n_qualifying_flares_in_test", "n_detected",
                                  "true_positive_rate", "false_alarm_rate"]].to_string(index=False))
    print(f"\nOverall True Positive Rate: {wf['overall_true_positive_rate']:.2%} "
          f"({wf['total_detected']}/{wf['total_qualifying']} flares detected)")
    print(f"Overall False Alarm Rate (mean across folds): {wf['overall_false_alarm_rate']:.2%}")
    print(f"Median Lead Time: {wf['median_lead_time_min']:.1f} minutes")
    print(f"All lead times (min): {[round(x,1) for x in wf['all_lead_times_min']]}")
