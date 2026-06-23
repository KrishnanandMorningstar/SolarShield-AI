"""
config.py
=========
Single source of truth for the whole pipeline.

WHY THIS FILE EXISTS
---------------------
The brief explicitly says: "when I get the actual ISSDC data, all I should
have to do is change the dataset". To make that literally true, every path,
column name, physical unit, and tunable threshold used anywhere in the
pipeline is defined HERE and nowhere else. Every other module imports from
this file instead of hard-coding values.

REAL DATA USAGE
----------------
1. Download SoLEXS L1 and HEL1OS L1 files from the ISSDC PRADAN portal.
2. Put them in data/raw/solexs/ and data/raw/hel1os/ (or change RAW_DIR below).
3. Check the actual column names in the downloaded files. If needed,
   update the REAL DATA INGESTION candidates below. The rest of the
   pipeline (preprocessing, nowcasting, forecasting, evaluation,
   dashboard) needs ZERO changes because they all consume the same
   standardized DataFrame schema defined below.
"""

from pathlib import Path

# --------------------------------------------------------------------------
# 0. MASTER SWITCH
# --------------------------------------------------------------------------
USE_SYNTHETIC = False  # Real-data-first. Use run_pipeline.py --source synthetic for validation.

# --------------------------------------------------------------------------
# 1. PATHS
# --------------------------------------------------------------------------
ROOT_DIR       = Path(__file__).resolve().parent.parent
DATA_DIR       = ROOT_DIR / "data"
RAW_DIR        = DATA_DIR / "raw"
SOLEXS_RAW_DIR = RAW_DIR / "solexs"     # real SoLEXS L1 files go here
HEL1OS_RAW_DIR = RAW_DIR / "hel1os"     # real HEL1OS L1 files go here
SAMPLE_DIR     = DATA_DIR / "sample"    # synthetic light curves cached here
PROCESSED_DIR  = DATA_DIR / "processed"
EXTERNAL_DIR   = DATA_DIR / "external"  # optional real flare catalogues go here
OUTPUT_DIR     = ROOT_DIR / "outputs"

