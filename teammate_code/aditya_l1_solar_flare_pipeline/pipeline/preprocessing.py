"""
preprocessing.py
================
Turns raw (time, sxr_flux, hxr_flux) into an analysis-ready DataFrame with:
  - rolling background estimate per channel (quiet-sun level)
  - background-subtracted "excess" flux per channel
  - smoothed (denoised) flux per channel
  - rate-of-change (derivative) per channel - precursor signal lives here
  - rolling statistics (std, skew) used as forecasting features

This module is shared by BOTH the nowcasting and forecasting subsystems so
background estimation logic never has to be duplicated/maintained twice.
"""

import numpy as np
import pandas as pd

from . import config


def estimate_background(series: pd.Series, window_s: int, percentile: float) -> pd.Series:
    """
    Rolling low-percentile background estimate. Using a percentile rather
    than a mean is standard in flare detection: it is robust to the flares
    themselves pulling a mean upward, since true "quiet" samples dominate
    most windows and a low percentile ignores the elevated flare tail.
    """
    window_samples = max(3, window_s // config.RESAMPLE_CADENCE_S)
    bg = series.rolling(window=window_samples, center=True, min_periods=max(3, window_samples // 4)) \
               .quantile(percentile / 100.0)
    bg = bg.bfill().ffill()
    return bg


def smooth(series: pd.Series, window_s: int = 15) -> pd.Series:
    """Light smoothing to suppress instrument shot-noise without washing out flare shape."""
    window_samples = max(1, window_s // config.RESAMPLE_CADENCE_S)
    return series.rolling(window=window_samples, center=True, min_periods=1).mean()


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Main preprocessing entry point.
    Input: standardized light curve df (config.REQUIRED_COLUMNS)
    Output: same df + derived columns:
        sxr_smooth, hxr_smooth
        sxr_background, hxr_background
        sxr_excess, hxr_excess           (smoothed - background, floor 0)
        sxr_ratio, hxr_ratio             (smoothed / background)
        sxr_slope, hxr_slope             (d/dt of smoothed excess, per minute)
        sxr_excess_std_5min, hxr_excess_std_5min   (rolling volatility)
    """
    out = df.copy()
    bg_window_s = config.BACKGROUND_WINDOW_MIN * 60
    pct = config.BACKGROUND_PERCENTILE

    out["sxr_smooth"] = smooth(out[config.SXR_COL])
    out["hxr_smooth"] = smooth(out[config.HXR_COL])

    out["sxr_background"] = estimate_background(out[config.SXR_COL], bg_window_s, pct)
    out["hxr_background"] = estimate_background(out[config.HXR_COL], bg_window_s, pct)

    out["sxr_excess"] = (out["sxr_smooth"] - out["sxr_background"]).clip(lower=0)
    out["hxr_excess"] = (out["hxr_smooth"] - out["hxr_background"]).clip(lower=0)

    out["sxr_ratio"] = out["sxr_smooth"] / out["sxr_background"].replace(0, np.nan)
    out["hxr_ratio"] = out["hxr_smooth"] / out["hxr_background"].replace(0, np.nan)

    dt_min = config.RESAMPLE_CADENCE_S / 60.0
    out["sxr_slope"] = out["sxr_excess"].diff() / dt_min
    out["hxr_slope"] = out["hxr_excess"].diff() / dt_min

    roll_5min = max(1, (5 * 60) // config.RESAMPLE_CADENCE_S)
    out["sxr_excess_std_5min"] = out["sxr_excess"].rolling(roll_5min, min_periods=1).std().fillna(0)
    out["hxr_excess_std_5min"] = out["hxr_excess"].rolling(roll_5min, min_periods=1).std().fillna(0)

    return out


def flux_to_flare_class(flux_w_m2: float) -> str:
    """Convert a SXR flux value (W/m^2) to GOES-style class letter + magnitude, e.g. 'C3.2'."""
    if pd.isna(flux_w_m2) or flux_w_m2 <= 0:
        return "Quiet"
    order = config.FLARE_CLASS_ORDER
    thresholds = config.FLARE_CLASS_THRESHOLDS
    letter = None
    for cls in reversed(order):
        if flux_w_m2 >= thresholds[cls]:
            letter = cls
            break
    if letter is None:
        return "Sub-A"
    magnitude = flux_w_m2 / thresholds[letter]
    return f"{letter}{magnitude:.1f}"


if __name__ == "__main__":
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.data_loader import load_light_curve
    df = load_light_curve()
    feat = build_feature_frame(df)
    print(feat[["time", "sxr_flux", "sxr_background", "sxr_excess", "hxr_excess"]].describe())
    print("\nSample flare-class conversions:")
    for f in [5e-9, 5e-8, 5e-7, 3.2e-6, 5e-5, 2e-4]:
        print(f"  {f:.1e} W/m^2 -> {flux_to_flare_class(f)}")
