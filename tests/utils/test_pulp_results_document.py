"""Tests for pulp_results.json document merge helpers."""

import pytest

import pulp_tool.utils.pulp_results_document as prd
from pulp_tool.models.artifacts import ArtifactJsonResponse
from pulp_tool.utils.pulp_results_document import (
    SideTagRpmTransfer,
    append_href_history,
    append_oci_manifest_history,
    apply_side_tag_transfer_to_document,
    bump_document_version,
    document_from_artifact_json,
    merge_origin_pulp_labels,
    resolve_predecessor_href,
    set_oci_manifest,
    side_tag_upload_labels,
)


class TestRetainDistributionSlots:
    def test_adds_artifact_slot_not_yet_in_merged(self) -> None:
        artifact = {"href": "/pulp/same/", "distributions": {"legacy": "https://example/legacy/"}}
        merged = prd._retain_distribution_slots(artifact, "/pulp/same/", {"st": "https://example/side/"})
        assert merged["legacy"] == "https://example/legacy/"
        assert merged["st"] == "https://example/side/"


class TestLineageHelpers:
    def test_resolve_predecessor_href_from_href_field(self) -> None:
        assert resolve_predecessor_href({"href": "/pulp/a/"}) == "/pulp/a/"

    def test_resolve_predecessor_href_from_labels(self) -> None:
        assert resolve_predecessor_href({"labels": {"source_pulp_href": "/pulp/b/"}}) == "/pulp/b/"

    def test_resolve_predecessor_href_invalid_labels(self) -> None:
        assert resolve_predecessor_href({"labels": "bad"}) == ""

    def test_resolve_predecessor_href_pulp_href_label(self) -> None:
        assert resolve_predecessor_href({"labels": {"pulp_href": "/pulp/c/"}}) == "/pulp/c/"

    def test_merge_origin_labels_do_not_overwrite(self) -> None:
        labels = {"origin_namespace": "keep"}
        merged = merge_origin_pulp_labels(labels, namespace="new", build_id="b1", cluster="c1")
        assert merged["origin_namespace"] == "keep"
        assert merged["origin_build_id"] == "b1"
        assert merged["origin_cluster"] == "c1"

    def test_side_tag_upload_labels(self) -> None:
        out = side_tag_upload_labels(
            {"build_id": "b"},
            side_tag="mytest",
            source_pulp_href="/src/",
            namespace="ns",
            build_id="b",
            cluster="cluster-a",
        )
        assert out["side_tag"] == "mytest"
        assert out["source_pulp_href"] == "/src/"
        assert out["origin_namespace"] == "ns"


