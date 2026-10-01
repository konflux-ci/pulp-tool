"""Public upload-collect API (non-``_`` symbols for cross-module use)."""

from .upload_collect import collect_results

__all__ = ["collect_results"]
