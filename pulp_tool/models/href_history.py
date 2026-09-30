"""Shared href history row (``pulp_results.json`` artifact lineage)."""

from pydantic import BaseModel, ConfigDict

PULP_RESULTS_SCHEMA_VERSION = "1.0.0"
SIDE_TAG_TRANSFER_OPERATION = "transfer"


class HrefHistoryEntry(BaseModel):
    """One prior Pulp content href for an artifact."""

    model_config = ConfigDict(extra="ignore")

    href: str
    sha256: str = ""
    operation: str = SIDE_TAG_TRANSFER_OPERATION
    last_updated: str = ""
    schema_version: str = PULP_RESULTS_SCHEMA_VERSION
    signed_by: str = ""
