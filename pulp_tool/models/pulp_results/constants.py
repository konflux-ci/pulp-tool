"""Constants for ``pulp_results.json`` schema and operations."""

PULP_RESULTS_ORAS_MEDIA_TYPE = "application/vnd.pulp.results.v0"

# Top-level ``version`` is the JSON **schema** semver (bump only on format changes).
PULP_RESULTS_SCHEMA_VERSION = "1.0.0"

BUILD_UPLOAD_OPERATION = "build_upload"
BUILD_SIGN_OPERATION = "build_sign"
RELEASE_SIGN_OPERATION = "release_sign"
BTS_UPDATE_OPERATION = "bts_update"
SIDE_TAG_TRANSFER_OPERATION = "transfer"

__all__ = [
    "PULP_RESULTS_ORAS_MEDIA_TYPE",
    "PULP_RESULTS_SCHEMA_VERSION",
    "BUILD_UPLOAD_OPERATION",
    "BUILD_SIGN_OPERATION",
    "RELEASE_SIGN_OPERATION",
    "BTS_UPDATE_OPERATION",
    "SIDE_TAG_TRANSFER_OPERATION",
]
