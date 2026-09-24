"""Resolve Konflux ``ociStorage`` for ORAS publish (CLI flag vs config)."""

from __future__ import annotations

import logging

from .config_manager import ConfigManager


def resolve_oci_storage(cli_oci_storage: str | None, config_path: str | None) -> str | None:
    """
    Return the OCI registry target for trusted-artifact / ORAS publish.

    Tekton pipelines pass ``$(params.ociStorage)`` as ``--oci-storage`` (see
    ``build-rpm-package`` in rpmbuild-pipeline). When the flag is omitted, fall back to
    ``cli.oci_storage`` in the config file (image-controller / legacy setups).
    """
    flag = (cli_oci_storage or "").strip()
    if flag:
        return flag
    path = (config_path or "").strip()
    if not path:
        return None
    try:
        cfg = ConfigManager(path)
        cfg.load()
        raw = cfg.get("cli.oci_storage")
        return str(raw).strip() if raw else None
    except Exception as e:
        logging.debug("Could not load cli.oci_storage from %s: %s", path, e)
        return None


__all__ = ["resolve_oci_storage"]
