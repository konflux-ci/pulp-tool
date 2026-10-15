"""
Central constants for the Konflux Pulp package.

This module consolidates all constants used throughout the codebase
to eliminate magic numbers and strings.
"""

# ============================================================================
# Repository and Content Types
# ============================================================================

# Repository types supported by Pulp
REPOSITORY_TYPES = ["rpms", "logs", "sbom", "artifacts"]

# Signed repository types (when --signed-by is used; only RPMs are signed)
SIGNED_REPOSITORY_TYPES = ["rpms-signed"]

# Supported CPU architectures (including source RPMs as a logical 'src' arch)
SUPPORTED_ARCHITECTURES = ["x86_64", "i686", "aarch64", "s390x", "ppc64le", "noarch", "src", "ppc64"]

# Content types for filtering
CONTENT_TYPES = ["rpm", "log", "sbom"]

# Artifact types in iteration order
ARTIFACT_TYPES = ["rpms", "sboms", "logs"]

# ============================================================================
# File and Path Constants
# ============================================================================

# Results JSON filename for upload artifacts
RESULTS_JSON_FILENAME = "pulp_results.json"

# Key prefix for per-arch RPM distribution base URLs in pulp_results.json ``distributions`` (e.g. rpm_x86_64)
RESULTS_JSON_RPM_ARCH_DISTRIBUTION_KEY_PREFIX = "rpm_"


def results_json_rpm_arch_distribution_key(arch: str) -> str:
    """Return the ``distributions`` map key for a per-arch RPM base URL in pulp_results.json."""
    return f"{RESULTS_JSON_RPM_ARCH_DISTRIBUTION_KEY_PREFIX}{arch.strip()}"


# Minimum file size (bytes) - 0 means file must not be empty
MIN_FILE_SIZE = 0

# File extensions for SBOM files
SBOM_EXTENSIONS = [".json", ".spdx", ".spdx.json"]

# ============================================================================
# API and Network Constants
# ============================================================================

# Default timeout for HTTP requests (seconds)
# Increased to 120 seconds to handle slow operations like bulk content queries
DEFAULT_TIMEOUT = 120

# Timeout for multipart content uploads (RPMs, logs, SBOM files) — large debuginfo RPMs
# can exceed the default API timeout when uploading over slow links
UPLOAD_CONTENT_TIMEOUT = 1800

# Minimum artifact size covered by e2e large-upload tests (production debuginfo scale).
LARGE_UPLOAD_MIN_SIZE_MB = 300
LARGE_UPLOAD_MIN_SIZE_BYTES = LARGE_UPLOAD_MIN_SIZE_MB * 1024 * 1024

# Default cap per distribution download (2 GiB; override with PULP_TOOL_MAX_DOWNLOAD_BYTES).
# Source-built SDK RPMs can exceed 900 MiB.
DEFAULT_MAX_ARTIFACT_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024

# Cache TTL (time-to-live) in seconds for GET request caching
CACHE_TTL = 300  # 5 minutes

# Default number of concurrent workers for parallel operations
DEFAULT_MAX_WORKERS = 4

# Maximum workers for repository setup operations
REPOSITORY_SETUP_MAX_WORKERS = 4

API_TYPES = ["rpm", "file"]

# ============================================================================
# Task Management Constants
# ============================================================================

# Initial interval between task status checks (seconds)
TASK_INITIAL_SLEEP_INTERVAL = 2

# Maximum interval between task status checks (seconds)
TASK_MAX_SLEEP_INTERVAL = 30

# Exponential backoff multiplier for task polling
TASK_BACKOFF_MULTIPLIER = 1.5

# Default timeout for Pulp async tasks (seconds) - 24 hours
DEFAULT_TASK_TIMEOUT = 86400

# ============================================================================
# Logging and Display Constants
# ============================================================================

# Maximum log line length (characters)
# Set to 114 to fit standard terminal width (120) minus prefix/margin
MAX_LOG_LINE_LENGTH = 114

# Width for separator lines in console output
SEPARATOR_WIDTH = 80

# Default logging progress interval (log every N items)
DEFAULT_PROGRESS_INTERVAL = 10

# ============================================================================
# Thread and Process Constants
# ============================================================================

# Thread name prefix for architecture processing
ARCHITECTURE_THREAD_PREFIX = "process_architectures"

# Chunk size for parallel GET requests with large parameter lists
# Prevents "Request Line is too large" errors
DEFAULT_CHUNK_SIZE = 50

# ============================================================================
# Exit Codes
# ============================================================================

# Standard exit codes for CLI commands
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_PARTIAL_SUCCESS = 2  # Some operations succeeded, some failed
EXIT_USER_INTERRUPT = 130  # User pressed Ctrl+C

