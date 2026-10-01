"""Tests for pulp_results.json document merge helpers."""

from datetime import date

import pytest

from pulp_tool.models.artifacts import ArtifactMetadata
from pulp_tool.models.pulp_results import (
    BUILD_SIGN_OPERATION,
    PULP_RESULTS_SCHEMA_VERSION,
    PulpResultsDocument,
    SideTagRpmTransfer,
    append_href_history,
    merge_origin_pulp_labels,
    merge_signed_by,
    normalize_document,
    recompute_distributions,
    resolve_predecessor_href,
    retain_distribution_slots,
    side_tag_upload_labels,
)


def _side_tag_doc(source: dict, transfers: list, *, side_tag: str, top_level_side_tag_distribution_url: str) -> dict:
    return (
        PulpResultsDocument.from_raw(source)
        .apply_side_tag_transfer(
            transfers,
            side_tag=side_tag,
            top_level_side_tag_distribution_url=top_level_side_tag_distribution_url,
        )
        .to_canonical_dict()
    )


def _prepare_doc(document: dict, *, operation: str) -> str:
    doc = PulpResultsDocument.from_raw(document)
    old = doc.prepare_for_mutation(operation=operation)
    document.clear()
    document.update(doc.to_canonical_dict())
    return old


def _touch_doc(document: dict) -> str:
    doc = PulpResultsDocument.from_raw(document)
    value = doc.touch_last_updated()
    document.clear()
    document.update(doc.to_canonical_dict())
    return value


class TestRetainDistributionSlots:
    def test_adds_artifact_slot_not_yet_in_merged(self) -> None:
        artifact = ArtifactMetadata(
            href="/pulp/same/",
            distributions={"legacy": "https://example/legacy/"},
        )
        merged = retain_distribution_slots(artifact, "/pulp/same/", {"st": "https://example/side/"})
        assert merged["legacy"] == "https://example/legacy/"
        assert merged["st"] == "https://example/side/"


