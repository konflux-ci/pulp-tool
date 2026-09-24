"""Ensure the Konflux container image ships ORAS and Konflux registry auth helpers."""

from pathlib import Path


def test_dockerfile_installs_oras() -> None:
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert "ORAS_VERSION" in dockerfile
    assert "/usr/local/bin/oras" in dockerfile
    assert "oras version" in dockerfile
    assert "select-oci-auth" in dockerfile
    assert "jq" in dockerfile
