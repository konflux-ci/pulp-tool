"""Smoke tests for the upload package module."""


def test_upload_package_docstring_describes_cli_entry() -> None:
    import pulp_tool.upload as upload_pkg

    assert upload_pkg.__doc__ is not None
    assert "PulpHelper" in upload_pkg.__doc__
