"""
data_loader.py
==============
The ONLY module that needs to change when you switch from synthetic data
to real ISSDC SoLEXS/HEL1OS files.

Every function here returns a DataFrame matching config.REQUIRED_COLUMNS.
Downstream code (preprocessing, nowcasting, forecasting, dashboard) is
written against that schema only and does not care where the data came
from.
"""

import numpy as np
import pandas as pd

from . import config


def load_light_curve() -> pd.DataFrame:
    """
    Master entry point. Reads config.USE_SYNTHETIC and dispatches.
    """
    if config.USE_SYNTHETIC:
        return _load_synthetic()
    else:
        return _load_real_issdc_data()


def _load_synthetic() -> pd.DataFrame:
    """Load (and generate if missing) the cached synthetic dataset."""
    cache_path = config.SAMPLE_DIR / "synthetic_light_curve.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
    else:
        from teammate_code.aditya_l1_solar_flare_pipeline.pipeline.synthetic_data import generate_synthetic_dataset
        df, _ = generate_synthetic_dataset(save=True)
    return _validate_schema(df)


def _load_real_issdc_data() -> pd.DataFrame:
    """
    Load real SoLEXS and HEL1OS Level-1 products into the standardized
    schema. Supported input formats are FITS, CSV, and Parquet.

    Before first use with PRADAN files, inspect the payload table column
    names and update the candidates in config.py if the defaults do not
    match. The downstream pipeline does not need to change.
    """
    sxr_files = _discover_payload_files(config.SOLEXS_RAW_DIR)
    hxr_files = _discover_payload_files(config.HEL1OS_RAW_DIR)
    if not sxr_files:
        raise FileNotFoundError(f"No SoLEXS files found in {config.SOLEXS_RAW_DIR}")
    if not hxr_files:
        raise FileNotFoundError(f"No HEL1OS files found in {config.HEL1OS_RAW_DIR}")

    sxr_df = _load_payload_files(
        sxr_files,
        signal_col=config.SXR_COL,
        quality_col=config.SXR_QUALITY_COL,
        explicit_signal_columns=config.SOLEXS_SIGNAL_COLUMNS,
        signal_candidates=config.SOLEXS_SIGNAL_COLUMN_CANDIDATES,
        payload_name="SoLEXS",
    )
    hxr_df = _load_payload_files(
        hxr_files,
        signal_col=config.HXR_COL,
        quality_col=config.HXR_QUALITY_COL,
        explicit_signal_columns=config.HEL1OS_SIGNAL_COLUMNS,
        signal_candidates=config.HEL1OS_SIGNAL_COLUMN_CANDIDATES,
        payload_name="HEL1OS",
    )

    merged = _merge_payload_streams(sxr_df, hxr_df)
    cleaned = _clean_merged_light_curve(merged)
    validated = _validate_schema(cleaned)

    if config.SAVE_PROCESSED_REAL_DATA:
        validated.to_parquet(config.PROCESSED_REAL_LIGHT_CURVE, index=False)

    return validated


def _discover_payload_files(directory):
    files = []
    for pattern in config.REAL_DATA_FILE_PATTERNS:
        files.extend(directory.glob(pattern))
    return sorted(set(files))


def _load_payload_files(
    files,
    signal_col,
    quality_col,
    explicit_signal_columns,
    signal_candidates,
    payload_name,
):
    frames = []
    errors = []
    for fpath in files:
        try:
            raw = _read_table_file(fpath)
            frames.append(
                _standardize_payload_frame(
                    raw,
                    signal_col=signal_col,
                    quality_col=quality_col,
                    explicit_signal_columns=explicit_signal_columns,
                    signal_candidates=signal_candidates,
                    payload_name=payload_name,
                    source_name=str(fpath),
                )
            )
        except Exception as exc:
            errors.append(f"{fpath}: {exc}")

    if not frames:
        joined = "\n".join(errors[:8])
        raise RuntimeError(f"Could not load any {payload_name} files.\n{joined}")

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(config.TIME_COL).reset_index(drop=True)
    out = out.groupby(config.TIME_COL, as_index=False).agg({
        signal_col: "mean",
        quality_col: "max",
    })
    return out