class TestApplySideTagTransfer:
    def test_apply_side_tag_transfer_bumps_version_and_history(self) -> None:
        source = {
            "version": 2,
            "oci_manifest": "quay.io/org/app@sha256:old",
            "distributions": {"rpms": "https://example.com/rpms/"},
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/old/",
                    "sha256": "abc",
                    "url": "https://example.com/pkg.rpm",
                    "labels": {"signed_by": "key-1"},
                    "distributions": {"rpms": "https://example.com/rpms/"},
                }
            },
        }
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/new/",
                sha256="def",
                distribution_url="https://rok.example/side-tag-mytest/Packages/p/pkg.rpm",
            )
        ]
        merged = apply_side_tag_transfer_to_document(
            source,
            transfers,
            side_tag="mytest",
            top_level_side_tag_distribution_url="https://rok.example/side-tag-mytest/",
        )
        assert merged["version"] == 3
        art = merged["artifacts"]["pkg.rpm"]
        assert art["href"] == "/pulp/new/"
        assert art["distributions"]["mytest"].startswith("https://rok.example")
        assert art["distributions"]["rpms"] == "https://example.com/rpms/"
        assert len(art["href_history"]) == 1
        assert art["href_history"][0]["href"] == "/pulp/old/"
        assert merged["distributions"]["mytest"].startswith("https://rok.example")

    def test_append_oci_manifest_history(self) -> None:
        doc = {"version": 4, "oci_manifest": "quay.io/r@sha256:abcd"}
        append_oci_manifest_history(doc)
        history = doc["oci_manifest_history"]
        assert isinstance(history, list)
        assert len(history) == 1
        assert history[0]["ref"] == "quay.io/r"
        assert "oci_manifest" not in doc

    def test_set_oci_manifest(self) -> None:
        doc: dict = {}
        set_oci_manifest(doc, "quay.io/r", "deadbeef")
        assert doc["oci_manifest"] == "quay.io/r@sha256:deadbeef"

    def test_set_oci_manifest_ref_only_when_no_digest(self) -> None:
        doc: dict = {}
        set_oci_manifest(doc, "quay.io/r", "")
        assert doc["oci_manifest"] == "quay.io/r"

    def test_append_href_history_skips_empty_prior(self) -> None:
        art: dict = {"href_history": []}
        append_href_history(art, prior_href="", prior_sha256="x", document_version=1)
        assert art["href_history"] == []

    def test_append_oci_manifest_history_no_manifest(self) -> None:
        doc = {"version": 1}
        append_oci_manifest_history(doc)
        assert "oci_manifest_history" not in doc

    def test_append_oci_manifest_history_invalid_version(self) -> None:
        doc: dict[str, object] = {"version": "bad", "oci_manifest": "quay.io/r@sha256:ab"}
        append_oci_manifest_history(doc)
        history = doc["oci_manifest_history"]
        assert isinstance(history, list)
        assert history[0]["document_version"] == 1

    def test_bump_document_version_invalid_current(self) -> None:
        doc = {"version": "x"}
        assert bump_document_version(doc) == 2

    def test_apply_side_tag_non_dict_artifacts(self) -> None:
        source = {"artifacts": "not-a-dict"}
        merged = apply_side_tag_transfer_to_document(
            source,
            [],
            side_tag="t",
            top_level_side_tag_distribution_url="https://example/side/",
        )
        assert isinstance(merged["artifacts"], dict)

    def test_apply_side_tag_invalid_prior_version(self) -> None:
        source = {"version": "nope", "artifacts": {}}
        merged = apply_side_tag_transfer_to_document(
            source,
            [],
            side_tag="t",
            top_level_side_tag_distribution_url="",
        )
        assert merged["version"] == 2

    def test_apply_side_tag_creates_artifact_entry(self) -> None:
        source = {"artifacts": {}}
        transfers = [
            SideTagRpmTransfer(
                artifact_key="new.rpm",
                pulp_href="/pulp/x/",
                sha256="aa",
                distribution_url="https://example/pkg.rpm",
            )
        ]
        merged = apply_side_tag_transfer_to_document(
            source,
            transfers,
            side_tag="st",
            top_level_side_tag_distribution_url="https://example/side/",
        )
        assert merged["artifacts"]["new.rpm"]["href"] == "/pulp/x/"

    def test_apply_side_tag_retains_distribution_slots_when_href_unchanged(self) -> None:
        source = {
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/same/",
                    "distributions": {"legacy": "https://example/legacy/"},
                }
            }
        }
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/same/",
                sha256="bb",
                distribution_url="https://example/side/pkg.rpm",
            )
        ]
        merged = apply_side_tag_transfer_to_document(
            source,
            transfers,
            side_tag="st",
            top_level_side_tag_distribution_url="https://example/side/",
        )
        per = merged["artifacts"]["pkg.rpm"]["distributions"]
        assert per["legacy"] == "https://example/legacy/"
        assert per["st"] == "https://example/side/pkg.rpm"

    def test_apply_side_tag_skips_duplicate_distribution_slot(self) -> None:
        source = {
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/same/",
                    "distributions": {"st": "https://example/old-side/"},
                }
            }
        }
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/same/",
                sha256="bb",
                distribution_url="https://example/new-side/pkg.rpm",
            )
        ]
        merged = apply_side_tag_transfer_to_document(
            source,
            transfers,
            side_tag="st",
            top_level_side_tag_distribution_url="",
        )
        assert merged["artifacts"]["pkg.rpm"]["distributions"]["st"] == "https://example/new-side/pkg.rpm"

    def test_apply_side_tag_non_dict_distributions_on_artifact(self) -> None:
        source = {
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/same/",
                    "distributions": "invalid",
                }
            }
        }
        transfers = [
            SideTagRpmTransfer(
                artifact_key="pkg.rpm",
                pulp_href="/pulp/same/",
                sha256="bb",
                distribution_url="https://example/side/pkg.rpm",
            )
        ]
        merged = apply_side_tag_transfer_to_document(
            source,
            transfers,
            side_tag="st",
            top_level_side_tag_distribution_url="",
        )
        assert merged["artifacts"]["pkg.rpm"]["distributions"]["st"] == "https://example/side/pkg.rpm"


class TestDocumentFromArtifactJson:
    def test_from_pydantic_model(self) -> None:
        model = ArtifactJsonResponse(artifacts={})
        doc = document_from_artifact_json(model)
        assert "artifacts" in doc

    def test_from_dict(self) -> None:
        doc = document_from_artifact_json({"version": 1})
        assert doc["version"] == 1

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError):
            document_from_artifact_json(42)