class TestLineageHelpers:
    def test_resolve_predecessor_href_from_href_field(self) -> None:
        assert resolve_predecessor_href({"href": "/pulp/a/"}) == "/pulp/a/"

    def test_resolve_predecessor_href_from_labels(self) -> None:
        assert resolve_predecessor_href({"pulp_labels": {"source_pulp_href": "/pulp/b/"}}) == "/pulp/b/"

    def test_resolve_predecessor_href_invalid_labels(self) -> None:
        assert resolve_predecessor_href({"labels": "bad"}) == ""

    def test_resolve_predecessor_href_pulp_href_label(self) -> None:
        assert resolve_predecessor_href({"pulp_labels": {"pulp_href": "/pulp/c/"}}) == "/pulp/c/"

    def test_resolve_predecessor_href_from_metadata_labels(self) -> None:
        artifact = ArtifactMetadata(
            href="",
            pulp_labels={"source_pulp_href": "/pulp/from-label/"},
        )
        assert resolve_predecessor_href(artifact) == "/pulp/from-label/"

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
    def test_apply_side_tag_transfer_touches_last_updated_and_history(self) -> None:
        prior_day = "2020-06-15"
        source = {
            "version": "1.0.0",
            "last_updated": prior_day,
            "oci_manifest": {"ref": "quay.io/org/app", "digest": "sha256:old"},
            "distributions": {"rpms": "https://example.com/rpms/"},
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/old/",
                    "sha256": "abc",
                    "url": "https://example.com/pkg.rpm",
                    "pulp_labels": {"signed_by": "key-1"},
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
        merged = _side_tag_doc(
            source,
            transfers,
            side_tag="mytest",
            top_level_side_tag_distribution_url="https://rok.example/side-tag-mytest/",
        )
        assert merged["version"] == "1.0.0"
        assert merged["last_updated"] == date.today().isoformat()
        art = merged["artifacts"]["pkg.rpm"]
        assert art["href"] == "/pulp/new/"
        assert art["distributions"]["mytest"].startswith("https://rok.example")
        assert art["distributions"]["rpms"] == "https://example.com/rpms/"
        assert len(art["href_history"]) == 1
        assert art["href_history"][0]["href"] == "/pulp/old/"
        assert art["href_history"][0]["last_updated"] == prior_day
        assert merged["distributions"]["mytest"].startswith("https://rok.example")

    def test_normalize_strips_legacy_oci_fields(self) -> None:
        raw = {
            "version": 2,
            "oci_manifest": {"ref": "quay.io/r", "digest": "sha256:abcd"},
            "oci_manifest_history": [{"ref": "quay.io/r", "digest": "sha256:old"}],
        }
        doc = normalize_document(raw)
        assert "oci_manifest" not in doc
        assert "oci_manifest_history" not in doc

    def test_append_href_history_skips_empty_prior(self) -> None:
        art = ArtifactMetadata(href_history=[])
        append_href_history(
            art,
            prior_href="",
            prior_sha256="x",
            last_updated="2026-01-01",
        )
        assert art.href_history == []

    def test_touch_document_last_updated_sets_iso_date(self) -> None:
        doc: dict = {"version": "1.0.0", "last_updated": "2019-01-01"}
        assert _touch_doc(doc) == date.today().isoformat()
        assert doc["version"] == "1.0.0"
        assert "revision" not in doc

    def test_apply_side_tag_non_dict_artifacts(self) -> None:
        source = {"artifacts": "not-a-dict"}
        merged = _side_tag_doc(
            source,
            [],
            side_tag="t",
            top_level_side_tag_distribution_url="https://example/side/",
        )
        assert isinstance(merged["artifacts"], dict)

    def test_apply_side_tag_missing_last_updated_still_mutates(self) -> None:
        source = {"artifacts": {}}
        merged = _side_tag_doc(
            source,
            [],
            side_tag="t",
            top_level_side_tag_distribution_url="",
        )
        assert merged["version"] == PULP_RESULTS_SCHEMA_VERSION
        assert merged["last_updated"] == date.today().isoformat()

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
        merged = _side_tag_doc(
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
        merged = _side_tag_doc(
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
        merged = _side_tag_doc(
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
        merged = _side_tag_doc(
            source,
            transfers,
            side_tag="st",
            top_level_side_tag_distribution_url="",
        )
        assert merged["artifacts"]["pkg.rpm"]["distributions"]["st"] == "https://example/side/pkg.rpm"


class TestDocumentFromArtifactJson:
    def test_from_pydantic_model(self) -> None:
        model = PulpResultsDocument(artifacts={})
        doc = PulpResultsDocument.from_artifact_json(model).to_canonical_dict()
        assert "artifacts" in doc

    def test_from_dict(self) -> None:
        doc = PulpResultsDocument.from_artifact_json({"version": "1.0.0"}).to_canonical_dict()
        assert doc["version"] == "1.0.0"

    def test_unsupported_type_raises(self) -> None:
        with pytest.raises(TypeError):
            PulpResultsDocument.from_artifact_json(42)


class TestCanonicalSchema:
    def test_normalize_legacy_labels_and_string_manifest(self) -> None:
        raw = {
            "version": 2,
            "oci_manifest": "quay.io/r@sha256:abc",
            "artifacts": {"a.rpm": {"pulp_labels": {"build_id": "b"}, "href": "/h/"}},
        }
        doc = normalize_document(raw)
        assert "oci_manifest" not in doc
        assert "oci_manifest_history" not in doc
        assert doc["artifacts"]["a.rpm"]["pulp_labels"]["build_id"] == "b"
        assert "labels" not in doc["artifacts"]["a.rpm"]

    def test_merge_signed_by_semicolon(self) -> None:
        assert merge_signed_by("a@x.com", "b@x.com") == "a@x.com;b@x.com"
        assert merge_signed_by("a@x.com", "b@x.com", replace=True) == "b@x.com"

    def test_prepare_document_for_mutation(self) -> None:
        prior_day = "2024-03-01"
        doc = {
            "version": "1.0.0",
            "last_updated": prior_day,
            "oci_manifest": {"ref": "quay.io/r", "digest": "sha256:aa"},
            "artifacts": {"p.rpm": {"href": "/old/", "sha256": "x"}},
        }
        old = _prepare_doc(doc, operation=BUILD_SIGN_OPERATION)
        assert old == prior_day
        assert doc["version"] == "1.0.0"
        assert doc["last_updated"] == date.today().isoformat()
        assert "oci_manifest_history" not in doc
        artifacts = doc.get("artifacts")
        assert isinstance(artifacts, dict)
        art_row = artifacts["p.rpm"]
        assert isinstance(art_row, dict)
        art_history = art_row["href_history"]
        assert isinstance(art_history, list)
        assert art_history[0]["href"] == "/old/"
        assert art_history[0]["last_updated"] == prior_day

    def test_recompute_distributions_prunes(self) -> None:
        art = {"distributions": {"rpms": "https://a/", "stale": "https://old/"}}
        out = recompute_distributions(art, {"rpms"}, slot_updates={"rpms": "https://new/"})
        assert out == {"rpms": "https://new/"}
        assert "stale" not in out

    def test_document_to_canonical_json_uses_pulp_labels(self) -> None:
        doc = normalize_document({"artifacts": {"f.rpm": {"pulp_labels": {"arch": "x86_64"}}}})
        text = PulpResultsDocument.from_raw(doc).to_canonical_json()
        assert '"pulp_labels"' in text
        assert '"labels"' not in text

    def test_initial_document_shell(self) -> None:
        doc = PulpResultsDocument.empty_shell(build_id="b", namespace="ns", cluster="c1").to_canonical_dict()
        assert doc["version"] == PULP_RESULTS_SCHEMA_VERSION
        assert doc["last_updated"] == date.today().isoformat()
        assert doc["cluster"] == "c1"
