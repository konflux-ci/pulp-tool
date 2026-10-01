"""Resolve Konflux ``ociStorage`` for ORAS publish (``--oci-storage`` flag only)."""

from __future__ import annotations


def resolve_oci_storage(cli_oci_storage: str | None, config_path: str | None) -> str | None:
    """
    Return the OCI registry target for trusted-artifact / ORAS publish.

    Tekton pipelines pass ``$(params.ociStorage)`` as ``--oci-storage`` (see
    ``build-rpm-package`` in rpmbuild-pipeline).
    """
    del config_path  # config file does not supply oci storage
    flag = (cli_oci_storage or "").strip()
    return flag or None


__all__ = ["resolve_oci_storage"]
