"""Artifact-related models for Konflux Pulp."""

from __future__ import annotations

from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import KonfluxBaseModel
from .href_history import HrefHistoryEntry


class PulpContentRow(BaseModel):
    """One content unit from Pulp's content API (RPM package, file unit, etc.); fields vary by type."""

    model_config = ConfigDict(extra="allow")

    pulp_href: str = ""
    pulp_labels: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    relative_path: str | None = None


class ExtraArtifactRef(BaseModel):
    """Content href from upload `created_resources` used when gather-by-build_id returns empty."""

    model_config = ConfigDict(extra="ignore")

    pulp_href: str | None = None


class DownloadTask(KonfluxBaseModel):
    """
    Information needed to download a single artifact.

    Attributes:
        artifact_name: Name of the artifact file
        file_url: URL to download the artifact from
        arch: Architecture of the artifact (e.g., x86_64, noarch)
        artifact_type: Type of artifact (rpm, sbom, or log)
    """

    artifact_name: str
    file_url: AnyHttpUrl
    arch: str
    artifact_type: str
    expected_sha256: str | None = None

    def to_tuple(self) -> tuple[str, str, str, str, str | None]:
        """Convert to tuple for :meth:`~pulp_tool.api.DistributionClient.pull_data_async`."""
        return (
            self.artifact_name,
            str(self.file_url),
            self.arch,
            self.artifact_type,
            self.expected_sha256,
        )


class ArtifactFile(KonfluxBaseModel):
    """
    Represents a single downloaded artifact file.

    Attributes:
        file: Path to the downloaded file
        labels: Metadata labels associated with the artifact
    """

    file: str
    labels: dict[str, str] = Field(default_factory=dict)

    @property
    def file_name(self) -> str:
        """Extract just the filename from the path."""
        import os  # pylint: disable=import-outside-toplevel

        return os.path.basename(self.file)

    @property
    def file_dir(self) -> str:
        """Extract the directory from the path."""
        import os  # pylint: disable=import-outside-toplevel

        return os.path.dirname(self.file)

    @property
    def build_id(self) -> str | None:
        """Get build_id from labels if available."""
        return self.labels.get("build_id")  # pylint: disable=no-member

    @property
    def arch(self) -> str | None:
        """Get architecture from labels if available."""
        return self.labels.get("arch")  # pylint: disable=no-member

    @property
    def namespace(self) -> str | None:
        """Get namespace from labels if available."""
        return self.labels.get("namespace")  # pylint: disable=no-member

    @property
    def parent_package(self) -> str | None:
        """Get parent_package from labels if available."""
        return self.labels.get("parent_package")  # pylint: disable=no-member


class PulledArtifacts(KonfluxBaseModel):
    """
    Collection of downloaded artifacts organized by type.

    Attributes:
        sboms: Dictionary of SBOM artifacts (name -> ArtifactFile)
        logs: Dictionary of log artifacts (name -> ArtifactFile)
        rpms: Dictionary of RPM artifacts (name -> ArtifactFile)
    """

    sboms: dict[str, ArtifactFile] = Field(default_factory=dict)
    logs: dict[str, ArtifactFile] = Field(default_factory=dict)
    rpms: dict[str, ArtifactFile] = Field(default_factory=dict)

    @property
    def total_count(self) -> int:
        """Total number of artifacts across all types."""
        return len(self.sboms) + len(self.logs) + len(self.rpms)

    def add_sbom(self, name: str, file: str, labels: dict[str, str]) -> None:
        """Add a SBOM artifact."""
        self.sboms[name] = ArtifactFile(file=file, labels=labels)  # pylint: disable=unsupported-assignment-operation

    def add_log(self, name: str, file: str, labels: dict[str, str]) -> None:
        """Add a log artifact."""
        self.logs[name] = ArtifactFile(file=file, labels=labels)  # pylint: disable=unsupported-assignment-operation

    def add_rpm(self, name: str, file: str, labels: dict[str, str]) -> None:
        """Add an RPM artifact."""
        self.rpms[name] = ArtifactFile(file=file, labels=labels)  # pylint: disable=unsupported-assignment-operation

    def get_all_build_ids(self) -> set:
        """Get all unique build IDs from all artifacts."""
        build_ids = set()
        for artifacts in [self.sboms, self.logs, self.rpms]:
            for artifact in artifacts.values():  # pylint: disable=no-member
                if artifact.build_id:
                    build_ids.add(artifact.build_id)
        return build_ids

    def get_all_architectures(self) -> set:
        """Get all unique architectures from all artifacts."""
        architectures = set()
        for artifacts in [self.sboms, self.logs, self.rpms]:
            for artifact in artifacts.values():  # pylint: disable=no-member
                if artifact.arch:
                    architectures.add(artifact.arch)
        return architectures

    def get_all_namespaces(self) -> set:
        """Get all unique namespaces from all artifacts."""
        namespaces = set()
        for artifacts in [self.sboms, self.logs, self.rpms]:
            for artifact in artifacts.values():  # pylint: disable=no-member
                if artifact.namespace:
                    namespaces.add(artifact.namespace)
        return namespaces


