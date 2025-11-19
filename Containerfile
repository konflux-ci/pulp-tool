# Containerfile for pulp-tool
# Base image: Fedora 42
FROM registry.fedoraproject.org/fedora:42@sha256:b752f2bfd4fa730db7a1237fc0a42075a92017d1ba9783a93adf9337f51a870d

# Install Python 3 and pip
RUN dnf install -y python3 python3-pip && dnf clean all

# Set working directory
WORKDIR /app

# Copy project files needed for installation
COPY setup.py pyproject.toml README.md MANIFEST.in VERSION ./
COPY pulp_tool/ ./pulp_tool/

# Install pulp-tool and its runtime dependencies
RUN pip install --no-cache-dir .

# The pulp-tool command is now available in PATH
# No entrypoint specified - users can run commands as needed
