"""Tests for logging utilities."""

import logging

from pulp_tool.utils.logging_utils import (
    log_operation_start,
    log_operation_complete,
    log_artifact_summary,
    format_count_with_unit,
    format_artifact_counts,
    format_file_size,
    log_file_size,
    log_progress,
    log_summary_separator,
    log_list_items,
)


class TestLogOperations:
    """Tests for operation logging functions."""

    def test_log_operation_start_no_details(self, caplog):
        """Test logging operation start without details."""
        with caplog.at_level(logging.INFO):
            log_operation_start("test operation")
        assert "Starting test operation" in caplog.text

    def test_log_operation_start_with_details(self, caplog):
        """Test logging operation start with details."""
        with caplog.at_level(logging.INFO):
            log_operation_start("test operation", build_id="test-123", count=5)
        assert "Starting test operation" in caplog.text
        assert "build_id=test-123" in caplog.text
        assert "count=5" in caplog.text

    def test_log_operation_complete_no_details(self, caplog):
        """Test logging operation complete without details."""
        with caplog.at_level(logging.INFO):
            log_operation_complete("test operation")
        assert "Completed test operation" in caplog.text

    def test_log_operation_complete_with_details(self, caplog):
        """Test logging operation complete with details."""
        with caplog.at_level(logging.INFO):
            log_operation_complete("test operation", status="success")
        assert "Completed test operation" in caplog.text
        assert "status=success" in caplog.text


class TestArtifactLogging:
    """Tests for artifact logging functions."""

    def test_log_artifact_summary_empty(self, caplog):
        """Test logging artifact summary with no artifacts."""
        with caplog.at_level(logging.INFO):
            log_artifact_summary({})
        assert "No artifacts" in caplog.text

    def test_log_artifact_summary_with_counts(self, caplog):
        """Test logging artifact summary with counts."""
        with caplog.at_level(logging.INFO):
            log_artifact_summary({"rpms": 5, "logs": 3}, operation="Downloaded")
        assert "Downloaded:" in caplog.text
        assert "5" in caplog.text and "rpms" in caplog.text.lower()
        assert "3" in caplog.text and "logs" in caplog.text.lower()

    def test_log_artifact_summary_zero_counts(self, caplog):
        """Test logging artifact summary with zero counts."""
        with caplog.at_level(logging.INFO):
            log_artifact_summary({"rpms": 0, "logs": 0})
        assert "No artifacts" in caplog.text


class TestCountFormatting:
    """Tests for count formatting functions."""

    def test_format_count_with_unit_singular(self):
        """Test formatting singular count."""
        assert format_count_with_unit(1, "RPM") == "1 RPM"

    def test_format_count_with_unit_plural(self):
        """Test formatting plural count."""
        assert format_count_with_unit(5, "RPM") == "5 RPMs"

    def test_format_count_with_unit_explicit_singular(self):
        """Test formatting with explicit singular form."""
        result = format_count_with_unit(1, "repositories", singular="repository")
        assert result == "1 repository"

    def test_format_count_with_unit_already_plural(self):
        """Test formatting with already plural unit."""
        assert format_count_with_unit(5, "repositories") == "5 repositories"

    def test_format_artifact_counts_empty(self):
        """Test formatting empty artifact counts."""
        assert format_artifact_counts({}) == "No artifacts"

    def test_format_artifact_counts_with_data(self):
        """Test formatting artifact counts with data."""
        result = format_artifact_counts({"rpms": 5, "logs": 3, "sboms": 1})
        assert "5 RPMs" in result
        assert "3 logs" in result
        assert "1 SBOM" in result

    def test_format_artifact_counts_zero_values(self):
        """Test formatting artifact counts with zero values."""
        result = format_artifact_counts({"rpms": 5, "logs": 0})
        assert "5 RPMs" in result
        assert "log" not in result


class TestFileSizeFormatting:
    """Tests for file size formatting functions."""

    def test_format_file_size_zero(self):
        """Test formatting zero bytes."""
        assert format_file_size(0) == "0 B"

    def test_format_file_size_bytes(self):
        """Test formatting bytes."""
        assert format_file_size(500) == "500.0 B"

    def test_format_file_size_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_file_size(1024) == "1.0 KB"

    def test_format_file_size_megabytes(self):
        """Test formatting megabytes."""
        assert format_file_size(1024 * 1024) == "1.0 MB"

    def test_format_file_size_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_file_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_log_file_size(self, caplog, tmp_path):
        """Test logging file size."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        with caplog.at_level(logging.DEBUG):
            log_file_size(str(test_file), "TEST", len("test content"))
        assert "TEST" in caplog.text


class TestProgressLogging:
    """Tests for progress logging functions."""

    def test_log_progress_at_interval(self, caplog):
        """Test logging progress at interval."""
        with caplog.at_level(logging.INFO):
            log_progress(10, 100, "Processing", interval=10)
        assert "Processing: 10/100" in caplog.text

    def test_log_progress_not_at_interval(self, caplog):
        """Test not logging progress between intervals."""
        caplog.clear()
        with caplog.at_level(logging.INFO):
            log_progress(5, 100, "Processing", interval=10)
        # Should not log at position 5 when interval is 10

    def test_log_progress_at_completion(self, caplog):
        """Test logging progress at completion."""
        with caplog.at_level(logging.INFO):
            log_progress(100, 100, "Processing", interval=10)
        assert "Processing: 100/100" in caplog.text
        assert "100.0%" in caplog.text


class TestDisplayFormatting:
    """Tests for display formatting functions."""

    def test_log_summary_separator_no_title(self, caplog):
        """Test logging separator without title."""
        with caplog.at_level(logging.INFO):
            log_summary_separator()
        assert "=" * 80 in caplog.text

    def test_log_summary_separator_with_title(self, caplog):
        """Test logging separator with title."""
        with caplog.at_level(logging.INFO):
            log_summary_separator("Test Title")
        assert "=" * 80 in caplog.text
        assert "Test Title" in caplog.text

    def test_log_list_items(self, caplog):
        """Test logging list items."""
        items = ["item1", "item2", "item3"]
        with caplog.at_level(logging.INFO):
            log_list_items(items)

        assert "- item1" in caplog.text
        assert "- item2" in caplog.text
        assert "- item3" in caplog.text

    def test_log_list_items_custom_prefix(self, caplog):
        """Test logging list items with custom prefix."""
        items = ["item1", "item2"]
        with caplog.at_level(logging.INFO):
            log_list_items(items, prefix="* ")

        assert "* item1" in caplog.text
        assert "* item2" in caplog.text
