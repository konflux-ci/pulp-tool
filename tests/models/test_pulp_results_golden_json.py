"""Golden JSON export for ``PulpResultsDocument.to_canonical_json``."""

import json
from pathlib import Path

from pulp_tool.models.artifacts import ArtifactMetadata
from pulp_tool.models.pulp_results import PulpResultsDocument

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "pulp_results_golden.json"


def test_to_canonical_json_matches_golden_fixture() -> None:
    doc = PulpResultsDocument(
        version="1.0.0",
        last_updated="2026-04-01",
        build_id="golden-build",
        namespace="golden-ns",
        cluster="c1",
        artifacts={
            "pkg.rpm": ArtifactMetadata(
                pulp_labels={"arch": "x86_64", "build_id": "golden-build"},
                url="https://example.com/pkg.rpm",
                sha256="deadbeef",
                href="/pulp/content/pkg/",
                distributions={"rpms": "https://example.com/rpms/"},
            )
        },
        distributions={"rpms": "https://example.com/rpms/"},
    )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = json.loads(doc.to_canonical_json(namespace="golden-ns", cluster="c1"))
    assert actual == expected
