# Pinned by scripts/sync-container-build-args.sh from .release-please-manifest.json
# Local editable installs may regenerate via setuptools-scm (see pyproject.toml).
from __future__ import annotations

__all__ = [
    "__version__",
    "__version_tuple__",
    "version",
    "version_tuple",
    "__commit_id__",
    "commit_id",
]

version: str
__version__: str
__version_tuple__: tuple[int | str, ...]
version_tuple: tuple[int | str, ...]
commit_id: str | None
__commit_id__: str | None

__version__ = version = '1.3.1'
__version_tuple__ = version_tuple = (1, 3, 1)

__commit_id__ = commit_id = None
