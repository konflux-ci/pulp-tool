"""Pulp Tool CLI models for JSON and input validation"""

import os
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator, model_validator

from .base import KonfluxBaseModel
from .pulp_label_values import normalize_signed_by_value_for_pulp

if TYPE_CHECKING:
    from .pulp_api import RpmPackageResponse

# SHA256 checksum length (64 hex chars)
SHA256_HEX_LENGTH = 64


class RepositoryOptions(KonfluxBaseModel):
    compression_type: Literal["zstd", "gz"] | None = None
    checksum_type: Literal["unknown", "md5", "sha1", "sha224", "sha256", "sha384", "sha512"] | None = None
    autopublish: bool = True


class DistributionOptions(KonfluxBaseModel):
    name: str
    base_path: str
    generate_repo_config: bool | None = None


class Package(KonfluxBaseModel):
    pulp_href: str


class CreateRepository(KonfluxBaseModel):
    name: str
    packages: list[Package] = Field(min_length=1)
    repository_options: RepositoryOptions = RepositoryOptions()
    distribution_options: DistributionOptions
    custom_files: dict[str, str] = {}


# -----------------------------------------------------------------------------
# Search-by models
# -----------------------------------------------------------------------------


class SearchByRequest(KonfluxBaseModel):
    """Request params for search-by. Checksums XOR filenames; signed_by optional (max 1)."""

    checksums: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)
    signed_by: list[str] = Field(default_factory=list)

    @field_validator("checksums")
    @classmethod
    def validate_checksums(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        result = []
        for c in v:
            c_stripped = c.strip().lower()
            if len(c_stripped) != SHA256_HEX_LENGTH or not all(ch in "0123456789abcdef" for ch in c_stripped):
                raise ValueError(f"Invalid checksum (expected 64 hex chars): {c}")
            result.append(c_stripped)
        return result

    @field_validator("filenames")
    @classmethod
    def validate_filenames(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        return [s.strip() for s in v if s and s.strip()]

    @field_validator("signed_by")
    @classmethod
    def validate_signed_by(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        stripped = [s.strip() for s in v if s and s.strip()]
        if len(stripped) > 1:
            raise ValueError("signed_by accepts at most one value")
        return [normalize_signed_by_value_for_pulp(stripped[0])]

    @model_validator(mode="after")
    def checksums_xor_filenames(self) -> "SearchByRequest":
        if self.checksums and self.filenames:
            raise ValueError("checksums and filenames cannot be combined")
        return self

    @model_validator(mode="after")
    def at_least_one_required(self) -> "SearchByRequest":
        if not self.checksums and not self.filenames and not self.signed_by:
            raise ValueError("At least one of checksum, filenames, or signed_by must be provided")
        return self


class FoundPackages(KonfluxBaseModel):
    """Extracted identifiers from found RPM packages for removal from results.json."""

    checksums: set[str] = Field(default_factory=set)
    filenames: set[str] = Field(default_factory=set)
    filename_checksum_pairs: set[tuple[str, str]] = Field(default_factory=set)  # (basename, sha256)
    signed_by: set[str] = Field(default_factory=set)

    @classmethod
    def from_packages(cls, packages: list["RpmPackageResponse"]) -> "FoundPackages":
        """Build FoundPackages from RPM package responses."""
        from .pulp_api import RpmPackageResponse

        checksums: set[str] = set()
        filenames: set[str] = set()
        filename_checksum_pairs: set[tuple[str, str]] = set()
        signed_by: set[str] = set()
        for pkg in packages:
            if isinstance(pkg, RpmPackageResponse):
                checksums.add(pkg.pkgId.lower())
                if pkg.location_href:
                    basename = os.path.basename(pkg.location_href)
                    filenames.add(pkg.location_href)
                    filenames.add(basename)
                    filename_checksum_pairs.add((basename, pkg.pkgId.lower()))
                else:
                    nvra_rpm = f"{pkg.name}-{pkg.version}-{pkg.release}.{pkg.arch}.rpm"
                    filenames.add(nvra_rpm)
                sb = (pkg.pulp_labels.get("signed_by") or "").strip()
                if sb:
                    signed_by.add(sb)
        return cls(
            checksums=checksums,
            filenames=filenames,
            filename_checksum_pairs=filename_checksum_pairs,
            signed_by=signed_by,
        )


class SearchByResultsJson:
    """Wrapper for results.json structure with extraction and removal helpers."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._artifacts = data.get("artifacts", {})

    @staticmethod
    def _is_rpm(key: str) -> bool:
        return key.lower().endswith(".rpm")

    def extract_rpm_checksums(self) -> list[str]:
        """Extract SHA256 checksums from RPM artifacts."""
        seen: set[str] = set()
        result: list[str] = []
        for key, info in self._artifacts.items():
            if not self._is_rpm(key) or not isinstance(info, dict):
                continue
            sha256 = (info.get("sha256") or "").strip().lower()
            if sha256 and len(sha256) == SHA256_HEX_LENGTH and sha256 not in seen:
                result.append(sha256)
                seen.add(sha256)
        return result

    def extract_filenames(self) -> list[str]:
        """Extract filenames (artifact keys) from RPM artifacts."""
        seen: set[str] = set()
        result: list[str] = []
        for key, info in self._artifacts.items():
            if not self._is_rpm(key) or not isinstance(info, dict) or not key or key in seen:
                continue
            result.append(key)
            seen.add(key)
        return result

    def remove_found(self, found: FoundPackages, only_remove_filenames: set[str] | None = None) -> dict[str, Any]:
        """
        Return a copy with RPMs matching found identifiers removed.

        ONLY remove an artifact when its sha256 matches a package (pkgId) from the
        Pulp GET response. This prevents incorrectly removing artifacts with same
        filename but different content (different builds).

        When only_remove_filenames is provided (filename mode), additionally require
        (basename, sha256) to match a Pulp package via filename_checksum_pairs.
        """
        import json

        out = json.loads(json.dumps(self._data))
        artifacts = out.get("artifacts", {})
        to_remove = []
        for key, info in artifacts.items():
            if not self._is_rpm(key) or not isinstance(info, dict):
                continue
            key_basename = os.path.basename(key)
            artifact_sha = (info.get("sha256") or "").strip().lower()
            remove = False
            # Never remove without sha256 match
            if artifact_sha not in found.checksums:
                pass
            elif only_remove_filenames is not None:
                # Filename mode: require (basename, sha256) in filename_checksum_pairs
                if found.filename_checksum_pairs and (key_basename, artifact_sha) in found.filename_checksum_pairs:
                    if key_basename in only_remove_filenames:
                        remove = True
                elif found.filenames and (key in found.filenames or key_basename in found.filenames):
                    # Fallback when location_href missing: basename + sha256 match
                    if key_basename in only_remove_filenames:
                        remove = True
            else:
                # Checksum/signed_by mode: sha256 match is sufficient
                if found.signed_by:
                    labels = info.get("pulp_labels") or {}
                    if isinstance(labels, dict):
                        artifact_sb = (labels.get("signed_by") or "").strip()
                        if artifact_sb and (
                            artifact_sb in found.signed_by
                            or normalize_signed_by_value_for_pulp(artifact_sb) in found.signed_by
                        ):
                            remove = True
                else:
                    remove = True
            if remove and (only_remove_filenames is None or key_basename in only_remove_filenames):
                to_remove.append(key)
        for key in to_remove:
            del artifacts[key]
        return out

    def to_dict(self) -> dict[str, Any]:
        """Return the underlying data dict."""
        return self._data


__all__ = [
    "CreateRepository",
    "FoundPackages",
    "SearchByRequest",
    "SearchByResultsJson",
]
