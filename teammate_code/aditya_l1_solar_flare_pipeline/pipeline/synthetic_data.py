"""
synthetic_data.py
==================
Generates physically-plausible synthetic SoLEXS (soft X-ray) and HEL1OS
(hard X-ray) light curves, standing in for real ISSDC data until it is
downloaded.

PHYSICS MODELED (kept simple but directionally correct)
---------------------------------------------------------
1. Quiet-sun background: slowly drifting baseline + Gaussian noise, in both
   channels independently (SXR and HXR backgrounds are NOT perfectly
   correlated in reality).
2. Flare shape: fast exponential rise + slower exponential decay
   (standard "FRED" - Fast Rise Exponential Decay - profile used widely in
   solar flare light curve modeling).
3. Neupert effect: HXR (driven by particle acceleration / chromospheric
   evaporation) peaks BEFORE the SXR peak (thermal plasma, integrates the
   energy deposited by HXR-producing electrons). We inject a realistic lag
   (HXR leads SXR by ~1-8 minutes depending on flare class) - this lag is
   exactly the kind of "precursor pattern" objective 2 of the problem
   statement asks us to learn.
4. Flare size variability: class A/B/C/M/X drawn from a distribution that
   resembles real solar cycle statistics (lots of small flares, few big
   ones - roughly power-law).
5. Occasional data gaps / quality flags to mimic real instrument dropouts,
   so the pipeline is forced to handle them robustly from day one.

OUTPUT
------
Returns a DataFrame matching config.REQUIRED_COLUMNS exactly, plus writes
a ground-truth flare catalogue (data/sample/ground_truth_flares.csv) used
ONLY for evaluation - the detection/forecasting algorithms never see it.
"""

import numpy as np
import pandas as pd
from pathlib import Path

from . import config


def _fred_profile(t_rel_s, rise_tau_s, decay_tau_s, peak_amp):
    """
    Fast-Rise-Exponential-Decay profile, the standard parametric shape
    used for solar/stellar flare light curves.
    t_rel_s: time relative to flare onset, seconds (can be negative)
    """
    y = np.zeros_like(t_rel_s, dtype=float)
    rise_mask = t_rel_s >= 0
    # rise phase: 1 - exp(-t/tau_rise), saturating to peak
    y[rise_mask] = peak_amp * (1 - np.exp(-t_rel_s[rise_mask] / rise_tau_s))
    # find peak time (approx where rise saturates ~99%) then decay
    return y


def _flare_light_curve(t_rel_s, rise_tau_s, decay_tau_s, peak_amp, peak_time_s):
    """
    Full FRED shape: rise up to peak_time_s, exponential decay after.
    """
    y = np.zeros_like(t_rel_s, dtype=float)
    before = t_rel_s <= peak_time_s
    after = ~before
    # rise: smooth ramp from 0 to peak_amp
    with np.errstate(over="ignore"):
        y[before] = peak_amp * (1 - np.exp(-(t_rel_s[before]) / rise_tau_s))
        y[before] = np.clip(y[before], 0, peak_amp)
        y[after] = peak_amp * np.exp(-(t_rel_s[after] - peak_time_s) / decay_tau_s)
    return y


def _sample_flare_class(rng):
    """Roughly power-law: lots of A/B, fewer C, few M, rare X."""
    classes = ["A", "B", "C", "M", "X"]
    probs = [0.30, 0.32, 0.25, 0.10, 0.03]
    return rng.choice(classes, p=probs)


def _class_to_peak_flux(flare_class, rng):
    """Sample a peak SXR flux (W/m^2) within the class decade, e.g. C-class -> [1e-6, 1e-5)."""
    base = config.FLARE_CLASS_THRESHOLDS[flare_class]
    # next threshold up (or 10x base for X class which has no upper bound here)
    order = config.FLARE_CLASS_ORDER
    idx = order.index(flare_class)
    upper = config.FLARE_CLASS_THRESHOLDS[order[idx + 1]] if idx + 1 < len(order) else base * 10
    frac = rng.uniform(0.1, 0.95)  # e.g. "C3.2" vs "C9.8"
    return base + frac * (upper - base)


