"""PulpClient tests (split module)."""

import json
import re
from unittest.mock import Mock, patch

import httpx
import pytest
from httpx import HTTPError

from pulp_tool.api import PulpClient
from pulp_tool.models.artifacts import ExtraArtifactRef, PulpContentRow
from pulp_tool.models.pulp_api import RpmDistributionRequest, RpmRepositoryRequest


class TestPulpClient:
    def test_gather_content_data(self, mock_pulp_client, mock_content_data, httpx_mock) -> None:
        """Test gather_content_data method."""
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json=mock_content_data, headers={"content-type": "application/json"}))
        content_data = mock_pulp_client.gather_content_data("test-build-123")
        assert len(content_data.content_results) == 1
        assert len(content_data.artifacts) == 1
        assert content_data.content_results[0].pulp_href == "/pulp/api/v3/content/rpm/packages/12345/"

    def test_gather_content_data_no_results(self, mock_pulp_client, httpx_mock) -> None:
        """Test gather_content_data method with no results."""
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json={"results": []}, headers={"content-type": "application/json"}))
        content_data = mock_pulp_client.gather_content_data("test-build-123")
        assert content_data.content_results == []
        assert content_data.artifacts == []

    def test_gather_content_data_with_extra_artifacts(self, mock_pulp_client, mock_content_data, httpx_mock) -> None:
        """Test gather_content_data method with extra artifacts."""
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build-123"
        ).mock(return_value=httpx.Response(200, json=mock_content_data, headers={"content-type": "application/json"}))
        extra_artifacts = [
            ExtraArtifactRef.model_validate({"file": "/pulp/api/v3/artifacts/67890/"}),
            ExtraArtifactRef.model_validate({"extra": "/pulp/api/v3/artifacts/99999/"}),
        ]
        content_data = mock_pulp_client.gather_content_data("test-build-123", extra_artifacts)
        assert len(content_data.content_results) == 1
        assert len(content_data.artifacts) == 1

    def test_gather_content_data_href_fallback_bare_list_json(
        self, mock_pulp_client, mock_content_data, httpx_mock
    ) -> None:
        """When build_id finds nothing, href query may return a bare JSON array instead of {"results": ...}."""
        httpx_mock.get(
            re.compile(
                "https://pulp\\.example\\.com/pulp/api/v3/test-domain/api/v3/content/"
                "\\?pulp_label_select=build_id~test-bare-list"
            )
        ).mock(return_value=httpx.Response(200, json={"results": []}))
        row = mock_content_data["results"][0]
        httpx_mock.get(re.compile(".*api/v3/content/\\?pulp_href__in=.*")).mock(
            return_value=httpx.Response(200, json=[row])
        )
        href = row["pulp_href"]
        extra = [ExtraArtifactRef.model_validate({"pulp_href": href})]
        content_data = mock_pulp_client.gather_content_data("test-bare-list", extra)
        assert len(content_data.content_results) == 1
        assert content_data.content_results[0].pulp_href == href
        assert len(content_data.artifacts) >= 1

    def test_gather_content_data_ignores_repository_version_hrefs_in_fallback(
        self, mock_pulp_client, httpx_mock
    ) -> None:
        """add_content task created_resources are repo versions; must not be sent to pulp_href__in."""
        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?pulp_label_select=build_id~test-build"
        ).mock(return_value=httpx.Response(200, json={"results": []}))
        extra = [
            ExtraArtifactRef(
                pulp_href="/api/pulp/domain/api/v3/repositories/rpm/rpm/abc/versions/1/",
            )
        ]
        with patch.object(mock_pulp_client, "find_content", wraps=mock_pulp_client.find_content) as mock_find:
            content_data = mock_pulp_client.gather_content_data("test-build", extra)
        assert content_data.content_results == []
        assert mock_find.call_count == 1
        assert mock_find.call_args_list[0].args[0] == "build_id"

    def test_build_results_structure(
        self, mock_pulp_client, mock_content_data, mock_file_locations, httpx_mock
    ) -> None:
        """Test build_results_structure method."""
        from pulp_tool.models import FileInfoModel, PulpResultsModel, RepositoryRefs

        httpx_mock.get(
            "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/artifacts/"
            "?pulp_href__in=/pulp/api/v3/artifacts/67890/"
        ).mock(return_value=httpx.Response(200, json=mock_file_locations))
        content_results = [PulpContentRow.model_validate(r) for r in mock_content_data["results"]]
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsModel(build_id="test-build-123", repositories=repositories)
        file_info = FileInfoModel(**mock_file_locations["results"][0])
        file_info_map = {"/pulp/api/v3/artifacts/67890/": file_info}
        result = mock_pulp_client.build_results_structure(results_model, content_results, file_info_map)
        assert result.artifact_count == 1
        assert "test-build-123/x86_64/test-package.rpm" in result.artifacts

    def test_build_results_structure_merge_preserves_incremental_and_adds_new(
        self, mock_pulp_client, mock_content_data
    ) -> None:
        """merge=True keeps existing artifact entries; still adds keys from gather."""
        from pulp_tool.models import FileInfoModel, PulpResultsModel, RepositoryRefs

        base = mock_content_data["results"][0]
        labels = dict(base["pulp_labels"])
        content_results = [
            PulpContentRow.model_validate(
                {
                    **base,
                    "artifacts": {
                        "test-build-123/x86_64/test-package.rpm": "/pulp/api/v3/artifacts/67890/",
                        "test-build-123/x86_64/extra.rpm": "/pulp/api/v3/artifacts/11111/",
                    },
                }
            )
        ]
        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsModel(build_id="test-build-123", repositories=repositories)
        inc_url = "https://incremental.example/test-package.rpm"
        results_model.add_artifact("test-build-123/x86_64/test-package.rpm", inc_url, "incremental-sha", labels)
        file_info_map = {
            "/pulp/api/v3/artifacts/67890/": FileInfoModel(
                pulp_href="/pulp/api/v3/artifacts/67890/",
                file="test-package.rpm@sha256:gather67890",
                sha256="gather67890",
            ),
            "/pulp/api/v3/artifacts/11111/": FileInfoModel(
                pulp_href="/pulp/api/v3/artifacts/11111/", file="extra.rpm@sha256:gather11111", sha256="gather11111"
            ),
        }
        distribution_urls = {"rpms": "https://pulp.example.com/pulp/content/test-build/rpms/"}
        with patch("pulp_tool.api.pulp_client.results.logging") as mock_logging:
            result = mock_pulp_client.build_results_structure(
                results_model, content_results, file_info_map, distribution_urls, merge=True
            )
        assert result.artifact_count == 2
        assert result.artifacts["test-build-123/x86_64/test-package.rpm"].url == inc_url
        assert result.artifacts["test-build-123/x86_64/test-package.rpm"].sha256 == "incremental-sha"
        assert "test-build-123/x86_64/extra.rpm" in result.artifacts
        warn_msgs = [str(c) for c in mock_logging.warning.call_args_list]
        assert any("differs from incremental" in m for m in warn_msgs)

    def test_build_results_structure_invalid_artifact_href(
        self, mock_pulp_client, mock_content_data, httpx_mock
    ) -> None:
        """Test build_results_structure with invalid artifact hrefs (line 1249)."""
        from pulp_tool.models import FileInfoModel, PulpResultsModel, RepositoryRefs

        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsModel(build_id="test-build-123", repositories=repositories)
        content_results = [
            PulpContentRow.model_validate(
                {
                    "pulp_href": "/content/123/",
                    "pulp_labels": {"build_id": "test-build-123"},
                    "artifacts": {
                        "valid.rpm": "/pulp/api/v3/artifacts/67890/",
                        "invalid1.txt": "/content/invalid/",
                        "invalid2.txt": "",
                        "invalid3.txt": None,
                    },
                    "relative_path": "test-package.rpm",
                }
            )
        ]
        file_info = FileInfoModel(
            pulp_href="/pulp/api/v3/artifacts/67890/", file="test-package.rpm@sha256:abc", sha256="abc"
        )
        file_info_map = {"/pulp/api/v3/artifacts/67890/": file_info}
        result = mock_pulp_client.build_results_structure(results_model, content_results, file_info_map)
        assert result.artifact_count == 1

    def test_build_results_structure_missing_file_info_many(
        self, mock_pulp_client, mock_content_data, httpx_mock
    ) -> None:
        """Test build_results_structure with many missing file info entries (line 1286)."""
        from pulp_tool.models import PulpResultsModel, RepositoryRefs

        repositories = RepositoryRefs(
            rpms_href="/rpms/",
            rpms_prn="rpms-prn",
            logs_href="/logs/",
            logs_prn="logs-prn",
            sbom_href="/sbom/",
            sbom_prn="sbom-prn",
            artifacts_href="/artifacts/",
            artifacts_prn="artifacts-prn",
        )
        results_model = PulpResultsModel(build_id="test-build-123", repositories=repositories)
        content_results = [
            PulpContentRow.model_validate(
                {
                    "pulp_href": "/content/123/",
                    "pulp_labels": {"build_id": "test-build-123"},
                    "artifacts": {f"file{i}.txt": f"/pulp/api/v3/artifacts/{i}/" for i in range(10)},
                    "relative_path": "test.txt",
                }
            )
        ]
        from pulp_tool.models import FileInfoModel

        file_info_map = {
            "/pulp/api/v3/artifacts/0/": FileInfoModel(
                pulp_href="/pulp/api/v3/artifacts/0/", file="file0.txt@sha256:abc", sha256="abc"
            )
        }
        with patch("pulp_tool.api.pulp_client.results.logging") as mock_logging:
            result = mock_pulp_client.build_results_structure(results_model, content_results, file_info_map)
            assert result.artifact_count == 1
            mock_logging.warning.assert_called()
            warning_calls = [call for call in mock_logging.warning.call_args_list if "Missing file info" in str(call)]
            assert len(warning_calls) > 0

    def test_repository_operation_create_repo(self, mock_pulp_client, httpx_mock) -> None:
        """Test repository_operation method for creating repository."""
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/repositories/rpm/rpm/").mock(
            return_value=httpx.Response(201, json={"pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/"})
        )
        new_repo = RpmRepositoryRequest(name="test-repo", autopublish=True)
        result = mock_pulp_client.repository_operation("create_repo", "rpm", repository_data=new_repo)
        captured_request = httpx_mock.calls[0].request.content
        captured_request_body = json.loads(captured_request)
        expected_request_body = {"name": "test-repo", "autopublish": True}
        assert captured_request_body == expected_request_body
        assert result.status_code == 201
        assert result.json()["pulp_href"] == "/pulp/api/v3/repositories/rpm/rpm/12345/"

    def test_repository_operation_create_repo_missing_data(self, mock_pulp_client) -> None:
        with pytest.raises(ValueError, match="Repository data is required for 'create_repo' operations"):
            mock_pulp_client.repository_operation("create_repo", "rpm", repository_data=None)

    def test_repository_operation_get_repo(self, mock_pulp_client, mock_response) -> None:
        """Test repository_operation method for getting repository."""
        mock_pulp_client._get_single_resource = Mock()
        mock_pulp_client._get_single_resource.return_value = mock_response
        result = mock_pulp_client.repository_operation("get_repo", "rpm", name="test-repo")
        assert result == mock_response
        mock_pulp_client._get_single_resource.assert_called_once()

    def test_repository_operation_get_repo_missing_name(self, mock_pulp_client) -> None:
        with pytest.raises(ValueError, match="Name is required for 'get_repo' operations"):
            mock_pulp_client.repository_operation("get_repo", "rpm", name=None)

    def test_repository_operation_create_distro(self, mock_pulp_client, httpx_mock) -> None:
        """Test repository_operation method for creating distribution."""
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/distributions/rpm/rpm/").mock(
            return_value=httpx.Response(201, json={"pulp_href": "/pulp/api/v3/distributions/rpm/rpm/12345/"})
        )
        new_distro = RpmDistributionRequest(name="test-distro", base_path="test-distro", repository="test-repo")
        result = mock_pulp_client.repository_operation("create_distro", "rpm", distribution_data=new_distro)
        captured_request = httpx_mock.calls[0].request.content
        captured_request_body = json.loads(captured_request)
        expected_request_body = {"name": "test-distro", "base_path": "test-distro", "repository": "test-repo"}
        assert captured_request_body == expected_request_body
        assert result.status_code == 201
        assert result.json()["pulp_href"] == "/pulp/api/v3/distributions/rpm/rpm/12345/"

    def test_repository_operation_create_distro_missing_data(self, mock_pulp_client) -> None:
        with pytest.raises(ValueError, match="Distribution data is required for 'create_distro' operations"):
            mock_pulp_client.repository_operation("create_distro", "rpm", distribution_data=None)

    def test_repository_operation_get_distro(self, mock_pulp_client, mock_response) -> None:
        """Test repository_operation method for getting distribution."""
        mock_pulp_client._get_single_resource = Mock()
        mock_pulp_client._get_single_resource.return_value = mock_response
        result = mock_pulp_client.repository_operation("get_distro", "rpm", name="test-distro")
        assert result == mock_response
        mock_pulp_client._get_single_resource.assert_called_once()

    def test_repository_operation_get_distro_missing_name(self, mock_pulp_client) -> None:
        with pytest.raises(ValueError, match="Name is required for 'get_distro' operations"):
            mock_pulp_client.repository_operation("get_distro", "rpm", name=None)

    def test_repository_operation_update_distro(self, mock_pulp_client, httpx_mock) -> None:
        """Test repository_operation method for updating distribution."""
        httpx_mock.patch("https://pulp.example.com/pulp/api/v3/distributions/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/distributions/rpm/rpm/12345/"})
        )
        result = mock_pulp_client.repository_operation(
            "update_distro",
            "rpm",
            name="test-distro",
            distribution_href="/pulp/api/v3/distributions/12345/",
            publication="/pulp/api/v3/publications/67890/",
        )
        assert result.status_code == 200
        assert result.json()["pulp_href"] == "/pulp/api/v3/distributions/rpm/rpm/12345/"

    def test_tomllib_import(self) -> None:
        """Test tomllib import (built-in in Python 3.12+)."""
        import pulp_tool.api.pulp_client.client

        assert hasattr(pulp_tool.api.pulp_client.client, "tomllib")

    def test_chunked_get_small_list(self, mock_pulp_client, httpx_mock) -> None:
        """Test _chunked_get method with small parameter list (no chunking)."""
        httpx_mock.get("https://test.com/api").mock(
            return_value=httpx.Response(200, json={"results": [{"id": 1}, {"id": 2}]})
        )
        params = {"small_param": "item1,item2"}
        result = mock_pulp_client._chunked_get("https://test.com/api", params, chunk_param="small_param", chunk_size=50)
        assert result.status_code == 200
        assert len(result.json()["results"]) == 2

    def test_chunked_get_empty_chunk_fallback(self, mock_pulp_client, httpx_mock) -> None:
        """Test _chunked_get method with empty chunk fallback."""
        httpx_mock.get("https://test.com/api").mock(return_value=httpx.Response(200, json={"results": []}))
        params = {"empty_param": ""}
        result = mock_pulp_client._chunked_get("https://test.com/api", params, chunk_param="empty_param", chunk_size=50)
        assert result.status_code == 200
        assert len(result.json()["results"]) == 0

    def test_request_params_without_headers(self, mock_config) -> None:
        """Test request_params property without headers."""
        config_without_cert = {k: v for k, v in mock_config.items() if k not in ("cert", "key")}
        client = PulpClient(config_without_cert)
        params = client.request_params
        assert "headers" not in params
        assert "auth" in params
        assert "cert" not in params

    def test_check_response_json_decode_error(self, mock_pulp_client, httpx_mock) -> None:
        """Test _check_response method with JSON decode error."""
        httpx_mock.get("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/?test_param=value1").mock(
            return_value=httpx.Response(500, text="Invalid JSON response", headers={"content-type": "application/json"})
        )
        with patch("pulp_tool.api.pulp_client.client.logging") as mock_logging:
            with pytest.raises(HTTPError, match="Failed to chunked request"):
                mock_pulp_client._chunked_get(
                    "https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/",
                    {"test_param": "value1,value2"},
                    chunk_param="test_param",
                    chunk_size=1,
                )
            mock_logging.error.assert_called()

    def test_create_file_content_with_arch(self, mock_pulp_client, httpx_mock) -> None:
        """Test create_file_content method with arch parameter."""
        httpx_mock.post("https://pulp.example.com/pulp/api/v3/test-domain/api/v3/content/file/files/").mock(
            return_value=httpx.Response(202, json={"task": "/pulp/api/v3/tasks/12345/"})
        )
        labels = {"build_id": "test-build"}
        content = '{"test": "data"}'
        result = mock_pulp_client.create_file_content(
            "test-repo", content, build_id="test-build", pulp_label=labels, filename="test.json", arch="x86_64"
        )
        assert result.status_code == 202
        assert result.json()["task"] == "/pulp/api/v3/tasks/12345/"

    def test_repository_operation_update_distro_with_publication(self, mock_pulp_client, httpx_mock) -> None:
        """Test repository_operation method for updating distribution with publication."""
        httpx_mock.patch("https://pulp.example.com/pulp/api/v3/distributions/12345/").mock(
            return_value=httpx.Response(200, json={"pulp_href": "/pulp/api/v3/distributions/rpm/rpm/12345/"})
        )
        result = mock_pulp_client.repository_operation(
            "update_distro",
            "rpm",
            name="test-distro",
            distribution_href="/pulp/api/v3/distributions/12345/",
            publication="/pulp/api/v3/publications/67890/",
        )
        assert result.status_code == 200
        assert result.json()["pulp_href"] == "/pulp/api/v3/distributions/rpm/rpm/12345/"