class OciManifestField(KonfluxBaseModel):
    """OCI manifest pointer on ``pulp_results.json`` (canonical object form)."""

    model_config = ConfigDict(extra="ignore")

    ref: str
    digest: str = ""


class ArtifactMetadata(KonfluxBaseModel):
    """
    Metadata for one artifact: the same shape in ``pulp_results.json`` for upload (push) and pull.

    Rows in :class:`~pulp_tool.models.pulp_results.PulpResultsDocument` use this type. For ``pulp pull``,
    load into :class:`~pulp_tool.models.pulp_results.PulpResultsDocument` and call :meth:`validate_for_pull`.
    Unknown keys on each artifact object are ignored when parsing JSON.

    Serialized JSON uses ``pulp_labels`` only.

    ``url`` / ``sha256`` may be omitted for in-memory partial records (e.g. tests); pull requires a
    non-empty ``http``/``https`` ``url`` on every artifact.
    """

    model_config = ConfigDict(
        extra="ignore",
        validate_assignment=True,
        frozen=False,
        populate_by_name=True,
    )

    pulp_labels: dict[str, str] = Field(default_factory=dict)

    url: str | None = None
    sha256: str | None = None
    href: str | None = None
    href_history: list[HrefHistoryEntry] = Field(default_factory=list)
    distributions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _coerce_href_history(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            raw = d.get("href_history")
            if isinstance(raw, list):
                from .pulp_results.normalize import normalize_href_history_rows

                d["href_history"] = normalize_href_history_rows(raw)
            return d
        return data

    @field_validator("url")
    @classmethod
    def _normalize_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None

    @field_validator("sha256", mode="before")
    @classmethod
    def _normalize_sha256(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        s = str(v).strip()
        return s if s else None

    @property
    def build_id(self) -> str | None:
        """Get build ID from pulp_labels."""
        return self.pulp_labels.get("build_id")

    @property
    def arch(self) -> str | None:
        """Get architecture from pulp_labels."""
        return self.pulp_labels.get("arch")

    @property
    def namespace(self) -> str | None:
        """Get namespace from pulp_labels."""
        return self.pulp_labels.get("namespace")

    @property
    def parent_package(self) -> str | None:
        """Get parent package from pulp_labels."""
        return self.pulp_labels.get("parent_package")


def _default_artifact_json_document() -> PulpResultsDocument:
    from .pulp_results import PulpResultsDocument

    return PulpResultsDocument()


class ArtifactData(KonfluxBaseModel):
    """
    Loaded and validated artifact metadata.

    Attributes:
        artifact_json: Full JSON metadata from artifact location
        artifacts: Dictionary of individual artifacts with their metadata
    """

    artifact_json: PulpResultsDocument = Field(default_factory=_default_artifact_json_document)
    artifacts: dict[str, ArtifactMetadata] = Field(default_factory=dict)

    @property
    def artifact_count(self) -> int:
        """Total number of artifacts."""
        return len(self.artifacts)

    @property
    def has_distributions(self) -> bool:
        """Check if distributions are present in metadata."""
        return self.artifact_json.has_distributions  # pylint: disable=no-member

    def get_distributions(self) -> dict[str, str]:
        """Get distribution URLs (empty dict when omitted)."""
        d = self.artifact_json.distributions
        if not d:
            return {}
        return {k: str(v) for k, v in d.items()}


class ContentData(KonfluxBaseModel):
    """
    Content data and artifacts gathered from Pulp.

    Attributes:
        content_results: List of content data from Pulp
        artifacts: List of artifact information dictionaries
    """

    content_results: list[PulpContentRow] = Field(default_factory=list)
    artifacts: list[dict[str, str]] = Field(default_factory=list)

    @property
    def artifact_count(self) -> int:
        """Total number of artifacts."""
        return len(self.artifacts)


class FileInfoModel(KonfluxBaseModel):
    """
    File location information from Pulp artifacts API.

    This model represents the file information returned by the Pulp API
    when querying artifact details.

    Attributes:
        pulp_href: Pulp API href for the artifact
        file: Download URL for the artifact file
        sha256: SHA256 checksum of the file
        size: File size in bytes
    """

    pulp_href: str
    file: str  # URL
    sha256: str | None = None
    size: int | None = None


FileInfoMap = dict[str, FileInfoModel]

from .pulp_results import PulpResultsDocument  # noqa: E402

__all__ = [
    "DownloadTask",
    "ArtifactFile",
    "PulledArtifacts",
    "ArtifactMetadata",
    "ArtifactData",
    "ContentData",
    "ExtraArtifactRef",
    "FileInfoMap",
    "FileInfoModel",
    "PulpContentRow",
]