def generate_synthetic_dataset(
    duration_hours=None,
    n_flares=None,
    seed=None,
    save=True,
):
    """
    Main entry point. Returns (df, flare_catalogue_df).

    df: standardized light curve DataFrame (config.REQUIRED_COLUMNS)
    flare_catalogue_df: ground truth, columns =
        [flare_id, class, peak_flux_sxr, onset_time, peak_time_sxr,
         peak_time_hxr, end_time, hxr_sxr_lag_min]
    """
    duration_hours = duration_hours or config.SYNTH_DURATION_HOURS
    n_flares = n_flares or config.SYNTH_N_FLARES
    seed = seed if seed is not None else config.SYNTH_SEED
    rng = np.random.default_rng(seed)

    n_seconds = int(duration_hours * 3600)
    cadence = config.RESAMPLE_CADENCE_S
    n_samples = n_seconds // cadence

    t0 = pd.Timestamp("2026-01-01T00:00:00Z")
    time_index = t0 + pd.to_timedelta(np.arange(n_samples) * cadence, unit="s")
    t_seconds = np.arange(n_samples) * cadence

    # ---------------------------------------------------------------
    # 1. Quiet-sun background (slow drift + noise), independent per channel
    # ---------------------------------------------------------------
    # SXR background drifts slowly between B-class-ish quiet levels
    sxr_background_level = 3e-8
    sxr_drift = sxr_background_level * (
        1 + 0.3 * np.sin(2 * np.pi * t_seconds / (6 * 3600) + rng.uniform(0, 2 * np.pi))
    )
    sxr_noise = rng.normal(0, sxr_background_level * 0.08, n_samples)
    sxr_flux = sxr_drift + sxr_noise

    hxr_background_level = 5.0  # counts/s, quiet sun
    hxr_drift = hxr_background_level * (
        1 + 0.25 * np.sin(2 * np.pi * t_seconds / (5 * 3600) + rng.uniform(0, 2 * np.pi))
    )
    hxr_noise = rng.normal(0, hxr_background_level * 0.15, n_samples)
    hxr_flux = hxr_drift + hxr_noise

    # ---------------------------------------------------------------
    # 2. Inject flares at random (non-overlapping) onset times
    # ---------------------------------------------------------------
    min_gap_s = 2 * 3600  # at least 2 hours between flare onsets, for clarity
    max_onset_s = n_seconds - 30 * 60
    onset_candidates = []
    attempts = 0
    while len(onset_candidates) < n_flares and attempts < n_flares * 50:
        candidate = rng.uniform(20 * 60, max_onset_s)
        if all(abs(candidate - c) > min_gap_s for c in onset_candidates):
            onset_candidates.append(candidate)
        attempts += 1
    onset_candidates.sort()

    catalogue_rows = []
    for i, onset_s in enumerate(onset_candidates):
        flare_class = _sample_flare_class(rng)
        peak_sxr_flux = _class_to_peak_flux(flare_class, rng)
        amp_sxr = peak_sxr_flux - sxr_background_level

        # Bigger flares -> longer rise/decay (well-known empirical scaling)
        size_factor = np.log10(peak_sxr_flux / 1e-8)  # ~0 (A) to ~4 (X)
        sxr_rise_tau = 60 + 40 * size_factor          # seconds
        sxr_decay_tau = 300 + 250 * size_factor        # seconds, decay >> rise

        rel_t = t_seconds - onset_s
        # only compute within a reasonable window around the flare for speed
        window_mask = (rel_t > -600) & (rel_t < 3 * sxr_decay_tau + 1800)
        peak_time_s_sxr = 3 * sxr_rise_tau  # approx saturation point of rise

        sxr_contrib = np.zeros(n_samples)
        sxr_contrib[window_mask] = _flare_light_curve(
            rel_t[window_mask], sxr_rise_tau, sxr_decay_tau, amp_sxr, peak_time_s_sxr
        )

        # ---------------------------------------------------------------
        # PRECURSOR SIGNAL (pre-flare brightening + micro-bursts)
        # ---------------------------------------------------------------
        # Physically motivated by real observations: active regions about
        # to flare often show (a) a slow brightening / "pre-heating" of
        # soft X-rays over ~10-25 minutes before onset, and (b) small
        # impulsive micro-bursts in hard X-rays as magnetic reconnection
        # "tests" before the main eruption. We inject both, with amplitude
        # scaling with eventual flare size (bigger flares -> more obvious
        # precursor activity), so a forecasting model has real signal to
        # learn from. NOT every flare gets a strong precursor (some flares
        # are genuinely impulsive/sudden in reality too) - we randomize
        # precursor strength so the model must learn a probabilistic
        # pattern, not a deterministic rule.
        precursor_duration_s = rng.uniform(8, 25) * 60
        precursor_strength = rng.uniform(0.05, 0.35) * (1 + 0.3 * size_factor)  # fraction of flare amplitude
        precursor_mask = (rel_t > -precursor_duration_s) & (rel_t <= 0)
        if precursor_mask.any():
            # smooth ramp from 0 to precursor_strength*amp_sxr over the precursor window
            precursor_rel = rel_t[precursor_mask] + precursor_duration_s  # 0 .. duration
            precursor_shape = (precursor_rel / precursor_duration_s) ** 1.5  # accelerating ramp
            sxr_contrib[precursor_mask] += precursor_strength * amp_sxr * precursor_shape

        sxr_flux = sxr_flux + sxr_contrib

        # HXR: Neupert effect -> HXR burst leads SXR peak. Lag scales mildly
        # with flare size (bigger flares -> slightly longer impulsive phase).
        hxr_lag_s = rng.uniform(60, 90) + 30 * size_factor  # ~1-8 min lead
        hxr_onset_s = onset_s - rng.uniform(0, 20)  # HXR often starts almost with onset
        amp_hxr = hxr_background_level * (5 + 40 * size_factor) * rng.uniform(0.7, 1.4)
        hxr_rise_tau = 15 + 10 * size_factor
        hxr_decay_tau = 40 + 30 * size_factor
        rel_t_hxr = t_seconds - hxr_onset_s
        peak_time_s_hxr = 2 * hxr_rise_tau
        window_mask_hxr = (rel_t_hxr > -300) & (rel_t_hxr < 3 * hxr_decay_tau + 600)
        hxr_contrib = np.zeros(n_samples)
        hxr_contrib[window_mask_hxr] = _flare_light_curve(
            rel_t_hxr[window_mask_hxr], hxr_rise_tau, hxr_decay_tau, amp_hxr, peak_time_s_hxr
        )

        # HXR micro-bursts during the precursor window: a few short
        # (5-20s) impulsive spikes, amplitude well below the main burst.
        n_microbursts = rng.integers(0, 4)
        for _ in range(n_microbursts):
            mb_offset_s = rng.uniform(precursor_duration_s * 0.2, precursor_duration_s * 1.1)
            mb_time_s = onset_s - mb_offset_s
            mb_amp = amp_hxr * rng.uniform(0.08, 0.25)
            mb_tau = rng.uniform(3, 8)
            rel_t_mb = t_seconds - mb_time_s
            mb_window = np.abs(rel_t_mb) < 60
            if mb_window.any():
                hxr_contrib[mb_window] += mb_amp * np.exp(-0.5 * (rel_t_mb[mb_window] / mb_tau) ** 2)

        hxr_flux = hxr_flux + hxr_contrib

        peak_time_sxr_abs = onset_s + peak_time_s_sxr
        peak_time_hxr_abs = hxr_onset_s + peak_time_s_hxr
        end_time_abs = onset_s + peak_time_s_sxr + 2.0 * sxr_decay_tau

        catalogue_rows.append({
            "flare_id": f"SYN_{i+1:03d}",
            "class": flare_class,
            "peak_flux_sxr_w_m2": peak_sxr_flux,
            "onset_time": t0 + pd.to_timedelta(onset_s, unit="s"),
            "peak_time_sxr": t0 + pd.to_timedelta(peak_time_sxr_abs, unit="s"),
            "peak_time_hxr": t0 + pd.to_timedelta(peak_time_hxr_abs, unit="s"),
            "end_time": t0 + pd.to_timedelta(end_time_abs, unit="s"),
            "hxr_leads_sxr_minutes": (peak_time_sxr_abs - peak_time_hxr_abs) / 60.0,
        })

    flare_catalogue_df = pd.DataFrame(catalogue_rows)

    # ---------------------------------------------------------------
    # 3. Quality flags + occasional data dropouts (realism)
    # ---------------------------------------------------------------
    sxr_quality = np.zeros(n_samples, dtype=np.int8)
    hxr_quality = np.zeros(n_samples, dtype=np.int8)

    n_dropouts = rng.integers(3, 7)
    for _ in range(n_dropouts):
        start = rng.integers(0, n_samples - 1)
        length = rng.integers(30, 300)  # 30s - 5min dropout
        end = min(start + length, n_samples)
        # randomly affect one or both channels
        if rng.random() < 0.5:
            sxr_flux[start:end] = np.nan
            sxr_quality[start:end] = 1
        else:
            hxr_flux[start:end] = np.nan
            hxr_quality[start:end] = 1

    # Forward-fill small gaps to emulate instrument-side interpolation,
    # but KEEP the quality flag so downstream code knows it's not a real measurement.
    sxr_flux = pd.Series(sxr_flux).ffill().bfill().to_numpy()
    hxr_flux = pd.Series(hxr_flux).ffill().bfill().to_numpy()

    # floors (flux/counts can't be negative)
    sxr_flux = np.clip(sxr_flux, 1e-9, None)
    hxr_flux = np.clip(hxr_flux, 0, None)

    df = pd.DataFrame({
        config.TIME_COL: time_index,
        config.SXR_COL: sxr_flux,
        config.HXR_COL: hxr_flux,
        config.SXR_QUALITY_COL: sxr_quality,
        config.HXR_QUALITY_COL: hxr_quality,
    })

    if save:
        df.to_parquet(config.SAMPLE_DIR / "synthetic_light_curve.parquet", index=False)
        flare_catalogue_df.to_csv(config.SAMPLE_DIR / "ground_truth_flares.csv", index=False)

    return df, flare_catalogue_df


if __name__ == "__main__":
    df, cat = generate_synthetic_dataset()
    print(f"Generated {len(df):,} samples ({len(df)/3600:.1f} hours)")
    print(f"Injected {len(cat)} ground-truth flares:")
    print(cat[["flare_id", "class", "onset_time", "hxr_leads_sxr_minutes"]].to_string(index=False))
