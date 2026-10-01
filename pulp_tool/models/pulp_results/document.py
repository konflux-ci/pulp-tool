"""``PulpResultsDocument`` — canonical in-memory ``pulp_results.json``."""

from __future__ import annotations

import json
from datetime import date
from threading import Lock
from typing import Any, Self

from pydantic import AnyHttpUrl, ConfigDict, Field, PrivateAttr, TypeAdapter, model_validator

from ..artifacts import ArtifactMetadata
from ..base import KonfluxBaseModel
from ..repository import RepositoryRefs
from ..statistics import UploadCounts
from .constants import (
    BUILD_UPLOAD_OPERATION,
    PULP_RESULTS_SCHEMA_VERSION,
    SIDE_TAG_TRANSFER_OPERATION,
)
from .distributions import (
    aggregate_top_level_distributions,
    aggregate_top_level_from_artifacts,
    recompute_distributions,
    retain_distribution_slots,
)
from .entries import SideTagRpmTransfer
from .lineage import (
    append_href_history,
    merge_origin_pulp_labels,
    merge_signed_by,
    resolve_predecessor_href,
)
from .normalize import (
    coerce_schema_version,
    document_last_updated_iso,
    normalize_document,
    optional_str_field,
)


class PulpResultsDocument(KonfluxBaseModel):
    """
    Unified ``pulp_results.json`` document and upload session state.

    Canonical JSON fields serialize via :meth:`to_canonical_dict`. Session-only fields
    (``repositories``, ``uploaded_counts``, ``upload_errors``) are excluded from export.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: str = PULP_RESULTS_SCHEMA_VERSION
    last_updated: str = Field(default_factory=lambda: date.today().isoformat())
    build_id: str = ""
    namespace: str | None = None
    cluster: str | None = None
    artifacts: dict[str, ArtifactMetadata] = Field(default_factory=dict)
    distributions: dict[str, str] = Field(default_factory=dict)
    repositories: RepositoryRefs | None = None
    uploaded_counts: UploadCounts = Field(default_factory=UploadCounts)
    upload_errors: list[str] = Field(default_factory=list)

    _lock: Lock = PrivateAttr(default_factory=Lock)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_document_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            d["version"] = coerce_schema_version(d.get("version"))
            dist = d.get("distributions")
            if isinstance(dist, dict):
                d["distributions"] = {str(k): str(v) for k, v in dist.items() if v is not None}
            return d
        return data

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, repositories: RepositoryRefs | None = None) -> Self:
        normalized = normalize_document(raw)
        artifacts: dict[str, ArtifactMetadata] = {}
        raw_arts = normalized.get("artifacts")
        if isinstance(raw_arts, dict):
            for key, row in raw_arts.items():
                if isinstance(row, dict):
                    artifacts[key] = ArtifactMetadata.model_validate(row)
        dist_raw = normalized.get("distributions")
        distributions = {str(k): str(v) for k, v in dist_raw.items() if v} if isinstance(dist_raw, dict) else {}
        return cls(
            version=coerce_schema_version(normalized.get("version")),
            last_updated=document_last_updated_iso(normalized),
            build_id=str(normalized.get("build_id") or "").strip(),
            namespace=optional_str_field(normalized.get("namespace")),
            cluster=optional_str_field(normalized.get("cluster")),
            artifacts=artifacts,
            distributions=distributions,
            repositories=repositories,
        )

    @classmethod
    def from_artifact_json(cls, artifact_json: Any, *, repositories: RepositoryRefs | None = None) -> Self:
        if hasattr(artifact_json, "model_dump"):
            raw = artifact_json.model_dump(mode="json", exclude_none=True)
            return cls.from_raw(raw, repositories=repositories)
        if isinstance(artifact_json, dict):
            return cls.from_raw(artifact_json, repositories=repositories)
        raise TypeError(f"Unsupported artifact_json type: {type(artifact_json)}")

    @classmethod
    def empty_shell(
        cls,
        *,
        build_id: str,
        namespace: str,
        cluster: str | None = None,
        repositories: RepositoryRefs | None = None,
    ) -> Self:
        raw: dict[str, Any] = {
            "version": PULP_RESULTS_SCHEMA_VERSION,
            "last_updated": date.today().isoformat(),
            "build_id": build_id,
            "namespace": namespace,
            "artifacts": {},
        }
        if cluster and cluster.strip():
            raw["cluster"] = cluster.strip()
        return cls.from_raw(raw, repositories=repositories)

    def normalize_in_place(self) -> None:
        refreshed = self.from_raw(
            {
                "version": self.version,
                "last_updated": self.last_updated,
                "build_id": self.build_id,
                "namespace": self.namespace,
                "cluster": self.cluster,
                "artifacts": {k: v.model_dump(mode="json", by_alias=True) for k, v in self.artifacts.items()},
                "distributions": dict(self.distributions),
            },
            repositories=self.repositories,
        )
        self.version = refreshed.version
        self.last_updated = refreshed.last_updated
        self.build_id = refreshed.build_id
        self.namespace = refreshed.namespace
        self.cluster = refreshed.cluster
        self.artifacts = refreshed.artifacts
        self.distributions = refreshed.distributions

    def prepare_for_mutation(self, *, operation: str) -> str:
        """Record prior hrefs in history; touch ``last_updated``. Returns prior ``last_updated``."""
        self.normalize_in_place()
        old_last_updated = self.last_updated
        schema_ver = self.version
        for meta in self.artifacts.values():
            prior_href = resolve_predecessor_href(meta)
            prior_sha256 = (meta.sha256 or "").strip()
            append_href_history(
                meta,
                prior_href=prior_href,
                prior_sha256=prior_sha256,
                last_updated=old_last_updated,
                schema_version_value=schema_ver,
                operation=operation,
            )
        self.touch_last_updated()
        return old_last_updated

    def touch_last_updated(self, *, when: date | None = None) -> str:
        value = (when or date.today()).isoformat()
        self.last_updated = value
        return value

    def apply_side_tag_transfer(
        self,
        transfers: list[SideTagRpmTransfer],
        *,
        side_tag: str,
        top_level_side_tag_distribution_url: str,
    ) -> PulpResultsDocument:
        result = PulpResultsDocument.from_raw(
            self.to_canonical_dict(),
            repositories=self.repositories,
        )
        result.normalize_in_place()
        old_last_updated = result.last_updated
        schema_ver = result.version
        result.touch_last_updated()

        top_distributions = dict(result.distributions)
        if top_level_side_tag_distribution_url:
            top_distributions[side_tag] = top_level_side_tag_distribution_url.rstrip("/") + "/"
        result.distributions = top_distributions

        for transfer in transfers:
            key = transfer.artifact_key
            existing = result.artifacts.get(key)
            if existing is None:
                existing = ArtifactMetadata()
                result.artifacts[key] = existing
            prior_href = resolve_predecessor_href(existing)
            prior_sha256 = (existing.sha256 or "").strip()
            append_href_history(
                existing,
                prior_href=prior_href,
                prior_sha256=prior_sha256,
                last_updated=old_last_updated,
                schema_version_value=schema_ver,
                operation=SIDE_TAG_TRANSFER_OPERATION,
            )
            existing.href = transfer.pulp_href
            existing.sha256 = transfer.sha256
            existing.url = transfer.distribution_url
            per_dist = dict(existing.distributions)
            per_dist[side_tag] = transfer.distribution_url
            per_dist = retain_distribution_slots(existing, prior_href, per_dist)
            existing.distributions = per_dist

        result.repositories = self.repositories
        return result

    def merge_upload_outcomes(
        self,
        upload: PulpResultsDocument,
        *,
        operation: str,
        signed_by: str | None,
        replace_signed_by: bool,
        verified_distribution_slots: set[str],
    ) -> None:
        self.normalize_in_place()
        old_last_updated = self.last_updated
        schema_ver = self.version

        for key, info in upload.artifacts.items():
            existing = self.artifacts.get(key)
            if existing is None:
                existing = ArtifactMetadata()
                self.artifacts[key] = existing
            prior_href = resolve_predecessor_href(existing)
            prior_sha256 = (existing.sha256 or "").strip()
            new_href = (info.href or "").strip()
            if new_href and new_href != prior_href:
                append_href_history(
                    existing,
                    prior_href=prior_href or (existing.href or "").strip(),
                    prior_sha256=prior_sha256,
                    last_updated=old_last_updated,
                    schema_version_value=schema_ver,
                    operation=operation,
                )
            if info.url:
                existing.url = info.url
            if info.sha256:
                existing.sha256 = info.sha256
            if new_href:
                existing.href = new_href
            labels = dict(existing.pulp_labels)
            labels.update({k: v for k, v in info.pulp_labels.items() if k != "signed_by"})
            new_signed = (info.pulp_labels.get("signed_by") or "").strip()
            if new_signed:
                labels["signed_by"] = merge_signed_by(
                    labels.get("signed_by", ""),
                    new_signed,
                    replace=replace_signed_by,
                )
            elif signed_by:
                labels["signed_by"] = merge_signed_by(
                    labels.get("signed_by", ""),
                    signed_by,
                    replace=replace_signed_by,
                )
            existing.pulp_labels = labels
            slot_updates = {str(k): str(v) for k, v in (info.distributions or {}).items() if v}
            if slot_updates or existing.distributions:
                existing.distributions = recompute_distributions(
                    existing,
                    verified_distribution_slots,
                    slot_updates=slot_updates,
                )

        self.distributions = aggregate_top_level_from_artifacts(self.artifacts, self.distributions)

    def to_canonical_dict(
        self,
        *,
        namespace: str | None = None,
        cluster: str | None = None,
    ) -> dict[str, Any]:
        ns = namespace if namespace is not None else self.namespace
        cl = cluster if cluster is not None else self.cluster
        artifacts_out: dict[str, Any] = {}
        for key, info in self.artifacts.items():
            labels = merge_origin_pulp_labels(
                dict(info.pulp_labels),
                namespace=ns,
                build_id=self.build_id or None,
                cluster=cl,
            )
            row: dict[str, Any] = {
                "pulp_labels": labels,
                "url": info.url,
                "sha256": info.sha256 or "",
                "href_history": [e.model_dump() for e in info.href_history],
            }
            if info.href:
                row["href"] = info.href
            if info.distributions:
                row["distributions"] = dict(info.distributions)
            artifacts_out[key] = row
        dist_map = dict(self.distributions)
        if not dist_map and artifacts_out:
            dist_map = aggregate_top_level_distributions({"artifacts": artifacts_out})
        out: dict[str, Any] = {
            "version": self.version or PULP_RESULTS_SCHEMA_VERSION,
            "last_updated": self.last_updated or date.today().isoformat(),
            "build_id": self.build_id,
            "artifacts": artifacts_out,
            "distributions": dict(sorted(dist_map.items())),
        }
        if ns:
            out["namespace"] = ns
        if cl and str(cl).strip():
            out["cluster"] = str(cl).strip()
        out["distributions"] = dict(sorted(dist_map.items()))
        return out

    def to_canonical_json(
        self,
        *,
        namespace: str | None = None,
        cluster: str | None = None,
    ) -> str:
        return json.dumps(self.to_canonical_dict(namespace=namespace, cluster=cluster), indent=2)

    def _mutable_dict(self) -> dict[str, Any]:
        """Internal dict snapshot (canonical artifact shape). Prefer :meth:`to_canonical_dict`."""
        return self.to_canonical_dict()

    def validate_for_pull(self) -> None:
        if not self.artifacts:
            raise ValueError("artifacts must contain at least one entry")
        for name, meta in self.artifacts.items():
            if not meta.url:
                raise ValueError(f"artifact {name!r} must include a non-empty http(s) url for pull")
            lower = meta.url.lower()
            if not (lower.startswith("http://") or lower.startswith("https://")):
                raise ValueError(f"artifact {name!r} url must be an http or https URL for pull")
            if not meta.sha256:
                raise ValueError(f"artifact {name!r} must include sha256 for pull")
            from ...utils.checksum_verify import validate_sha256_hex

            validate_sha256_hex(meta.sha256, field_name=f"artifact {name!r} sha256")

    def add_artifact(self, key: str, url: str, sha256: str, pulp_labels: dict[str, str]) -> None:
        with self._lock:
            self.artifacts[key] = ArtifactMetadata(pulp_labels=pulp_labels, url=url, sha256=sha256)

    def add_distribution(self, repo_type: str, url: str) -> None:
        with self._lock:
            coerced = TypeAdapter(AnyHttpUrl).validate_python(url)
            self.distributions = {**self.distributions, repo_type: str(coerced)}

    def increment_counts(self, *, rpms: int = 0, logs: int = 0, sboms: int = 0, files: int = 0) -> None:
        with self._lock:
            if rpms:
                self.uploaded_counts.rpms += rpms
            if logs:
                self.uploaded_counts.logs += logs
            if sboms:
                self.uploaded_counts.sboms += sboms
            if files:
                self.uploaded_counts.files += files

    def add_error(self, error: str) -> None:
        with self._lock:
            self.upload_errors.append(error)

    @property
    def total_uploaded(self) -> int:
        return self.uploaded_counts.total

    @property
    def has_errors(self) -> bool:
        return len(self.upload_errors) > 0

    @property
    def error_count(self) -> int:
        return len(self.upload_errors)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def has_distributions(self) -> bool:
        return bool(self.distributions)

    def get_artifact(self, name: str) -> ArtifactMetadata | None:
        return self.artifacts.get(name)

    @property
    def rpms_distribution_url(self) -> str | None:
        return self.distributions.get("rpms")

    @property
    def logs_distribution_url(self) -> str | None:
        return self.distributions.get("logs")

    @property
    def sbom_distribution_url(self) -> str | None:
        return self.distributions.get("sbom")


__all__ = ["PulpResultsDocument", "BUILD_UPLOAD_OPERATION"]
