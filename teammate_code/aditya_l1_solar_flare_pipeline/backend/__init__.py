"""
Aditya-L1 Flare Operations — Web Backend
========================================
FastAPI web layer. It is a thin adapter over the scientific ``pipeline``
package: it triggers runs, serves generated catalogues/metrics as JSON, and
streams a live replay of the processed light curve over a WebSocket.

It contains NO science. All detection/forecasting logic lives in ``pipeline``.
"""

__all__ = ["app"]
