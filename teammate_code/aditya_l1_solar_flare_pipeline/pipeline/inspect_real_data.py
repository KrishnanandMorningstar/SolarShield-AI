"""
inspect_real_data.py
====================
Inspect real SoLEXS and HEL1OS payload files before running the pipeline.

Usage:
    python -m pipeline.inspect_real_data

The output lists discovered files, table columns, row counts, and basic
candidate matches. Use it to update the real-data column settings in
pipeline/config.py before running:

    python -m pipeline.run_pipeline --source real
"""

from pathlib import Path

import pandas as pd

from . import config


def _discover_files(directory: Path):
    files = []
    for pattern in config.REAL_DATA_FILE_PATTERNS:
        files.extend(directory.glob(pattern))
    return sorted(set(files))


def _read_columns(path: Path):
    suffix = path.suffix.lower()
    if suffix in {".fits", ".fit", ".fts"}:
        try:
            from astropy.io import fits
        except ImportError as exc:
            raise ImportError("Install astropy to inspect FITS files: pip install astropy") from exc

        with fits.open(path, memmap=False) as hdul:
            for idx, hdu in enumerate(hdul):
                data = getattr(hdu, "data", None)
                columns = getattr(data, "columns", None)
                if data is not None and columns is not None and len(columns.names):
                    return idx, list(columns.names), len(data)
        return None, [], 0

    if suffix == ".csv":
        sample = pd.read_csv(path, nrows=5)
        return None, list(sample.columns), None

    if suffix == ".parquet":
        sample = pd.read_parquet(path)
        return None, list(sample.columns), len(sample)

    return None, [], 0


def _matches(columns, candidates):
    lookup = {str(col).lower(): col for col in columns}
    found = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key in lookup:
            found.append(lookup[key])
    return found


def _print_payload(name, directory, signal_candidates):
    print("=" * 72)
    print(f"{name}: {directory}")
    files = _discover_files(directory)
    if not files:
        print("No files found.")
        return

    for path in files[:10]:
        print("-" * 72)
        print(path.name)
        hdu_idx, columns, n_rows = _read_columns(path)
        if hdu_idx is not None:
            print(f"table_hdu: {hdu_idx}")
        if n_rows is not None:
            print(f"rows: {n_rows}")
        print(f"columns: {columns}")
        print(f"time candidates found: {_matches(columns, config.TIME_COLUMN_CANDIDATES)}")
        print(f"quality candidates found: {_matches(columns, config.QUALITY_COLUMN_CANDIDATES)}")
        print(f"signal candidates found: {_matches(columns, signal_candidates)}")

    if len(files) > 10:
        print(f"... {len(files) - 10} more files not shown")


def main():
    _print_payload("SoLEXS", config.SOLEXS_RAW_DIR, config.SOLEXS_SIGNAL_COLUMN_CANDIDATES)
    _print_payload("HEL1OS", config.HEL1OS_RAW_DIR, config.HEL1OS_SIGNAL_COLUMN_CANDIDATES)


if __name__ == "__main__":
    main()
