"""Ensure the Konflux container image ships ORAS and Konflux registry auth helpers."""

from pathlib import Path

ORAS_IMAGE = "quay.io/konflux-ci/oras"


def test_dockerfile_installs_oras() -> None:
    root = Path(__file__).resolve().parents[2]
    for name in ("Dockerfile", "Dockerfile.e2e"):
        dockerfile = (root / name).read_text(encoding="utf-8")
        assert ORAS_IMAGE in dockerfile
        assert "COPY --from=oras /usr/bin/oras" in dockerfile
        assert "COPY --from=oras /usr/bin/yq" in dockerfile
        assert "COPY --from=oras /usr/local/bin/select-oci-auth" in dockerfile
        assert "COPY --from=oras /usr/local/bin/get-reference-base" in dockerfile
        assert "oras version" in dockerfile
        assert "yq --version" in dockerfile
