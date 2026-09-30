"""Extra coverage for pulp_results document edge paths."""

from datetime import date

import pytest
from pydantic import ValidationError

from pulp_tool.models import pulp_results as prd
from pulp_tool.models.pulp_results import BUILD_SIGN_OPERATION, PULP_RESULTS_SCHEMA_VERSION, PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs


def test_coerce_schema_version_blank_defaults() -> None:
    assert prd.schema_version({"version": "  "}) == PULP_RESULTS_SCHEMA_VERSION


def test_parse_last_updated_non_string_returns_none() -> None:
    assert prd.parse_last_updated(None) is None
    assert prd.parse_last_updated(12345) is None


def test_normalize_href_history_sets_default_schema_version() -> None:
    doc = prd.normalize_document(
        {
            "artifacts": {
                "a.rpm": {
                    "href_history": [{"href": "/h/", "operation": "build_sign"}],
                }
            }
        }
    )
    entry = doc["artifacts"]["a.rpm"]["href_history"][0]
    assert entry["schema_version"] == PULP_RESULTS_SCHEMA_VERSION


def test_normalize_href_history_coerces_existing_schema_version() -> None:
    doc = prd.normalize_document(
        {
            "artifacts": {
                "a.rpm": {
                    "href_history": [
                        {"href": "/h/", "operation": "build_sign", "schema_version": " 2.0.0 "},
                    ],
                }
            }
        }
    )
    entry = doc["artifacts"]["a.rpm"]["href_history"][0]
    assert entry["schema_version"] == "2.0.0"


def test_merge_upload_outcomes_coerces_non_dict_artifacts_in_place() -> None:
    repos = RepositoryRefs(
        rpms_href="/r/",
        rpms_prn="r",
        logs_href="/l/",
        logs_prn="l",
        sbom_href="/s/",
        sbom_prn="s",
        artifacts_href="/a/",
        artifacts_prn="a",
    )
    upload = PulpResultsDocument(build_id="b1", repositories=repos)
    target = PulpResultsDocument.from_raw(
        {
            "version": "1.0.0",
            "last_updated": "2026-01-01",
            "artifacts": [],
        }
    )
    raw = target.to_canonical_dict()
    raw["artifacts"] = []
    doc = PulpResultsDocument.from_raw(raw)
    doc.merge_upload_outcomes(
        upload,
        operation=BUILD_SIGN_OPERATION,
        signed_by=None,
        replace_signed_by=False,
        verified_distribution_slots=set(),
    )
    assert isinstance(doc.artifacts, dict)


class TestPulpResultsDocumentMethods:
    def test_model_validator_passthrough_non_dict(self) -> None:
        doc = PulpResultsDocument.from_raw({"artifacts": {}})
        again = PulpResultsDocument.model_validate(doc)
        assert again.build_id == doc.build_id
        with pytest.raises(ValidationError):
            PulpResultsDocument.model_validate("not-a-dict")

    def test_from_artifact_json_dict_and_unsupported(self) -> None:
        from_dict = PulpResultsDocument.from_artifact_json({"version": "1.0.0", "artifacts": {}})
        assert from_dict.version == "1.0.0"
        from_model = PulpResultsDocument.from_artifact_json(PulpResultsDocument(artifacts={}))
        assert from_model.artifacts == {}
        with pytest.raises(TypeError, match="Unsupported artifact_json"):
            PulpResultsDocument.from_artifact_json(42)

    def test_empty_shell(self) -> None:
        doc = PulpResultsDocument.empty_shell(build_id="b", namespace="ns", cluster="c1")
        assert doc.build_id == "b"
        assert doc.cluster == "c1"

    def test_mutable_dict_includes_cluster(self) -> None:
        doc = PulpResultsDocument.from_raw({"artifacts": {}, "cluster": "cluster-a"})
        assert doc._mutable_dict()["cluster"] == "cluster-a"

    def test_prepare_for_mutation_on_model(self) -> None:
        prior = "2024-06-01"
        doc = PulpResultsDocument.from_raw(
            {
                "version": "1.0.0",
                "last_updated": prior,
                "artifacts": {"p.rpm": {"href": "/old/", "sha256": "abc"}},
            }
        )
        old = doc.prepare_for_mutation(operation=BUILD_SIGN_OPERATION)
        assert old == prior
        assert doc.last_updated == date.today().isoformat()


def test_normalize_strips_empty_oci_manifest() -> None:
    doc = prd.normalize_document({"oci_manifest": "", "artifacts": {}})
    assert "oci_manifest" not in doc


def test_normalize_skips_non_dict_artifact_rows() -> None:
    doc = prd.normalize_document({"artifacts": {"ok": {"pulp_labels": {"a": "1"}}, "bad": "x"}})
    assert doc["artifacts"]["ok"]["pulp_labels"]["a"] == "1"


def test_normalize_invalid_top_level_distributions() -> None:
    doc = prd.normalize_document({"distributions": "not-a-dict", "artifacts": {}})
    assert doc["distributions"] == {}


def test_document_to_canonical_dict_includes_shell_fields() -> None:
    raw = {
        "build_id": "  b1 ",
        "namespace": "ns",
        "cluster": "c1",
        "oci_manifest": {"ref": "quay.io/r", "digest": "sha256:aa"},
        "distributions": {"rpms": "https://example/rpms/"},
        "artifacts": {},
    }
    out = PulpResultsDocument.from_raw(raw).to_canonical_dict()
    assert out["build_id"] == "b1"
    assert out["namespace"] == "ns"
    assert out["cluster"] == "c1"
    assert "oci_manifest" not in out
    assert out["version"] == prd.PULP_RESULTS_SCHEMA_VERSION


def test_merge_signed_by_replace() -> None:
    assert prd.merge_signed_by("a;b", "c", replace=True) == "c"


def test_merge_signed_by_empty_new_keeps_existing() -> None:
    assert prd.merge_signed_by("a@x.com", "") == "a@x.com"


def test_aggregate_top_level_distributions_merges_rows_and_document() -> None:
    doc = {
        "artifacts": {
            "a.rpm": {"distributions": {"rpms": "https://from-artifact/"}},
            "bad": "skip",
        },
        "distributions": {"logs": "https://from-doc/logs/"},
    }
    agg = prd.aggregate_top_level_distributions(doc)
    assert agg["rpms"] == "https://from-artifact/"
    assert agg["logs"] == "https://from-doc/logs/"


def test_aggregate_top_level_distributions_non_dict_artifacts() -> None:
    assert prd.aggregate_top_level_distributions({"artifacts": []}) == {}


def test_apply_side_tag_empty_transfers() -> None:
    doc = PulpResultsDocument.from_raw({"artifacts": {}})
    out = doc.apply_side_tag_transfer([], side_tag="st", top_level_side_tag_distribution_url="https://ex/side/")
    assert out.distributions.get("st", "").startswith("https://ex/side")