for d in [SOLEXS_RAW_DIR, HEL1OS_RAW_DIR, SAMPLE_DIR, PROCESSED_DIR, EXTERNAL_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# 2. STANDARDIZED SCHEMA
# --------------------------------------------------------------------------
# Every loader (synthetic or real) MUST return a pandas DataFrame with
# *exactly* these columns. This is the contract that decouples data source
# from algorithms.
#
#   time        : pandas datetime64[ns], UTC, monotonic increasing
#   sxr_flux    : float, soft X-ray flux from SoLEXS, units W/m^2 (GOES-equivalent
#                 scaling so existing flare-class thresholds can be reused)
#   hxr_flux    : float, hard X-ray count rate from HEL1OS, units counts/s
#   sxr_quality : int8, 0 = good, 1 = flagged/interpolated/missing
#   hxr_quality : int8, 0 = good, 1 = flagged/interpolated/missing
#
TIME_COL = "time"
SXR_COL = "sxr_flux"
HXR_COL = "hxr_flux"
SXR_QUALITY_COL = "sxr_quality"
HXR_QUALITY_COL = "hxr_quality"

REQUIRED_COLUMNS = [TIME_COL, SXR_COL, HXR_COL, SXR_QUALITY_COL, HXR_QUALITY_COL]

# Native cadence we resample everything to (seconds). SoLEXS/HEL1OS nominal
# cadence is ~1s; we use 1s for nowcasting precision and later downsample
# for forecasting features.
RESAMPLE_CADENCE_S = 1

# --------------------------------------------------------------------------
# 2A. REAL DATA INGESTION AND CLEANING
# --------------------------------------------------------------------------
# The loader supports FITS, CSV, and Parquet files. FITS is the expected
# format for ISSDC PRADAN Level-1 products; CSV/Parquet support is useful
# if you first export payload tables with ISRO/mission tools.
REAL_DATA_FILE_PATTERNS = ["*.fits", "*.fit", "*.fts", "*.csv", "*.parquet"]

# Time parsing. If time values are ISO strings, leave REAL_TIME_NUMERIC_UNIT
# as None. If the PRADAN files store numeric mission time, set the unit and
# origin after checking the FITS header or product guide. Examples:
#   REAL_TIME_NUMERIC_UNIT = "s"; REAL_TIME_ORIGIN = "2024-01-01T00:00:00Z"
#   REAL_TIME_NUMERIC_UNIT = "ms"; REAL_TIME_ORIGIN = "unix"
REAL_TIME_NUMERIC_UNIT = None
REAL_TIME_ORIGIN = "unix"

# Column candidates are case-insensitive. Put exact PRADAN column names first
# once you inspect the real files. For signal columns, the loader can either
# pick one column from the candidate list or sum explicit channel columns.
TIME_COLUMN_CANDIDATES = ["time", "TIME", "timestamp", "DATE_TIME", "datetime", "utc_time", "UTC"]
QUALITY_COLUMN_CANDIDATES = ["quality", "QUALITY", "qual", "FLAG", "flags", "data_quality"]

SOLEXS_SIGNAL_COLUMNS = []  # optional explicit list; summed if provided
SOLEXS_SIGNAL_COLUMN_CANDIDATES = [
    "sxr_flux", "SXR_FLUX", "flux", "FLUX", "rate", "RATE",
    "counts", "COUNTS", "count_rate", "COUNT_RATE",
]

HEL1OS_SIGNAL_COLUMNS = []  # optional explicit list; summed if provided
HEL1OS_SIGNAL_COLUMN_CANDIDATES = [
    "hxr_flux", "HXR_FLUX", "count_rate", "COUNT_RATE", "counts",
    "COUNTS", "rate", "RATE", "flux", "FLUX",
]

# Cleaning policy applied after SXR/HXR merge.
REAL_MERGE_TOLERANCE_S = 2
MAX_INTERPOLATION_GAP_S = 10
SAVE_PROCESSED_REAL_DATA = True
PROCESSED_REAL_LIGHT_CURVE = PROCESSED_DIR / "real_light_curve_standardized.parquet"

# Optional external flare catalogue for real-data training/evaluation. If this
# CSV exists, run_pipeline.py uses it instead of self-labeling from nowcasts.
# Required columns: onset_time plus class or flare_class.
EXTERNAL_FLARE_CATALOGUE_PATH = EXTERNAL_DIR / "flare_catalogue.csv"

# --------------------------------------------------------------------------
# 3. FLARE CLASSIFICATION THRESHOLDS (GOES-style, W/m^2, 1-8 Angstrom analogue)
# --------------------------------------------------------------------------
# SoLEXS soft X-ray flux is scaled to be GOES-comparable so we can reuse
# the well-established NOAA flare class boundaries.
FLARE_CLASS_THRESHOLDS = {
    "A": 1e-8,
    "B": 1e-7,
    "C": 1e-6,
    "M": 1e-5,
    "X": 1e-4,
}
FLARE_CLASS_ORDER = ["A", "B", "C", "M", "X"]

# --------------------------------------------------------------------------
# 4. NOWCASTING (DETECTION) PARAMETERS
# --------------------------------------------------------------------------
# Background estimation
BACKGROUND_WINDOW_MIN = 60        # minutes, rolling window for background level
BACKGROUND_PERCENTILE = 10        # percentile used as "quiet sun" background

# Trigger / rise criteria (applied independently to SXR and HXR channels)
SXR_RISE_THRESHOLD_RATIO = 1.5    # flux must exceed background * this ratio
HXR_RISE_THRESHOLD_SIGMA = 4.0    # flux must exceed background + N*sigma
MIN_RISE_DURATION_S = 30          # sustained rise needed to avoid noise spikes
PEAK_SEARCH_WINDOW_MIN = 120      # max window to search for peak after trigger
END_DROP_FRACTION = 0.5           # flare "ends" when flux decays to this
                                   # fraction of (peak - background) above background

# Cross-channel correlation window for combining SXR+HXR detections into
# one master event (HXR precedes/coincides with SXR in real flares).
COINCIDENCE_WINDOW_MIN = 10

# --------------------------------------------------------------------------
# 5. FORECASTING PARAMETERS
# --------------------------------------------------------------------------
FORECAST_HORIZON_MIN = 30        # predict probability of flare in next N minutes
LOOKBACK_WINDOW_MIN = 60         # how much history feeds the feature window
FEATURE_STEP_MIN = 1             # stride for sliding-window feature extraction
MIN_FLARE_CLASS_FOR_POSITIVE = "C"   # label "1" only for C-class and above
                                       # (smaller flares too noisy to forecast reliably)

# Recommended operating threshold for alerting, chosen via walk-forward
# evaluation as a reasonable TPR/false-alarm-rate tradeoff (see README
# "Forecasting Results" section for the full sweep). Override per
# deployment risk appetite: lower -> more sensitive/more false alarms,
# higher -> fewer false alarms/may miss some events.
ALERT_PROBABILITY_THRESHOLD = 0.7

# Train/test split (chronological, NOT random, to avoid leakage)
TRAIN_FRACTION = 0.7
VAL_FRACTION = 0.15
# remaining 0.15 -> test

RANDOM_SEED = 42

# --------------------------------------------------------------------------
# 6. SYNTHETIC DATA GENERATION PARAMETERS (only used if USE_SYNTHETIC=True)
# --------------------------------------------------------------------------
SYNTH_DURATION_HOURS = 24 * 14     # 14 days -> enough C/M/X flares land in
                                    # every chronological split (train/val/test)
SYNTH_N_FLARES = 70                # number of injected flares
SYNTH_SEED = 7
