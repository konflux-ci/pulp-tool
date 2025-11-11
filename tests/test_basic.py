"""
Basic tests for pulp-tool package.

This module contains basic tests to verify the package structure and imports.
"""

import pulp_tool


def test_package_import():
    """Test that the package can be imported."""
    assert pulp_tool is not None


def test_version():
    """Test that version is accessible."""
    assert hasattr(pulp_tool, "__version__")
    assert pulp_tool.__version__ is not None


def test_version_module():
    """Test that _version module can be imported and has correct version."""
    from pulp_tool._version import __version__

    assert __version__ == "1.0.0"


def test_main_classes_import():
    """Test that main classes can be imported."""
    from pulp_tool import PulpClient, PulpHelper

    assert PulpClient is not None
    assert PulpHelper is not None


def test_oauth_auth_import():
    """Test that OAuth authentication class can be imported."""
    from pulp_tool import OAuth2ClientCredentialsAuth

    assert OAuth2ClientCredentialsAuth is not None


def test_utility_functions_import():
    """Test that utility functions can be imported."""
    from pulp_tool import setup_logging, create_session_with_retry

    assert setup_logging is not None
    assert create_session_with_retry is not None
