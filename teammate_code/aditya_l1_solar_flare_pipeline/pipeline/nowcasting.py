"""
nowcasting.py
=============
Real-time flare DETECTION (not prediction). Implements the pipeline's
Objective 1 and the "Algorithmic Nowcasting" step in the brief:

    1. Detect flare-like rises independently in SXR and in HXR.
    2. Combine the two independent event lists into ONE master catalogue,
       requiring (or scoring up) temporal coincidence between channels,
       since a real flare lights up both bands while an instrument
       glitch in only one channel should not.

ALGORITHM (per channel)
------------------------
This is a classic "threshold + state machine" flare-detection algorithm,
the same family used operationally by NOAA/GOES flare alerts:

  QUIET --(excess crosses rise threshold, sustained MIN_RISE_DURATION_S)-->
  RISING --(local max reached, flux stops increasing)-->
  DECAYING --(excess decays to END_DROP_FRACTION of peak-above-background)-->
  QUIET (event closed, written to that channel's catalogue)

Each channel's catalogue records: onset, peak time, peak value, end time,
estimated flare class (from SXR peak flux; HXR-only detections get a
HXR-based proxy class).

COMBINING INTO A MASTER CATALOGUE
-----------------------------------
For each SXR event we search HEL1OS's HXR event list for any HXR event
whose peak falls within COINCIDENCE_WINDOW_MIN of the SXR onset/peak.
  - SXR event WITH a coincident HXR event -> "confirmed" flare (high
    confidence; both thermal and non-thermal/particle signatures seen).
  - SXR event with NO coincident HXR event -> "sxr_only" (still reported,
    lower confidence flag - could be a smaller/cooler event below HEL1OS's
    sensitivity, or a SoLEXS-side artifact).
  - HXR event with NO coincident SXR event -> "hxr_only" (e.g. a compact
    impulsive burst, or noise spike in HEL1OS - flagged for review).
This mirrors how real multi-instrument solar flare catalogues (e.g.
combining GOES with RHESSI/Fermi) are built.
"""

import numpy as np
import pandas as pd

from . import config
from .preprocessing import flux_to_flare_class


