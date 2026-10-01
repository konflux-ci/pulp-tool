"""Tests for shared pulp_results ORAS publish helper."""

from unittest.mock import Mock, patch

import pytest

from pulp_tool.models.pulp_results import PULP_RESULTS_SCHEMA_VERSION, PulpResultsDocument
from pulp_tool.utils.oras_publish import OrasPublishError
from pulp_tool.utils.pulp_results_oci_publish import sync_pulp_results_with_oci_registry


def _results_doc(raw: dict | None = None) -> PulpResultsDocument:
    return PulpResultsDocument.from_raw(raw if raw is not None else {"artifacts": {}})


class TestSyncPulpResultsWithOciRegistry:
    def test_sync_sets_version_and_publishes(self) -> None:
        mock_client = Mock()
        document = _results_doc({"artifacts": {}, "distributions": {}})
        mock_task = Mock()
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=mock_task,
            ) as mock_upload,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/ns/repo", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/ns/repo", "sha256:final"),
            ),
        ):
            oci_ref, task = sync_pulp_results_with_oci_registry(
                mock_client,
                "artifacts-prn",
                document,
                "quay.io/ns/repo:latest",
                {"build_id": "b1"},
                build_id="b1",
            )
        assert document.version == PULP_RESULTS_SCHEMA_VERSION
        assert document.last_updated
        assert "oci_manifest" not in document._mutable_dict()
        assert oci_ref == "quay.io/ns/repo@sha256:final"
        assert task is mock_task
        assert mock_upload.call_count == 2

    def test_sync_uses_attach_when_subject_set(self) -> None:
        document = _results_doc({"artifacts": {}, "version": 1})
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ) as mock_upload,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.attach_pulp_results_manifest",
                return_value=("quay.io/ns/repo", "sha256:attached"),
            ) as mock_attach,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
            ) as mock_push,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
            ) as mock_resolve,
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.PulpResultsDocument.prepare_for_mutation",
            ) as mock_prep,
        ):
            oci_ref, _ = sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/ns/repo:latest",
                {},
                build_id="b1",
                attach_subject="quay.io/ns/repo@sha256:subject",
            )
        mock_prep.assert_called_once()
        mock_attach.assert_called_once()
        mock_push.assert_not_called()
        mock_resolve.assert_not_called()
        assert oci_ref == "quay.io/ns/repo@sha256:attached"
        assert mock_upload.call_count == 2

    def test_sync_requires_oci_storage(self) -> None:
        with pytest.raises(ValueError, match="oci_storage is required"):
            sync_pulp_results_with_oci_registry(Mock(), "prn", _results_doc(), "  ", {}, build_id="b1")

    def test_sync_records_manifest_history(self) -> None:
        mock_client = Mock()
        document = _results_doc({"artifacts": {}, "oci_manifest": "quay.io/r@sha256:old"})
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
            patch("pulp_tool.utils.pulp_results_oci_publish.PulpResultsDocument.prepare_for_mutation") as mock_prep,
        ):
            sync_pulp_results_with_oci_registry(
                mock_client,
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
                record_manifest_history=True,
            )
        mock_prep.assert_called_once()

    def test_sync_prepare_mutation_when_republish_requested(self) -> None:
        document = _results_doc({"version": 1, "artifacts": {}})
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.PulpResultsDocument.prepare_for_mutation",
            ) as mock_prep,
        ):
            sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
                operation="build_sign",
                record_manifest_history=True,
            )
        mock_prep.assert_called_once()

    def test_sync_oci_ref_from_resolve_oci_manifest(self) -> None:
        document = _results_doc({"artifacts": {}})
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "dead"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "final"),
            ),
        ):
            oci_ref, _ = sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
            )
        assert oci_ref == "quay.io/r@sha256:final"

    def test_sync_applies_document_defaults_when_missing(self) -> None:
        document = _results_doc({})
        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.models.pulp_results.normalize_document",
                return_value={"artifacts": {}},
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
        ):
            sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
            )
        assert document.version == PULP_RESULTS_SCHEMA_VERSION
        assert document.last_updated

    def test_sync_touches_last_updated_when_blank(self) -> None:
        document = PulpResultsDocument.model_construct(
            version=PULP_RESULTS_SCHEMA_VERSION,
            last_updated="",
            artifacts={},
        )
        with (
            patch.object(PulpResultsDocument, "normalize_in_place", lambda self: None),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                return_value=Mock(),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
        ):
            sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
            )
        assert document.last_updated

    def test_sync_label_fallback_when_schema_helpers_fail(self) -> None:
        document = PulpResultsDocument.model_construct(
            version="",
            last_updated="2026-01-01",
            artifacts={},
        )
        captured: list[dict] = []

        def fake_upload(*_args, **kwargs):  # noqa: ANN002
            captured.append(dict(kwargs["pulp_label"]))
            return Mock()

        with (
            patch.object(PulpResultsDocument, "normalize_in_place", lambda self: None),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                side_effect=fake_upload,
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.schema_version",
                side_effect=TypeError("bad"),
            ),
        ):
            sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
            )
        assert captured[0]["document_schema_version"] == PULP_RESULTS_SCHEMA_VERSION
        assert captured[0]["document_last_updated"]

    def test_sync_invalid_document_last_updated_label(self) -> None:
        document = _results_doc({"version": "x", "last_updated": "y", "artifacts": {}})
        captured: list[dict] = []

        def fake_upload(*_args, **kwargs):  # noqa: ANN002
            captured.append(dict(kwargs["pulp_label"]))
            return Mock()

        with (
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait",
                side_effect=fake_upload,
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                return_value=("quay.io/r", "sha256:one"),
            ),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.resolve_oci_manifest",
                return_value=("quay.io/r", "sha256:final"),
            ),
        ):
            sync_pulp_results_with_oci_registry(
                Mock(),
                "prn",
                document,
                "quay.io/r:tag",
                {},
                build_id="b1",
            )
        assert captured[0]["document_schema_version"] == "x"
        assert captured[0]["document_last_updated"]
        assert captured[0]["document_schema_version"] == "x"

    def test_sync_wraps_oras_publish_error(self) -> None:
        with (
            patch("pulp_tool.utils.pulp_results_oci_publish.create_file_content_and_wait", return_value=Mock()),
            patch(
                "pulp_tool.utils.pulp_results_oci_publish.push_pulp_results_manifest",
                side_effect=OrasPublishError("oras down"),
            ),
        ):
            with pytest.raises(OrasPublishError, match="oras down"):
                sync_pulp_results_with_oci_registry(
                    Mock(),
                    "prn",
                    _results_doc({"artifacts": {}}),
                    "quay.io/r:tag",
                    {},
                    build_id="b1",
                )
