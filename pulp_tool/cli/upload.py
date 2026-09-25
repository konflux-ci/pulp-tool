"""
Deprecated ``upload`` CLI alias for ``upload-build``.

Tekton tasks still invoke ``upload`` until downstream pipelines switch to ``upload-build``.
"""

from __future__ import annotations

import click

from .upload_build import upload_build

upload = click.Command(
    "upload",
    params=upload_build.params,
    callback=upload_build.callback,
    help=(upload_build.help or "") + " Prefer ``upload-build``; ``upload`` remains for compatibility.",
)

__all__ = ["upload", "upload_build"]
