"""
Test fixtures and mock data for pulp-tool tests.

This module provides common fixtures, mock data, and utilities
for testing the pulp-tool package.

Best Practices for Temporary Files in Tests:
1. Always use fixtures from this file (temp_file, temp_rpm_file, temp_dir, temp_config)
2. If creating files manually, always use try/finally for cleanup
3. Prefer pytest's tmp_path fixture for test-specific temp directories
4. The temp_file_tracker fixture automatically ensures cleanup of all temp files
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
import httpx
import respx

# Global registry to track temporary files for cleanup
_temp_file_registry = set()


@pytest.fixture(scope="session", autouse=True)
def temp_file_cleanup():
    """
    Session-scoped fixture that ensures all temporary files are cleaned up.

    This fixture runs automatically for every test session and performs
    cleanup at the end. It serves as a safety net for any temp files that
    weren't properly cleaned up in individual tests.
    """
    yield

    # Cleanup any files in the registry
    for temp_path in _temp_file_registry:
        try:
            if Path(temp_path).exists():
                Path(temp_path).unlink()
        except Exception:
            pass  # Best effort cleanup

    _temp_file_registry.clear()


def register_temp_file(path: str) -> str:
    """
    Register a temporary file for automatic cleanup.

    Args:
        path: Path to temporary file

    Returns:
        The same path (for convenience)

    Example:
        temp_path = register_temp_file(tempfile.mktemp())
    """
    _temp_file_registry.add(path)
    return path


def unregister_temp_file(path: str) -> None:
    """
    Unregister a temporary file (already cleaned up manually).

    Args:
        path: Path to temporary file
    """
    _temp_file_registry.discard(path)


@pytest.fixture
def mock_config():
    """Mock Pulp configuration."""
    return {
        "base_url": "https://pulp.example.com",
        "api_root": "/pulp/api/v3",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "domain": "test-domain",
        "cert": "/path/to/cert.pem",
        "key": "/path/to/key.pem",
    }


@pytest.fixture
def httpx_mock():
    """Provide respx mock for HTTP mocking."""
    with respx.mock:
        yield respx


@pytest.fixture
def mock_pulp_client(mock_config, httpx_mock):
    """Mock PulpClient instance with respx."""
    from pulp_tool.api import PulpClient

    client = PulpClient(mock_config)
    # Use real client instead of mock
    return client


@pytest.fixture
def mock_oauth_auth():
    """Mock OAuth2ClientCredentialsAuth instance."""
    from pulp_tool.api import OAuth2ClientCredentialsAuth

    auth = OAuth2ClientCredentialsAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
        token_url="https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
    )
    auth._access_token = "mock-access-token"
    auth._expire_at = None
    return auth


@pytest.fixture
def mock_response():
    """Mock httpx Response object."""
    response = Mock(spec=httpx.Response)
    response.status_code = 200
    response.text = "OK"
    response.json = lambda: {"status": "success"}
    response.headers = httpx.Headers({"content-type": "application/json"})
    response.url = httpx.URL("https://pulp.example.com/api/v3/test")
    response.request = Mock(spec=httpx.Request)
    response.request.method = "GET"
    # Add httpx-specific attributes
    response.is_success = True
    response.is_error = False
    # For compatibility, add 'ok' attribute (similar to requests)
    response.ok = response.status_code < 400
    return response


@pytest.fixture
def mock_error_response():
    """Mock error httpx Response object."""
    response = Mock(spec=httpx.Response)
    response.status_code = 500
    response.text = "Internal Server Error"
    response.json = lambda: {"error": "Internal Server Error"}
    response.headers = httpx.Headers({"content-type": "application/json"})
    response.url = httpx.URL("https://pulp.example.com/api/v3/test")
    response.request = Mock(spec=httpx.Request)
    response.request.method = "GET"
    response.request.headers = httpx.Headers({})  # Add headers to request
    response.request.content = b'{"test": "data"}'  # Add content to request
    # Add httpx-specific attributes
    response.is_success = False
    response.is_error = True
    # For compatibility, add 'ok' attribute (similar to requests)
    response.ok = response.status_code < 400
    return response


@pytest.fixture
def mock_task_response():
    """Mock task response from Pulp API."""
    return {
        "pulp_href": "/pulp/api/v3/tasks/12345/",
        "state": "completed",
        "result": {"relative_path": "test-build/sbom/test-sbom.json"},
        "created_resources": ["/pulp/api/v3/content/file/files/67890/"],
    }


@pytest.fixture
def mock_repository_data():
    """Mock repository data from Pulp API."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/repositories/rpm/rpm/12345/",
                "prn": "pulp:///api/v3/repositories/rpm/rpm/12345/",
                "name": "test-build/rpms",
            }
        ]
    }


