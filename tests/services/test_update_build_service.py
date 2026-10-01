"""Tests for update-build service helpers."""

from typing import Any, cast
from unittest.mock import patch

from pulp_tool.models.pulp_results import BUILD_SIGN_OPERATION, PulpResultsDocument
from pulp_tool.models.repository import RepositoryRefs


def test_merge_upload_outcomes_updates_artifact_and_signed_by() -> None:
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
    model = PulpResultsDocument(build_id="b1", repositories=repos)
    model.add_artifact("pkg.rpm", "https://new/url", "deadbeef", {"arch": "x86_64", "signed_by": "s1"})
    model.artifacts["pkg.rpm"].href = "/pulp/new/"

    doc = PulpResultsDocument.from_raw(
        {
            "version": 1,
            "artifacts": {
                "pkg.rpm": {
                    "href": "/pulp/old/",
                    "sha256": "old",
                    "url": "https://old/",
                    "pulp_labels": {"signed_by": "s0"},
                    "distributions": {"rpms": "https://old/rpms/"},
                }
            },
        }
    )
    doc.merge_upload_outcomes(
        model,
        operation=BUILD_SIGN_OPERATION,
        signed_by="s1",
        replace_signed_by=False,
        verified_distribution_slots={"rpms"},
    )
    row_dict = doc._mutable_dict()["artifacts"]["pkg.rpm"]
    row = row_dict
    assert row["href"] == "/pulp/new/"
    pulp_labels = row["pulp_labels"]
    assert isinstance(pulp_labels, dict)
    assert "s0" in pulp_labels["signed_by"]
    assert "s1" in pulp_labels["signed_by"]
    href_hist = row["href_history"]
    assert isinstance(href_hist, list)
    assert len(href_hist) == 1


def test_merge_upload_outcomes_non_dict_artifacts_and_new_row() -> None:
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
    model = PulpResultsDocument(build_id="b1", repositories=repos)
    model.add_artifact("new.rpm", "https://u/", "abc", {"arch": "noarch"})
    model.artifacts["new.rpm"].href = "/pulp/h/"

    doc = PulpResultsDocument.from_raw({"version": "bad", "artifacts": []})
    doc.merge_upload_outcomes(
        model,
        operation=BUILD_SIGN_OPERATION,
        signed_by="signer@x.com",
        replace_signed_by=False,
        verified_distribution_slots={"rpms"},
    )
    row = cast(dict[str, Any], doc._mutable_dict()["artifacts"]["new.rpm"])
    assert row["pulp_labels"]["signed_by"] == "signer@x.com"


def test_merge_signed_by_from_context_when_upload_labels_empty() -> None:
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
    model = PulpResultsDocument(build_id="b1", repositories=repos)
    model.add_artifact("p.rpm", "https://u/", "abc", {"arch": "x86_64"})
    model.artifacts["p.rpm"].href = "/pulp/h/"

    doc = PulpResultsDocument.from_raw({"version": 1, "artifacts": {"p.rpm": "not-a-dict"}})
    doc.merge_upload_outcomes(
        model,
        operation=BUILD_SIGN_OPERATION,
        signed_by="only-from-arg@x.com",
        replace_signed_by=True,
        verified_distribution_slots=set(),
    )
    row = cast(dict[str, Any], doc._mutable_dict()["artifacts"]["p.rpm"])
    labels = row["pulp_labels"]
    assert labels["signed_by"] == "only-from-arg@x.com"


def test_merge_appends_history_when_href_first_populated() -> None:
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
    model = PulpResultsDocument(build_id="b1", repositories=repos)
    model.add_artifact("p.rpm", "https://u/", "abc", {"arch": "x86_64"})
    model.artifacts["p.rpm"].href = "/pulp/content/new/"

    doc = PulpResultsDocument.from_raw(
        {
            "version": 1,
            "artifacts": {"p.rpm": {"href": "/pulp/old/", "url": "https://u/", "sha256": "abc", "pulp_labels": {}}},
        }
    )
    doc.merge_upload_outcomes(
        model,
        operation=BUILD_SIGN_OPERATION,
        signed_by=None,
        replace_signed_by=False,
        verified_distribution_slots=set(),
    )
    row = doc._mutable_dict()["artifacts"]["p.rpm"]
    history = row["href_history"]
    assert isinstance(history, list)
    assert len(history) == 1
    assert history[0]["href"] == "/pulp/old/"


def test_merge_coerces_non_dict_artifacts_after_normalize_bypass() -> None:
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
    model = PulpResultsDocument(build_id="b1", repositories=repos)
    doc = PulpResultsDocument.from_raw({"version": 1, "artifacts": "not-a-dict"})
    with patch("pulp_tool.models.pulp_results.normalize_document"):
        doc.merge_upload_outcomes(
            model,
            operation=BUILD_SIGN_OPERATION,
            signed_by=None,
            replace_signed_by=False,
            verified_distribution_slots=set(),
        )
    assert doc.to_canonical_dict()["artifacts"] == {}
