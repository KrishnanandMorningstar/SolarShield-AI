"""
Aditya-L1 Solar Flare Pipeline
==============================
Scientific core: data ingestion, preprocessing, nowcasting (detection),
forecasting (precursor model), and dashboard export.

The web layer lives in the separate ``backend`` package and only consumes the
public functions exposed here. Run the full pipeline with::

    python -m pipeline.run_pipeline --source synthetic
"""

__all__ = ["config"]
__version__ = "1.0.0"