def _detect_events_single_channel(
    time: pd.Series,
    excess: pd.Series,
    ratio: pd.Series,
    raw_value: pd.Series,
    quality: pd.Series,
    rise_threshold_ratio=None,
    rise_threshold_sigma=None,
    use_ratio=True,
):
    """
    State-machine event detector for one channel (SXR or HXR).
    Returns a list of dicts: onset_time, peak_time, peak_value, end_time.
    """
    n = len(time)
    cadence = config.RESAMPLE_CADENCE_S
    min_rise_samples = max(1, config.MIN_RISE_DURATION_S // cadence)
    peak_search_samples = max(1, (config.PEAK_SEARCH_WINDOW_MIN * 60) // cadence)

    excess_arr = excess.to_numpy()
    ratio_arr = ratio.to_numpy()
    raw_arr = raw_value.to_numpy()
    quality_arr = quality.to_numpy()
    time_arr = time.to_numpy()

    # Trigger condition evaluated at each sample
    if use_ratio and rise_threshold_ratio is not None:
        trigger_mask = (ratio_arr >= rise_threshold_ratio) & (quality_arr == 0)
    else:
        # sigma-based trigger: excess - baseline_noise compared to estimated sigma
        sigma = np.nanstd(excess_arr[excess_arr > 0]) if np.any(excess_arr > 0) else 1.0
        sigma = max(sigma, 1e-12)
        trigger_mask = (excess_arr >= rise_threshold_sigma * sigma) & (quality_arr == 0)

    events = []
    i = 0
    while i < n:
        if not trigger_mask[i]:
            i += 1
            continue

        # require sustained trigger for MIN_RISE_DURATION_S before confirming onset
        j = i
        while j < n and trigger_mask[j]:
            j += 1
        run_length = j - i
        if run_length < min_rise_samples:
            i = j
            continue

        onset_idx = i
        # search forward for the peak within PEAK_SEARCH_WINDOW_MIN
        search_end = min(n, onset_idx + peak_search_samples)
        peak_idx = onset_idx + int(np.argmax(excess_arr[onset_idx:search_end]))
        peak_value_excess = excess_arr[peak_idx]
        peak_value_raw = raw_arr[peak_idx]

        # search forward from peak for decay below END_DROP_FRACTION of peak excess
        decay_threshold = peak_value_excess * config.END_DROP_FRACTION
        end_idx = peak_idx
        k = peak_idx
        max_end_search = min(n, peak_idx + peak_search_samples)
        while k < max_end_search and excess_arr[k] > decay_threshold:
            k += 1
        end_idx = min(k, n - 1)

        events.append({
            "onset_time": pd.Timestamp(time_arr[onset_idx]),
            "peak_time": pd.Timestamp(time_arr[peak_idx]),
            "end_time": pd.Timestamp(time_arr[end_idx]),
            "peak_value_raw": float(peak_value_raw),
            "peak_value_excess": float(peak_value_excess),
        })

        # resume scanning after this event's end to avoid re-triggering on its own decay tail
        i = max(end_idx, j) + 1

    events = _merge_fragmented_events(events)
    return events


def _merge_fragmented_events(events, max_gap_s=None):
    """
    Merge consecutive events whose gap (next onset - previous end) is
    small. This handles a realistic detector artifact: a slow pre-flare
    brightening ramp can dip briefly below the rise threshold right before
    the main flare onset, causing the state machine to close one event and
    immediately open another for what is physically a single flare. Real
    operational flare catalogues (e.g. NOAA SWPC) apply an equivalent
    de-fragmentation step. max_gap_s defaults to 600s (10 min).
    """
    if not events:
        return events
    max_gap_s = max_gap_s if max_gap_s is not None else 600  # 10 minutes
    max_gap = pd.Timedelta(seconds=max_gap_s)

    merged = [events[0]]
    for ev in events[1:]:
        prev = merged[-1]
        if (ev["onset_time"] - prev["end_time"]) <= max_gap:
            # extend previous event; keep whichever peak is larger
            prev["end_time"] = max(prev["end_time"], ev["end_time"])
            if ev["peak_value_excess"] > prev["peak_value_excess"]:
                prev["peak_time"] = ev["peak_time"]
                prev["peak_value_raw"] = ev["peak_value_raw"]
                prev["peak_value_excess"] = ev["peak_value_excess"]
        else:
            merged.append(ev)

    return merged


def detect_sxr_events(feat: pd.DataFrame) -> pd.DataFrame:
    events = _detect_events_single_channel(
        time=feat[config.TIME_COL],
        excess=feat["sxr_excess"],
        ratio=feat["sxr_ratio"],
        raw_value=feat[config.SXR_COL],
        quality=feat[config.SXR_QUALITY_COL],
        rise_threshold_ratio=config.SXR_RISE_THRESHOLD_RATIO,
        use_ratio=True,
    )
    df = pd.DataFrame(events)
    if len(df):
        df["flare_class"] = df["peak_value_raw"].apply(flux_to_flare_class)
        df["channel"] = "SXR"
    return df


def detect_hxr_events(feat: pd.DataFrame) -> pd.DataFrame:
    events = _detect_events_single_channel(
        time=feat[config.TIME_COL],
        excess=feat["hxr_excess"],
        ratio=feat["hxr_ratio"],
        raw_value=feat[config.HXR_COL],
        quality=feat[config.HXR_QUALITY_COL],
        rise_threshold_sigma=config.HXR_RISE_THRESHOLD_SIGMA,
        use_ratio=False,
    )
    df = pd.DataFrame(events)
    if len(df):
        df["flare_class"] = "HXR-only (no SXR class)"
        df["channel"] = "HXR"
    return df


def build_master_catalogue(sxr_events: pd.DataFrame, hxr_events: pd.DataFrame) -> pd.DataFrame:
    """
    Combine independent SXR and HXR event catalogues into one master
    catalogue, tagging each event with a confidence level based on
    cross-channel coincidence.
    """
    coincidence_window = pd.Timedelta(minutes=config.COINCIDENCE_WINDOW_MIN)
    master_rows = []
    matched_hxr_idx = set()

    sxr_events = sxr_events.sort_values("onset_time").reset_index(drop=True) if len(sxr_events) else sxr_events
    hxr_events = hxr_events.sort_values("onset_time").reset_index(drop=True) if len(hxr_events) else hxr_events

    for _, sxr_ev in sxr_events.iterrows():
        coincident = pd.DataFrame()
        if len(hxr_events):
            # Compare against the SXR PEAK time, not onset. Onset now
            # includes any slow precursor ramp the detector latched onto,
            # which can precede the main HXR burst by more than a typical
            # coincidence window even though they are the same physical
            # event - the SXR and HXR peaks remain tightly coupled
            # (Neupert effect), so peak-to-peak comparison is the robust
            # coincidence criterion.
            time_diff = (hxr_events["peak_time"] - sxr_ev["peak_time"]).abs()
            coincident_mask = time_diff <= coincidence_window
            coincident = hxr_events[coincident_mask]

        if len(coincident):
            # Pick the STRONGEST coincident HXR event as the "main burst"
            # match (not just the first chronologically) - this matters
            # once small precursor micro-bursts are present in the same
            # coincidence window as the main flare-associated HXR burst.
            best_match_idx = coincident["peak_value_raw"].idxmax()
            best_match = coincident.loc[best_match_idx]
            # All coincident HXR events (main burst + any micro-bursts in
            # the same window) belong to this one flare and should not
            # also appear as separate hxr_only entries.
            matched_hxr_idx.update(coincident.index)
            hxr_lead_minutes = (sxr_ev["peak_time"] - best_match["peak_time"]).total_seconds() / 60.0
            master_rows.append({
                "event_id": f"FLR_{len(master_rows)+1:04d}",
                "status": "confirmed",
                "confidence": "high",
                "onset_time": sxr_ev["onset_time"],
                "peak_time_sxr": sxr_ev["peak_time"],
                "peak_time_hxr": best_match["peak_time"],
                "end_time": sxr_ev["end_time"],
                "flare_class": sxr_ev["flare_class"],
                "peak_sxr_flux_w_m2": sxr_ev["peak_value_raw"],
                "peak_hxr_counts_s": best_match["peak_value_raw"],
                "hxr_leads_sxr_minutes": hxr_lead_minutes,
            })
        else:
            master_rows.append({
                "event_id": f"FLR_{len(master_rows)+1:04d}",
                "status": "sxr_only",
                "confidence": "medium",
                "onset_time": sxr_ev["onset_time"],
                "peak_time_sxr": sxr_ev["peak_time"],
                "peak_time_hxr": None,
                "end_time": sxr_ev["end_time"],
                "flare_class": sxr_ev["flare_class"],
                "peak_sxr_flux_w_m2": sxr_ev["peak_value_raw"],
                "peak_hxr_counts_s": None,
                "hxr_leads_sxr_minutes": None,
            })

    if len(hxr_events):
        unmatched_hxr = hxr_events.loc[~hxr_events.index.isin(matched_hxr_idx)]
        for _, hxr_ev in unmatched_hxr.iterrows():
            master_rows.append({
                "event_id": f"FLR_{len(master_rows)+1:04d}",
                "status": "hxr_only",
                "confidence": "low",
                "onset_time": hxr_ev["onset_time"],
                "peak_time_sxr": None,
                "peak_time_hxr": hxr_ev["peak_time"],
                "end_time": hxr_ev["end_time"],
                "flare_class": "Unclassified (HXR-only)",
                "peak_sxr_flux_w_m2": None,
                "peak_hxr_counts_s": hxr_ev["peak_value_raw"],
                "hxr_leads_sxr_minutes": None,
            })

    master_df = pd.DataFrame(master_rows)
    if len(master_df):
        master_df = master_df.sort_values("onset_time").reset_index(drop=True)
        master_df["event_id"] = [f"FLR_{i+1:04d}" for i in range(len(master_df))]
    return master_df


def run_nowcasting_pipeline(feat: pd.DataFrame, save=True):
    """Full nowcasting run: detect both channels, combine, optionally save catalogue CSV."""
    sxr_events = detect_sxr_events(feat)
    hxr_events = detect_hxr_events(feat)
    master = build_master_catalogue(sxr_events, hxr_events)

    if save:
        master.to_csv(config.OUTPUT_DIR / "nowcast_master_catalogue.csv", index=False)
        sxr_events.to_csv(config.OUTPUT_DIR / "nowcast_sxr_events.csv", index=False)
        hxr_events.to_csv(config.OUTPUT_DIR / "nowcast_hxr_events.csv", index=False)

    return master, sxr_events, hxr_events


if __name__ == "__main__":
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.data_loader import load_light_curve
    from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.preprocessing import build_feature_frame

    df = load_light_curve()
    feat = build_feature_frame(df)
    master, sxr_ev, hxr_ev = run_nowcasting_pipeline(feat)

    print(f"SXR-channel events detected: {len(sxr_ev)}")
    print(f"HXR-channel events detected: {len(hxr_ev)}")
    print(f"\nMaster catalogue ({len(master)} events):")
    cols = ["event_id", "status", "confidence", "onset_time", "flare_class", "hxr_leads_sxr_minutes"]
    print(master[cols].to_string(index=False))
