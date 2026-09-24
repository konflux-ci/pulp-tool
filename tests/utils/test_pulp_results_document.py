"""Tests for pulp_results.json document merge helpers."""

from pulp_tool.utils.pulp_results_document import (
    SideTagRpmTransfer,
    append_oci_manifest_history,
    apply_side_tag_transfer_to_document,
    merge_origin_pulp_labels,
    resolve_predecessor_href,
    set_oci_manifest,
    side_tag_upload_labels,
)


class TestLineageHelpers:
    def test_resolve_predecessor_href_from_href_field(self) -> None:
        assert resolve_predecessor_href({"href": "/pulp/a/"}) == "/pulp/a/"

    def test_resolve_predecessor_href_from_labels(self) -> None:
        assert resolve_predecessor_href({"labels": {"source_pulp_href": "/pulp/b/"}}) == "/pulp/b/"

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
