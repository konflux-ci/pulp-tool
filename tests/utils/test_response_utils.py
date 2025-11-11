"""Tests for response utilities module."""

import pytest
import httpx

from pulp_tool.utils.response_utils import (
    parse_json_response,
    extract_task_href,
    extract_created_resources,
    check_task_success,
    extract_results_list,
    extract_single_result,
    get_response_field,
)
from pulp_tool.models.pulp_api import TaskResponse


class TestParseJsonResponse:
    """Test parse_json_response utility."""

    def test_parse_json_success(self):
        """Test parsing successful JSON response."""
        response = httpx.Response(200, json={"key": "value", "number": 42})
        result = parse_json_response(response, "test operation")
        assert result == {"key": "value", "number": 42}

    def test_parse_json_skip_success_check(self):
        """Test parsing JSON with success check disabled."""
        response = httpx.Response(400, json={"error": "test"})
        result = parse_json_response(response, "test operation", check_success=False)
        assert result == {"error": "test"}

    def test_parse_json_non_success_status(self):
        """Test parsing JSON with non-success status raises error."""
        response = httpx.Response(400, json={"error": "test"})
        with pytest.raises(ValueError, match="Response not successful"):
            parse_json_response(response, "test operation")

    def test_parse_json_invalid_json(self):
        """Test parsing invalid JSON raises error."""
        response = httpx.Response(200, content=b"not json")
        with pytest.raises(ValueError, match="Invalid JSON response"):
            parse_json_response(response, "test operation")


class TestExtractTaskHref:
    """Test extract_task_href utility."""

    def test_extract_task_href_success(self):
        """Test successful task href extraction."""
        response = httpx.Response(202, json={"task": "/pulp/api/v3/tasks/12345/"})
        result = extract_task_href(response, "create repository")
        assert result == "/pulp/api/v3/tasks/12345/"

    def test_extract_task_href_missing_key(self):
        """Test extraction fails when task key is missing."""
        response = httpx.Response(200, json={"other": "data"})
        with pytest.raises(KeyError, match="does not contain task href"):
            extract_task_href(response, "create repository")

    def test_extract_task_href_invalid_json(self):
        """Test extraction fails with invalid JSON."""
        response = httpx.Response(200, content=b"not json")
        with pytest.raises(ValueError, match="Invalid JSON response"):
            extract_task_href(response, "create repository")


class TestExtractCreatedResources:
    """Test extract_created_resources utility."""

    def test_extract_created_resources_success(self):
        """Test extracting created resources from task response."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="completed",
            created_resources=["/pulp/api/v3/repo/1/", "/pulp/api/v3/repo/2/"],
        )
        result = extract_created_resources(task_response, "test operation")
        assert len(result) == 2
        assert "/pulp/api/v3/repo/1/" in result

    def test_extract_created_resources_empty(self):
        """Test extracting when no resources were created."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="completed",
            created_resources=[],
        )
        result = extract_created_resources(task_response, "test operation")
        assert result == []

    def test_extract_created_resources_none(self):
        """Test extracting when created_resources is None."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="completed",
        )
        result = extract_created_resources(task_response, "test operation")
        assert result == []


class TestCheckTaskSuccess:
    """Test check_task_success utility."""

    def test_check_task_success_completed(self):
        """Test successful task check."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="completed",
        )
        result = check_task_success(task_response, "test operation")
        assert result is True

    def test_check_task_success_failed_with_error(self):
        """Test failed task with error description."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="failed",
            error={"description": "Database connection failed"},
        )
        with pytest.raises(ValueError, match="Task failed.*Database connection failed"):
            check_task_success(task_response, "test operation")

    def test_check_task_success_failed_no_error(self):
        """Test failed task without error description."""
        task_response = TaskResponse(
            pulp_href="/pulp/api/v3/tasks/123/",
            state="failed",
        )
        with pytest.raises(ValueError, match="Task failed.*Unknown error"):
            check_task_success(task_response, "test operation")


class TestExtractResultsList:
    """Test extract_results_list utility."""

    def test_extract_results_list_success(self):
        """Test extracting results list from response."""
        response = httpx.Response(
            200,
            json={
                "results": [{"id": 1, "name": "test1"}, {"id": 2, "name": "test2"}],
                "count": 2,
            },
        )
        result = extract_results_list(response, "search operation")
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_extract_results_list_empty_allowed(self):
        """Test extracting empty results when allowed."""
        response = httpx.Response(200, json={"results": [], "count": 0})
        result = extract_results_list(response, "search operation", allow_empty=True)
        assert result == []

    def test_extract_results_list_empty_not_allowed(self):
        """Test extracting empty results when not allowed raises error."""
        response = httpx.Response(200, json={"results": [], "count": 0})
        with pytest.raises(ValueError, match="Empty results"):
            extract_results_list(response, "search operation", allow_empty=False)

    def test_extract_results_list_missing_results_key(self):
        """Test extraction when results key is missing."""
        response = httpx.Response(200, json={"count": 0})
        result = extract_results_list(response, "search operation", allow_empty=True)
        assert result == []


class TestExtractSingleResult:
    """Test extract_single_result utility."""

    def test_extract_single_result_success(self):
        """Test extracting single result from response."""
        response = httpx.Response(
            200,
            json={"results": [{"id": 1, "name": "test"}], "count": 1},
        )
        result = extract_single_result(response, "get operation")
        assert result == {"id": 1, "name": "test"}

    def test_extract_single_result_empty(self):
        """Test extracting single result from empty response fails."""
        response = httpx.Response(200, json={"results": [], "count": 0})
        with pytest.raises(ValueError, match="Empty results"):
            extract_single_result(response, "get operation")


class TestGetResponseField:
    """Test get_response_field utility."""

    def test_get_response_field_exists(self):
        """Test getting existing field from response."""
        response = httpx.Response(200, json={"field": "value", "other": 123})
        result = get_response_field(response, "field", "test operation")
        assert result == "value"

    def test_get_response_field_missing_with_default(self):
        """Test getting missing field returns default."""
        response = httpx.Response(200, json={"other": "value"})
        result = get_response_field(response, "missing", "test operation", default="default_value")
        assert result == "default_value"

    def test_get_response_field_missing_no_default(self):
        """Test getting missing field with no default returns None."""
        response = httpx.Response(200, json={"other": "value"})
        result = get_response_field(response, "missing", "test operation")
        assert result is None

    def test_get_response_field_none_value(self):
        """Test getting field with None value."""
        response = httpx.Response(200, json={"field": None})
        result = get_response_field(response, "field", "test operation", default="default")
        assert result is None