def _read_table_file(fpath):
    suffix = fpath.suffix.lower()
    if suffix in {".fits", ".fit", ".fts"}:
        return _read_fits_table(fpath)
    if suffix == ".csv":
        return pd.read_csv(fpath)
    if suffix == ".parquet":
        return pd.read_parquet(fpath)
    raise ValueError(f"Unsupported file type: {fpath.suffix}")


def _read_fits_table(fpath):
    try:
        from astropy.io import fits
    except ImportError as exc:
        raise ImportError(
            "Reading FITS files requires astropy. Install it with "
            "`pip install astropy` or `pip install -r requirements.txt`."
        ) from exc

    with fits.open(fpath, memmap=False) as hdul:
        for hdu in hdul:
            data = getattr(hdu, "data", None)
            columns = getattr(data, "columns", None)
            if data is not None and columns is not None and len(columns.names):
                arr = np.array(data)
                arr = arr.byteswap().view(arr.dtype.newbyteorder("="))
                return pd.DataFrame(arr)
    raise ValueError("No binary table HDU found")


def _standardize_payload_frame(
    raw,
    signal_col,
    quality_col,
    explicit_signal_columns,
    signal_candidates,
    payload_name,
    source_name,
):
    if raw.empty:
        raise ValueError("file table is empty")

    time_source = _pick_column(raw, config.TIME_COLUMN_CANDIDATES, "time", payload_name, source_name)
    time = _parse_time(raw[time_source], payload_name, source_name)

    signal = _extract_signal(
        raw,
        explicit_columns=explicit_signal_columns,
        candidate_columns=signal_candidates,
        payload_name=payload_name,
        source_name=source_name,
    )

    quality_source = _pick_column(
        raw,
        config.QUALITY_COLUMN_CANDIDATES,
        "quality",
        payload_name,
        source_name,
        required=False,
    )
    if quality_source:
        quality = pd.to_numeric(raw[quality_source], errors="coerce").fillna(1)
        quality = (quality != 0).astype(np.int8)
    else:
        quality = pd.Series(np.zeros(len(raw), dtype=np.int8))

    out = pd.DataFrame({
        config.TIME_COL: time,
        signal_col: pd.to_numeric(signal, errors="coerce"),
        quality_col: quality.to_numpy(dtype=np.int8),
    })
    out.loc[out[signal_col].isna(), quality_col] = 1
    out = out.dropna(subset=[config.TIME_COL])
    return out


def _pick_column(raw, candidates, purpose, payload_name, source_name, required=True):
    normalized = {str(col).strip().lower(): col for col in raw.columns}
    for candidate in candidates:
        key = str(candidate).strip().lower()
        if key in normalized:
            return normalized[key]
    if required:
        raise ValueError(
            f"Could not find {purpose} column for {payload_name} in {source_name}. "
            f"Available columns: {list(raw.columns)}"
        )
    return None


def _extract_signal(raw, explicit_columns, candidate_columns, payload_name, source_name):
    normalized = {str(col).strip().lower(): col for col in raw.columns}
    if explicit_columns:
        resolved = []
        missing = []
        for col in explicit_columns:
            key = str(col).strip().lower()
            if key in normalized:
                resolved.append(normalized[key])
            else:
                missing.append(col)
        if missing:
            raise ValueError(f"Missing configured {payload_name} signal columns: {missing}")
        return raw[resolved].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)

    selected = _pick_column(raw, candidate_columns, "signal", payload_name, source_name)
    return raw[selected]


