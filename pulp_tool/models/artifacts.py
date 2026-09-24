"""Artifact-related models for Konflux Pulp."""

from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import KonfluxBaseModel


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
    file: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_dict_href_keys(cls, data: Any) -> Any:
        """Support legacy {"pulp_href"} and odd test shapes {"file": href} / {"extra": href}."""
        if isinstance(data, dict):
            d = dict(data)
            if not (d.get("pulp_href") or "").strip():
                for k in ("file", "extra"):
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        d["pulp_href"] = v.strip()
                        break
            return d
        return data


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

    def to_tuple(self) -> tuple:
        """Convert to tuple format (artifact_name, file_url, arch, artifact_type)."""
        return (self.artifact_name, str(self.file_url), self.arch, self.artifact_type)


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


class ArtifactMetadata(KonfluxBaseModel):
    """
    Metadata for one artifact: the same shape in ``pulp_results.json`` for upload (push) and pull.

    Rows in :class:`~pulp_tool.models.results.PulpResultsModel` use this type. For ``pulp pull``,
    load into :class:`ArtifactJsonResponse` and call :meth:`ArtifactJsonResponse.validate_for_pull`.
    Unknown keys on each artifact object are ignored when parsing JSON.

    ``url`` / ``sha256`` may be omitted for in-memory partial records (e.g. tests); pull requires a
    non-empty ``http``/``https`` ``url`` on every artifact.
    """

    model_config = ConfigDict(extra="ignore", validate_assignment=True, frozen=False)

    labels: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    sha256: str | None = None
    href: str | None = None
    href_history: list[dict[str, Any]] = Field(default_factory=list)
    distributions: dict[str, str] = Field(default_factory=dict)

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
        """Get build ID from labels."""
        return self.labels.get("build_id")  # pylint: disable=no-member

    @property
    def arch(self) -> str | None:
        """Get architecture from labels."""
        return self.labels.get("arch")  # pylint: disable=no-member

    @property
    def namespace(self) -> str | None:
        """Get namespace from labels."""
        return self.labels.get("namespace")  # pylint: disable=no-member

    @property
    def parent_package(self) -> str | None:
        """Get parent package from labels."""
        return self.labels.get("parent_package")  # pylint: disable=no-member


class ArtifactJsonResponse(KonfluxBaseModel):
    """
    Full artifact JSON response structure.

    Attributes:
        artifacts: Dictionary of artifact names to their metadata
        distributions: Optional map of distribution slot to base URL (may be omitted in JSON)
    """

    artifacts: dict[str, ArtifactMetadata] = Field(default_factory=dict)
    distributions: dict[str, AnyHttpUrl] | None = None
    version: int | None = None
    oci_manifest: str | None = None
    oci_manifest_history: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def artifact_count(self) -> int:
        """Total number of artifacts."""
        return len(self.artifacts)

    @property
    def has_distributions(self) -> bool:
        """Check if distributions are present."""
        return bool(self.distributions)

    @property
    def rpms_distribution_url(self) -> str | None:
        """Get RPMs distribution URL."""
        v = (self.distributions or {}).get("rpms")
        return str(v) if v is not None else None

    @property
    def logs_distribution_url(self) -> str | None:
        """Get logs distribution URL."""
        v = (self.distributions or {}).get("logs")
        return str(v) if v is not None else None

    @property
    def sbom_distribution_url(self) -> str | None:
        """Get SBOM distribution URL."""
        v = (self.distributions or {}).get("sbom")
        return str(v) if v is not None else None

    def get_artifact(self, name: str) -> ArtifactMetadata | None:
        """Get artifact metadata by name."""
        return self.artifacts.get(name)  # pylint: disable=no-member

    def validate_for_pull(self) -> None:
        """Require non-empty ``artifacts`` and an ``http``/``https`` ``url`` on every row (``pulp pull``)."""
        if not self.artifacts:
            raise ValueError("artifacts must contain at least one entry")
        for name, meta in self.artifacts.items():
            if not meta.url:
                raise ValueError(
                    f"artifact {name!r} must include a non-empty http(s) url for pull",
                )
            lower = meta.url.lower()
            if not (lower.startswith("http://") or lower.startswith("https://")):
                raise ValueError(
                    f"artifact {name!r} url must be an http or https URL for pull",
                )


class ArtifactData(KonfluxBaseModel):
    """
    Loaded and validated artifact metadata.

    Attributes:
        artifact_json: Full JSON metadata from artifact location
        artifacts: Dictionary of individual artifacts with their metadata
    """

    artifact_json: ArtifactJsonResponse = Field(default_factory=ArtifactJsonResponse)
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


__all__ = [
    "DownloadTask",
    "ArtifactFile",
    "PulledArtifacts",
    "ArtifactMetadata",
    "ArtifactJsonResponse",
    "ArtifactData",
    "ContentData",
    "ExtraArtifactRef",
    "FileInfoMap",
    "FileInfoModel",
    "PulpContentRow",
]
