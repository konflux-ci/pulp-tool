"""Tests that Click commands are registered via entry points."""

from importlib.metadata import entry_points
from unittest.mock import patch

import click
import pytest

from pulp_tool.cli import _ENTRYPOINT_GROUP, _register_entrypoint_commands, cli


def test_pulp_tool_commands_entrypoints_resolve() -> None:
    eps = list(entry_points(group=_ENTRYPOINT_GROUP))
    if not eps:
        pytest.skip("package metadata not installed; CLI uses built-in command fallback")
    names = {ep.name for ep in eps}
    assert names == {"upload-build", "upload", "upload_files", "pull", "search_by", "create_repository"}
    for ep in eps:
        cmd = ep.load()
        assert cmd.name is not None


def test_cli_has_all_subcommands() -> None:
    expected = {"upload-build", "upload", "upload-files", "pull", "search-by", "create-repository"}
    assert set(cli.commands.keys()) == expected


def test_register_entrypoint_commands_uses_metadata_when_eps_exist() -> None:
    """Covers ``pulp_tool.cli`` branch that loads from ``pulp_tool.commands`` entry points."""

    @click.command("ep-test-cmd")
    def ep_test_cmd() -> None:
        """Stub command."""

    class _Ep:
        name = "ep_test"

        def load(self) -> click.Command:
            return ep_test_cmd

    g = click.Group()
    with patch("pulp_tool.cli.entry_points", return_value=[_Ep()]):
        _register_entrypoint_commands(g)
    assert "ep-test-cmd" in g.commands


def test_register_entrypoint_commands_builtin_fallback_when_no_eps() -> None:
    """Covers editable / bare runs with no ``pulp_tool.commands`` dist-info entry points."""

    g = click.Group()
    with patch("pulp_tool.cli.entry_points", return_value=[]):
        _register_entrypoint_commands(g)
    assert set(g.commands.keys()) == {
        "upload-build",
        "upload",
        "upload-files",
        "pull",
        "search-by",
        "create-repository",
    }
