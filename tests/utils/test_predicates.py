"""Tests for predicate functions."""

from pulp_tool.utils.predicates import (
    is_remote_url,
    has_required_certificates,
    is_artifact_type,
    file_exists_and_readable,
    is_empty_file,
    is_valid_build_id,
    should_use_config,
    is_successful_response,
    is_client_error,
    is_server_error,
)


class TestUrlPredicates:
    """Tests for URL predicate functions."""

    def test_is_remote_url_http(self):
        """Test identifying HTTP URLs."""
        assert is_remote_url("http://example.com/file") is True

    def test_is_remote_url_https(self):
        """Test identifying HTTPS URLs."""
        assert is_remote_url("https://example.com/file") is True

    def test_is_remote_url_local_path(self):
        """Test identifying local paths."""
        assert is_remote_url("/local/path/file") is False

    def test_is_remote_url_relative_path(self):
        """Test identifying relative paths."""
        assert is_remote_url("relative/path/file") is False


class TestCertificatePredicates:
    """Tests for certificate predicate functions."""

    def test_has_required_certificates_both_present(self):
        """Test when both certificate paths are provided."""
        assert has_required_certificates("/path/cert", "/path/key") is True

    def test_has_required_certificates_cert_missing(self):
        """Test when certificate path is missing."""
        assert has_required_certificates(None, "/path/key") is False

    def test_has_required_certificates_key_missing(self):
        """Test when key path is missing."""
        assert has_required_certificates("/path/cert", None) is False

    def test_has_required_certificates_both_missing(self):
        """Test when both paths are missing."""
        assert has_required_certificates(None, None) is False


class TestArtifactPredicates:
    """Tests for artifact type predicate functions."""

    def test_is_artifact_type_rpm(self):
        """Test identifying RPM artifacts."""
        assert is_artifact_type("package.rpm", "rpm") is True
        assert is_artifact_type("package.RPM", "rpm") is True

    def test_is_artifact_type_log(self):
        """Test identifying log artifacts."""
        assert is_artifact_type("build.log", "log") is True
        assert is_artifact_type("build.LOG", "log") is True

    def test_is_artifact_type_sbom(self):
        """Test identifying SBOM artifacts."""
        assert is_artifact_type("sbom.json", "sbom") is True
        assert is_artifact_type("package.SBOM", "sbom") is True

    def test_is_artifact_type_mismatch(self):
        """Test artifact type mismatch."""
        assert is_artifact_type("package.rpm", "log") is False

    def test_is_artifact_type_invalid_type(self):
        """Test invalid artifact type."""
        assert is_artifact_type("file.txt", "invalid") is False


class TestFilePredicates:
    """Tests for file predicate functions."""

    def test_file_exists_and_readable(self, tmp_path):
        """Test checking if file exists and is readable."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        assert file_exists_and_readable(str(test_file)) is True

    def test_file_not_exists(self):
        """Test checking non-existent file."""
        assert file_exists_and_readable("/nonexistent/file.txt") is False

    def test_is_empty_file(self, tmp_path):
        """Test checking if file is empty."""
        empty_file = tmp_path / "empty.txt"
        empty_file.touch()

        assert is_empty_file(str(empty_file)) is True

    def test_is_not_empty_file(self, tmp_path):
        """Test checking if file is not empty."""
        non_empty_file = tmp_path / "content.txt"
        non_empty_file.write_text("content")

        assert is_empty_file(str(non_empty_file)) is False

    def test_is_empty_file_nonexistent(self):
        """Test checking empty file on non-existent file."""
        # Treat inaccessible files as empty
        assert is_empty_file("/nonexistent/file.txt") is True


class TestBuildIdPredicates:
    """Tests for build ID predicate functions."""

    def test_is_valid_build_id_valid(self):
        """Test valid build ID."""
        assert is_valid_build_id("my-build-123") is True

    def test_is_valid_build_id_empty(self):
        """Test empty build ID."""
        assert is_valid_build_id("") is False

    def test_is_valid_build_id_whitespace(self):
        """Test whitespace-only build ID."""
        assert is_valid_build_id("   ") is False

    def test_is_valid_build_id_none(self):
        """Test None build ID."""
        assert is_valid_build_id(None) is False

    def test_is_valid_build_id_not_string(self):
        """Test non-string build ID."""
        assert is_valid_build_id(123) is False


class TestConfigPredicates:
    """Tests for config predicate functions."""

    def test_should_use_config_present(self):
        """Test when config is provided."""
        assert should_use_config("/path/to/config") is True

    def test_should_use_config_none(self):
        """Test when config is None."""
        assert should_use_config(None) is False


class TestHttpStatusPredicates:
    """Tests for HTTP status code predicate functions."""

    def test_is_successful_response_200(self):
        """Test identifying 200 OK as successful."""
        assert is_successful_response(200) is True

    def test_is_successful_response_299(self):
        """Test identifying 299 as successful."""
        assert is_successful_response(299) is True

    def test_is_successful_response_300(self):
        """Test identifying 300 as not successful."""
        assert is_successful_response(300) is False

    def test_is_successful_response_400(self):
        """Test identifying 400 as not successful."""
        assert is_successful_response(400) is False

    def test_is_client_error_400(self):
        """Test identifying 400 as client error."""
        assert is_client_error(400) is True

    def test_is_client_error_404(self):
        """Test identifying 404 as client error."""
        assert is_client_error(404) is True

    def test_is_client_error_499(self):
        """Test identifying 499 as client error."""
        assert is_client_error(499) is True

    def test_is_client_error_500(self):
        """Test identifying 500 as not client error."""
        assert is_client_error(500) is False

    def test_is_server_error_500(self):
        """Test identifying 500 as server error."""
        assert is_server_error(500) is True

    def test_is_server_error_503(self):
        """Test identifying 503 as server error."""
        assert is_server_error(503) is True

    def test_is_server_error_599(self):
        """Test identifying 599 as server error."""
        assert is_server_error(599) is True

    def test_is_server_error_400(self):
        """Test identifying 400 as not server error."""
        assert is_server_error(400) is False
