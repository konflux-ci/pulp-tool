"""Reusable mock HTTP / response builders and upload test factories."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import httpx

from pulp_tool.models.context import UploadRpmContext
from pulp_tool.models.repository import RepositoryRefs
from pulp_tool.models.upload_distribution import DistributionUrlMap


def make_upload_rpm_context(**overrides: Any) -> UploadRpmContext:
    """Minimal :class:`UploadRpmContext` for upload tests."""
    defaults: dict[str, Any] = {
        "build_id": "test-build",
        "date_str": "2024-01-01",
        "namespace": "test-ns",
        "parent_package": "test-pkg",
        "rpm_path": "/test/rpms",
    }
    defaults.update(overrides)
    return UploadRpmContext(**defaults)


def make_repository_refs(**overrides: str) -> RepositoryRefs:
    """Minimal :class:`RepositoryRefs` with empty hrefs unless overridden."""
    defaults: dict[str, str] = {
        "rpms_href": "/rpms",
        "rpms_prn": "rpms-prn",
        "logs_href": "/logs",
        "logs_prn": "logs-prn",
        "sbom_href": "/sbom",
        "sbom_prn": "sbom-prn",
        "artifacts_href": "/artifacts",
        "artifacts_prn": "artifacts-prn",
    }
    defaults.update(overrides)
    return RepositoryRefs(**defaults)


def make_distribution_url_map(urls: dict[str, str] | None = None) -> DistributionUrlMap:
    return DistributionUrlMap.from_dict(urls or {"rpms": "https://example.com/rpms"})


def make_rpm_list_response(results: list) -> httpx.Response:
    """Build a mock httpx.Response for RPM packages list API."""
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {
        "count": len(results),
        "next": None,
        "previous": None,
        "results": results,
    }
    response.raise_for_status = Mock()
    return response


def mock_httpx_response_json(status_code: int, payload: dict[str, Any]) -> Mock:
    """Minimal httpx.Response mock with .json() and status fields."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = ""
    response.headers = httpx.Headers({"content-type": "application/json"})
    return response
