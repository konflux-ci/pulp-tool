"""Tests for upload pipeline DTO models."""

import pytest

from pulp_tool.models.context import UploadContext, UploadRpmContext
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.upload_distribution import DistributionUrlMap
from pulp_tool.models.upload_labels import UploadLabels


class TestUploadLabels:
    def test_to_pulp_dict_includes_standard_fields(self) -> None:
        labels = UploadLabels.from_upload_context(
            build_id="b1",
            arch="x86_64",
            namespace="ns",
            parent_package="parent",
            date="2024-01-01",
        )
        pulp = labels.to_pulp_dict()
        assert pulp["build_id"] == "b1"
        assert pulp["arch"] == "x86_64"
        assert pulp["namespace"] == "ns"
        assert pulp["parent_package"] == "parent"

    def test_signed_by_normalized_on_to_pulp_dict(self) -> None:
        labels = UploadLabels.from_upload_context(
            build_id="b1",
            arch="x86_64",
            namespace="ns",
            parent_package=None,
            date="d",
            signed_by="key-id",
        )
        assert labels.to_pulp_dict()["signed_by"] == "key-id"


class TestDistributionUrlMap:
    def test_to_dict_round_trip(self) -> None:
        m = DistributionUrlMap.from_dict({"rpms": "https://example/rpms", "logs": "https://example/logs"})
        assert m.to_dict()["rpms"] == "https://example/rpms"
        assert m.get("logs") == "https://example/logs"

    def test_getitem_items_keys(self) -> None:
        m = DistributionUrlMap.from_dict({"rpms": "https://example/rpms", "logs": "https://example/logs"})
        assert m["rpms"] == "https://example/rpms"
        assert list(m.keys()) == ["rpms", "logs"]
        assert list(m.items()) == [("rpms", "https://example/rpms"), ("logs", "https://example/logs")]


class TestRepositoryRefsUploadHelpers:
    def test_rpm_href_for_upload_unsigned(self) -> None:
        refs = RepositoryRefs(
            rpms_href="/bulk-rpm",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        ctx = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
        )
        assert refs.rpm_href_for_upload(ctx) == "/bulk-rpm"

    def test_rpm_href_for_upload_signed(self) -> None:
        refs = RepositoryRefs(
            rpms_href="/rpms",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
            rpms_signed_href="/signed-rpm",
        )
        ctx = UploadRpmContext(
            build_id="test-build",
            date_str="2024-01-01",
            namespace="test-ns",
            parent_package="test-pkg",
            rpm_path="/test/rpms",
            signed_by="key-1",
        )
        assert refs.rpm_href_for_upload(ctx) == "/signed-rpm"

    def test_rpm_href_for_upload_wrong_context_type(self) -> None:
        refs = RepositoryRefs(
            rpms_href="/rpms",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with pytest.raises(TypeError, match="UploadRpmContext"):
            refs.rpm_href_for_upload(UploadContext(build_id="b", date_str="d", namespace="n", parent_package="p"))

    def test_require_logs_prn_for_upload(self) -> None:
        refs = RepositoryRefs(
            rpms_href="/rpms",
            rpms_prn="",
            logs_href="",
            logs_prn="logs-prn",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        assert refs.require_logs_prn_for_upload() == "logs-prn"

    def test_require_logs_prn_raises_when_empty(self) -> None:
        refs = RepositoryRefs(
            rpms_href="/rpms",
            rpms_prn="",
            logs_href="",
            logs_prn="",
            sbom_href="",
            sbom_prn="",
            artifacts_href="",
            artifacts_prn="",
        )
        with pytest.raises(ValueError, match="logs repository PRN"):
            refs.require_logs_prn_for_upload()