def _parse_time(values, payload_name, source_name):
    if config.REAL_TIME_NUMERIC_UNIT:
        return pd.to_datetime(
            pd.to_numeric(values, errors="coerce"),
            unit=config.REAL_TIME_NUMERIC_UNIT,
            origin=config.REAL_TIME_ORIGIN,
            utc=True,
        )

    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if parsed.notna().any():
        return parsed

    numeric_preview = pd.to_numeric(values, errors="coerce")
    if numeric_preview.notna().any():
        raise ValueError(
            f"{payload_name} time column in {source_name} appears numeric. "
            "Set REAL_TIME_NUMERIC_UNIT and REAL_TIME_ORIGIN in pipeline/config.py "
            "according to the FITS header or PRADAN product guide."
        )
    raise ValueError(f"Could not parse {payload_name} time column in {source_name}")


def _merge_payload_streams(sxr_df, hxr_df):
    tolerance = pd.Timedelta(seconds=config.REAL_MERGE_TOLERANCE_S)
    return pd.merge_asof(
        sxr_df.sort_values(config.TIME_COL),
        hxr_df.sort_values(config.TIME_COL),
        on=config.TIME_COL,
        direction="nearest",
        tolerance=tolerance,
    )


def _clean_merged_light_curve(df):
    df = df.copy()
    df[config.TIME_COL] = pd.to_datetime(df[config.TIME_COL], utc=True)
    df = df.sort_values(config.TIME_COL).drop_duplicates(config.TIME_COL)
    df = df.set_index(config.TIME_COL)

    cadence = f"{config.RESAMPLE_CADENCE_S}s"
    agg = {
        config.SXR_COL: "mean",
        config.HXR_COL: "mean",
        config.SXR_QUALITY_COL: "max",
        config.HXR_QUALITY_COL: "max",
    }
    df = df.resample(cadence).agg({k: v for k, v in agg.items() if k in df.columns})

    max_gap = max(0, int(config.MAX_INTERPOLATION_GAP_S / config.RESAMPLE_CADENCE_S))
    for signal_col, quality_col in [
        (config.SXR_COL, config.SXR_QUALITY_COL),
        (config.HXR_COL, config.HXR_QUALITY_COL),
    ]:
        if quality_col not in df.columns:
            df[quality_col] = 1
        original_missing = df[signal_col].isna()
        df[quality_col] = df[quality_col].fillna(1)
        df[signal_col] = pd.to_numeric(df[signal_col], errors="coerce")
        df[signal_col] = df[signal_col].interpolate(
            method="time",
            limit=max_gap if max_gap else None,
            limit_direction="both",
        )
        df.loc[original_missing, quality_col] = 1
        df.loc[df[signal_col].isna(), quality_col] = 1

    df[config.SXR_COL] = df[config.SXR_COL].clip(lower=1e-12)
    df[config.HXR_COL] = df[config.HXR_COL].clip(lower=0)
    df = df.dropna(subset=[config.SXR_COL, config.HXR_COL])
    df = df.reset_index()
    return df


def _validate_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the standardized schema contract on any loaded DataFrame."""
    missing = [c for c in config.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Loaded data is missing required columns: {missing}")

    df = df.copy()
    df[config.TIME_COL] = pd.to_datetime(df[config.TIME_COL], utc=True)
    df = df.sort_values(config.TIME_COL).reset_index(drop=True)

    # basic sanity checks
    if df[config.TIME_COL].duplicated().any():
        df = df.drop_duplicates(subset=[config.TIME_COL], keep="first")

    for col in [config.SXR_COL, config.HXR_COL]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in [config.SXR_QUALITY_COL, config.HXR_QUALITY_COL]:
        df[col] = df[col].fillna(1).astype(np.int8)

    return df[config.REQUIRED_COLUMNS]


if __name__ == "__main__":
    df = load_light_curve()
    print(df.head())
    print(f"\nLoaded {len(df):,} rows spanning "
          f"{df[config.TIME_COL].iloc[0]} to {df[config.TIME_COL].iloc[-1]}")
    print(f"\nQuality flag summary:")
    print(f"  SXR flagged: {df[config.SXR_QUALITY_COL].sum()} samples")
    print(f"  HXR flagged: {df[config.HXR_QUALITY_COL].sum()} samples")