@pytest.fixture
def mock_distribution_data():
    """Mock distribution data from Pulp API."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/distributions/rpm/rpm/12345/",
                "name": "test-build/rpms",
                "base_path": "test-build/rpms",
            }
        ]
    }


@pytest.fixture
def mock_content_data():
    """Mock content data from Pulp API."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/content/rpm/packages/12345/",
                "artifacts": {"test-build-123/x86_64/test-package.rpm": "/pulp/api/v3/artifacts/67890/"},
                "relative_path": "test-build-123/x86_64/test-package.rpm",
                "pulp_labels": {"build_id": "test-build-123", "arch": "x86_64", "namespace": "test-namespace"},
            }
        ]
    }


@pytest.fixture
def mock_artifact_data():
    """Mock artifact data from Pulp API."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/artifacts/67890/",
                "file": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                "sha256": "abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            }
        ]
    }


@pytest.fixture
def mock_rpm_data():
    """Mock RPM package data from Pulp API."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/content/rpm/packages/12345/",
                "name": "test-package",
                "version": "1.0.0",
                "release": "1",
                "arch": "x86_64",
                "sha256": "abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            }
        ]
    }


@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        f.write("test content")
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def temp_rpm_file():
    """Create a temporary RPM file for testing."""
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".rpm") as f:
        f.write(b"fake rpm content")
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    import shutil

    temp_path = tempfile.mkdtemp()

    yield temp_path

    # Cleanup
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def temp_config_file(mock_config):
    """Create a temporary TOML config file."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".toml") as f:
        # Write valid TOML format
        f.write("[cli]\n")
        for key, value in mock_config.items():
            if isinstance(value, str):
                f.write(f'{key} = "{value}"\n')
            else:
                f.write(f"{key} = {value}\n")
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def temp_files(tmp_path):
    """
    Fixture providing a cleaner way to create temporary files.

    Uses pytest's tmp_path which automatically cleans up after the test.

    Usage:
        def test_something(temp_files):
            config_file = temp_files / "config.toml"
            config_file.write_text('[cli]\\nbase_url = "http://example.com"')

            data_file = temp_files / "data.json"
            data_file.write_text('{"key": "value"}')

    Returns:
        pathlib.Path: Temporary directory that will be cleaned up automatically
    """
    return tmp_path


@pytest.fixture
def create_temp_file(tmp_path):
    """
    Factory fixture for creating multiple temporary files in a test.

    Usage:
        def test_something(create_temp_file):
            file1 = create_temp_file("config.toml", '[cli]\\nbase_url = "test"')
            file2 = create_temp_file("data.json", '{"test": true}', binary=True)

    Returns:
        Callable: Function to create temp files
    """

    def _create(filename: str, content: str = "", binary: bool = False):
        """Create a temporary file with content."""
        file_path = tmp_path / filename
        if binary:
            file_path.write_bytes(content if isinstance(content, bytes) else content.encode())
        else:
            file_path.write_text(content)
        return file_path

    return _create


@pytest.fixture
def mock_args():
    """Mock command line arguments."""
    args = Mock()
    args.rpm_path = "/path/to/rpms"
    args.sbom_path = "/path/to/sbom.json"
    args.build_id = "test-build-123"
    args.namespace = "test-namespace"
    args.parent_package = "test-package"
    args.config = "/path/to/config.toml"
    args.cert_config = "/path/to/cert-config.toml"
    args.artifact_results = None
    args.debug = False
    args.artifact_location = "/path/to/artifacts.json"
    args.cert_path = "/path/to/cert.pem"
    args.key_path = "/path/to/key.pem"
    args.max_workers = 10
    return args


@pytest.fixture
def mock_artifacts_json():
    """Mock artifacts JSON data."""
    return {
        "artifacts": {
            "test-package-1.0.0-1.x86_64.rpm": {
                "labels": {"build_id": "test-build-123", "arch": "x86_64", "namespace": "test-namespace"}
            },
            "test-sbom.json": {
                "labels": {"build_id": "test-build-123", "arch": "noarch", "namespace": "test-namespace"}
            },
        },
        "distributions": {
            "rpms": "https://pulp.example.com/pulp/content/test-build/rpms/",
            "logs": "https://pulp.example.com/pulp/content/test-build/logs/",
            "sbom": "https://pulp.example.com/pulp/content/test-build/sbom/",
        },
    }


@pytest.fixture
def mock_repositories():
    """Mock repository information."""
    return {
        "rpms_prn": "pulp:///api/v3/repositories/rpm/rpm/12345/",
        "rpms_href": "/pulp/api/v3/repositories/rpm/rpm/12345/",
        "logs_prn": "pulp:///api/v3/repositories/file/file/12346/",
        "sbom_prn": "pulp:///api/v3/repositories/file/file/12347/",
        "artifacts_prn": "pulp:///api/v3/repositories/file/file/12348/",
    }


@pytest.fixture
def mock_distribution_urls():
    """Mock distribution URLs."""
    return {
        "rpms": "https://pulp.example.com/pulp/content/test-build/rpms/",
        "logs": "https://pulp.example.com/pulp/content/test-build/logs/",
        "sbom": "https://pulp.example.com/pulp/content/test-build/sbom/",
        "artifacts": "https://pulp.example.com/pulp/content/test-build/artifacts/",
    }


@pytest.fixture
def mock_upload_info():
    """Mock upload information."""
    return {
        "build_id": "test-build-123",
        "repositories": {
            "rpms_prn": "pulp:///api/v3/repositories/rpm/rpm/12345/",
            "logs_prn": "pulp:///api/v3/repositories/file/file/12346/",
        },
        "uploaded_counts": {"sboms": 1, "logs": 2, "rpms": 5},
        "upload_errors": [],
    }


@pytest.fixture
def mock_pulled_artifacts():
    """Mock pulled artifacts data."""
    from pulp_tool.models.artifacts import PulledArtifacts

    artifacts = PulledArtifacts()
    artifacts.add_sbom(
        "test-sbom.json",
        "/tmp/test-sbom.json",
        {"build_id": "test-build-123", "arch": "noarch", "namespace": "test-namespace"},
    )
    artifacts.add_log(
        "test.log", "/tmp/test.log", {"build_id": "test-build-123", "arch": "x86_64", "namespace": "test-namespace"}
    )
    artifacts.add_rpm(
        "test-package-1.0.0-1.x86_64.rpm",
        "/tmp/test-package-1.0.0-1.x86_64.rpm",
        {"build_id": "test-build-123", "arch": "x86_64", "namespace": "test-namespace"},
    )
    return artifacts


@pytest.fixture
def mock_file_locations():
    """Mock file locations data."""
    return {
        "results": [
            {
                "pulp_href": "/pulp/api/v3/artifacts/67890/",
                "file": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                "sha256": "abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            }
        ]
    }


@pytest.fixture
def mock_results_structure():
    """Mock results structure."""
    return {
        "artifacts": {
            "test-package-1.0.0-1.x86_64.rpm": {
                "labels": {"build_id": "test-build-123", "arch": "x86_64", "namespace": "test-namespace"},
                "url": "https://pulp.example.com/pulp/content/test-build/rpms/test-package.rpm",
                "sha256": "abcd1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            }
        },
        "distributions": {
            "rpms": "https://pulp.example.com/pulp/content/test-build/rpms/",
            "logs": "https://pulp.example.com/pulp/content/test-build/logs/",
            "sbom": "https://pulp.example.com/pulp/content/test-build/sbom/",
        },
    }


class MockClient:
    """Mock httpx client for testing."""

    def __init__(self):
        self.get_calls = []
        self.post_calls = []
        self.patch_calls = []
        self.put_calls = []
        self.delete_calls = []
        self.close_called = False

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        response = Mock(spec=httpx.Response)
        response.status_code = 200
        response.json = lambda: {"status": "success"}
        response.text = "OK"
        response.headers = httpx.Headers({})
        response.url = httpx.URL(url)
        response.request = Mock(spec=httpx.Request)
        response.request.method = "GET"
        return response

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = Mock(spec=httpx.Response)
        response.status_code = 201
        response.json = lambda: {"status": "created"}
        response.text = "Created"
        response.headers = httpx.Headers({})
        response.url = httpx.URL(url)
        response.request = Mock(spec=httpx.Request)
        response.request.method = "POST"
        return response

    def patch(self, url, **kwargs):
        self.patch_calls.append((url, kwargs))
        response = Mock(spec=httpx.Response)
        response.status_code = 200
        response.json = lambda: {"status": "updated"}
        response.text = "OK"
        response.headers = httpx.Headers({})
        response.url = httpx.URL(url)
        response.request = Mock(spec=httpx.Request)
        response.request.method = "PATCH"
        return response

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        response = Mock(spec=httpx.Response)
        response.status_code = 200
        response.json = lambda: {"status": "updated"}
        response.text = "OK"
        response.headers = httpx.Headers({})
        response.url = httpx.URL(url)
        response.request = Mock(spec=httpx.Request)
        response.request.method = "PUT"
        return response

    def delete(self, url, **kwargs):
        self.delete_calls.append((url, kwargs))
        response = Mock(spec=httpx.Response)
        response.status_code = 204
        response.text = ""
        response.headers = httpx.Headers({})
        response.url = httpx.URL(url)
        response.request = Mock(spec=httpx.Request)
        response.request.method = "DELETE"
        return response

    def close(self):
        self.close_called = True


@pytest.fixture
def mock_client():
    """Mock httpx client."""
    return MockClient()


@pytest.fixture
def mock_thread_pool_executor():
    """Mock ThreadPoolExecutor."""
    executor = Mock()
    executor.submit = Mock()
    executor.__enter__ = Mock(return_value=executor)
    executor.__exit__ = Mock(return_value=None)
    return executor


@pytest.fixture
def mock_future():
    """Mock Future object."""
    future = Mock()
    future.result = Mock(return_value="test-result")
    return future


@pytest.fixture
def mock_as_completed():
    """Mock as_completed function."""

    def mock_as_completed_func(futures):
        for future in futures:
            yield future

    return mock_as_completed_func