# ============================================================================
# OAuth2 Configuration
# ============================================================================

# Red Hat SSO token URL for OAuth2 authentication
RED_HAT_SSO_TOKEN_URL = "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token"  # nosec B105  # noqa: S105

# ============================================================================
# Default Paths
# ============================================================================

# Default Pulp CLI configuration file path
DEFAULT_CONFIG_PATH = "~/.config/pulp/cli.toml"

# ============================================================================
# Validation Constants
# ============================================================================

# Invalid characters for repository naming
INVALID_REPO_CHARS = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]

# Default build ID fallback when none can be determined
DEFAULT_BUILD_ID = "rok-storage"

# Message when architecture cannot be detected for an RPM/file (use with os.path.basename for %s)
ARCH_DETECT_WARNING_MSG = "Skipping %s: Could not detect architecture. Use --arch to specify explicitly."

# ============================================================================
# HTTP Status Code Groups
# ============================================================================

# Client error status codes (4xx)
HTTP_CLIENT_ERROR_MIN = 400
HTTP_CLIENT_ERROR_MAX = 499

# Server error status codes (5xx)
HTTP_SERVER_ERROR_MIN = 500
HTTP_SERVER_ERROR_MAX = 599

# Specific status codes for special handling
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_FORBIDDEN = 403
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_SERVER_ERROR = 500

# ============================================================================
# URL Patterns
# ============================================================================

# URL schemes that indicate remote resources
REMOTE_URL_SCHEMES = ("http://", "https://")

# API path components
API_VERSION_PATH = "/pulp/api/v3"
PULP_CONTENT_PATH = "/api/pulp-content"

# ============================================================================
# File Size Units
# ============================================================================

# Units for file size formatting
FILE_SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]

# Bytes per kilobyte (used for size conversions)
BYTES_PER_KB = 1024


__all__ = [
    # Repository and Content
    "REPOSITORY_TYPES",
    "SIGNED_REPOSITORY_TYPES",
    "SUPPORTED_ARCHITECTURES",
    "CONTENT_TYPES",
    "ARTIFACT_TYPES",
    # File and Path
    "RESULTS_JSON_FILENAME",
    "RESULTS_JSON_RPM_ARCH_DISTRIBUTION_KEY_PREFIX",
    "results_json_rpm_arch_distribution_key",
    "MIN_FILE_SIZE",
    "SBOM_EXTENSIONS",
    # API and Network
    "DEFAULT_TIMEOUT",
    "UPLOAD_CONTENT_TIMEOUT",
    "LARGE_UPLOAD_MIN_SIZE_MB",
    "LARGE_UPLOAD_MIN_SIZE_BYTES",
    "CACHE_TTL",
    "DEFAULT_MAX_WORKERS",
    "REPOSITORY_SETUP_MAX_WORKERS",
    # Task Management
    "TASK_INITIAL_SLEEP_INTERVAL",
    "TASK_MAX_SLEEP_INTERVAL",
    "TASK_BACKOFF_MULTIPLIER",
    "DEFAULT_TASK_TIMEOUT",
    # Logging and Display
    "MAX_LOG_LINE_LENGTH",
    "SEPARATOR_WIDTH",
    "DEFAULT_PROGRESS_INTERVAL",
    # Thread and Process
    "ARCHITECTURE_THREAD_PREFIX",
    "DEFAULT_CHUNK_SIZE",
    # Exit Codes
    "EXIT_SUCCESS",
    "EXIT_GENERAL_ERROR",
    "EXIT_PARTIAL_SUCCESS",
    "EXIT_USER_INTERRUPT",
    # OAuth2
    "RED_HAT_SSO_TOKEN_URL",
    # Default Paths
    "DEFAULT_CONFIG_PATH",
    # Validation
    "INVALID_REPO_CHARS",
    "DEFAULT_BUILD_ID",
    "ARCH_DETECT_WARNING_MSG",
    # HTTP Status Codes
    "HTTP_CLIENT_ERROR_MIN",
    "HTTP_CLIENT_ERROR_MAX",
    "HTTP_SERVER_ERROR_MIN",
    "HTTP_SERVER_ERROR_MAX",
    "HTTP_STATUS_UNAUTHORIZED",
    "HTTP_STATUS_FORBIDDEN",
    "HTTP_STATUS_NOT_FOUND",
    "HTTP_STATUS_SERVER_ERROR",
    # URL Patterns
    "REMOTE_URL_SCHEMES",
    "API_VERSION_PATH",
    "PULP_CONTENT_PATH",
    # File Size
    "FILE_SIZE_UNITS",
    "BYTES_PER_KB",
]
