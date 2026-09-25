"""OCI image reference helpers for Konflux ``ociStorage`` (bare repo vs oras CLI)."""

from __future__ import annotations


def oci_storage_repository_name(oci_storage: str) -> str:
    """
    Repository reference without tag or digest.

    Matches Konflux ``create-oci.sh`` / ``select-oci-auth`` (tag and digest stripped for auth and
    ``PULP-IMAGE_URL``).
    """
    ref = oci_storage.strip()
    if not ref:
        return ref
    if "@" in ref:
        ref = ref.split("@", 1)[0]
    slash = ref.find("/")
    if slash == -1:
        return ref
    head, tail = ref[:slash], ref[slash:]
    if ":" in tail:
        tail = tail.rsplit(":", 1)[0]
    return head + tail


def _oci_storage_has_tag_or_digest(oci_storage: str) -> bool:
    ref = oci_storage.strip()
    if not ref or "@" in ref:
        return bool(ref and "@" in ref)
    slash = ref.find("/")
    if slash == -1:
        return False
    return ":" in ref[slash:]


def oci_storage_oras_target(oci_storage: str) -> str:
    """
    Reference for ``oras push`` / ``oras resolve``.

    Konflux ``ociStorage`` is often a bare repository; oras requires ``:<tag>`` or ``@<digest>``.
    Bare repos use ``:latest`` (same as implicit tag for ``oras push`` in trusted-artifacts).
    """
    ref = oci_storage.strip()
    if not ref:
        return ref
    if _oci_storage_has_tag_or_digest(ref):
        return ref
    return f"{ref}:latest"


__all__ = ["oci_storage_oras_target", "oci_storage_repository_name"]
