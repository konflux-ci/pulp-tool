# Dockerfile for pulp-tool
# Base image: UBI 10 minimal (Python 3.12 in builder/runtime stages)
#
# Multi-stage layout: builder installs deps (network); runtime copies /app/install
# only so the final image has no uv/pip fetch steps and fewer microdnf packages.

# ORAS CLI + select-oci-auth (Konflux release-service-utils pattern).
FROM quay.io/konflux-ci/oras:latest@sha256:6cea0b9e142c2e18429f5cd30d716715d932047cbf1631334c5c31f7e47c3a19 AS oras

FROM registry.access.redhat.com/ubi10/ubi-minimal:10.2-1789645153 AS builder

ARG VERSION=1.0.0
ARG RELEASE=1

# Skip microdnf update — metadata refresh is a common Konflux failure point.
RUN microdnf install -y \
        python3 \
        python3-pip && \
    microdnf clean all && \
    pip3 install --no-cache-dir --root-user-action=ignore uv

WORKDIR /app

# Runtime install from uv.lock (regenerate with: make lock).
COPY pyproject.toml uv.lock README.md MANIFEST.in VERSION ./
COPY pulp_tool/ ./pulp_tool/

ENV UV_SYSTEM_PYTHON=1
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt && \
    pip3 install --no-cache-dir --root-user-action=ignore \
        --prefix=/app/install -r /tmp/requirements.txt && \
    SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" pip3 install --no-cache-dir --root-user-action=ignore \
        --prefix=/app/install --no-deps . && \
    rm -rf /root/.cache /root/.local /tmp/requirements.txt

FROM registry.access.redhat.com/ubi10/ubi-minimal:10.2-1789645153

# Konflux passes VERSION/RELEASE via build-args-file (.tekton/pulp-tool-container.build-args).
ARG VERSION=1.0.0
ARG RELEASE=1

LABEL name="pulp-tool-container" \
      description="Konflux container image for pulp-tool Pulp API client operations" \
      summary="pulp-tool container image for uploading RPMs and artifacts to Pulp" \
      maintainer="Rok Artifact Storage Team <jreidy@redhat.com>" \
      io.k8s.description="Konflux container image for pulp-tool Pulp API client operations" \
      com.redhat.component="pulp-tool-container" \
      distribution-scope="public" \
      release="${RELEASE}" \
      version="${VERSION}" \
      url="https://github.com/konflux-ci/pulp-tool/" \
      vendor="Red Hat, Inc."

# OpenShift preflight check requires licensing files under /licenses
COPY LICENSE /licenses/LICENSE

RUN microdnf install -y \
        python3 \
        shadow-utils && \
    microdnf clean all

COPY --from=oras /usr/bin/oras /usr/bin/oras
COPY --from=oras /usr/bin/yq /usr/bin/yq
COPY --from=oras /usr/local/bin/select-oci-auth /usr/local/bin/select-oci-auth
COPY --from=oras /usr/local/bin/get-reference-base /usr/local/bin/get-reference-base
RUN oras version && yq --version && test -x /usr/local/bin/select-oci-auth && test -x /usr/local/bin/get-reference-base

COPY --from=builder /app/install /app/install

ENV PATH="/app/install/bin:${PATH}" \
    PYTHONPATH="/app/install/lib64/python3.12/site-packages:/app/install/lib/python3.12/site-packages"

RUN useradd -lms /bin/bash -u 1001 -g 0 pulp-tool && \
    chown -R 1001:0 /app/install && \
    chmod -R g=u /app/install

USER 1001

# The pulp-tool command is available in PATH; no entrypoint — Tekton invokes it directly.
