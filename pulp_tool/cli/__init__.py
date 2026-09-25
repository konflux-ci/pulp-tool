"""
Unified CLI entry point for Pulp Tool operations using Click.

This module provides the main CLI group and shared options.
Subcommands are registered from ``[project.entry-points."pulp_tool.commands"]``
(pulp-cli–style plugin discovery) and attached to :func:`cli`.
"""

import sys
from collections.abc import Callable
from importlib.metadata import entry_points
from typing import Any, TypeVar

import click

from .._version import __version__
from ..exceptions import PulpToolConfigError, PulpToolHTTPError

F = TypeVar("F", bound=Callable[..., Any])

_ENTRYPOINT_GROUP = "pulp_tool.commands"


# ============================================================================
# Common Click Options - Reusable decorators for shared options
# ============================================================================


def config_option(required: bool = False) -> Callable[[F], F]:
    """Shared --config option for commands."""
    default_help = " (default: ~/.config/pulp/cli.toml)" if not required else ""
    return click.option(
        "--config",
        required=required,
        type=str,
        help=f"Path to Pulp CLI config file or base64-encoded config content{default_help}",
    )


def debug_option() -> Callable[[F], F]:
    """Shared --debug option for verbosity control."""
    return click.option(
        "-d",
        "--debug",
        count=True,
        help="Increase verbosity (use -d for INFO, -dd for DEBUG, -ddd for DEBUG with HTTP logs)",
    )


# ============================================================================
# CLI Group
# ============================================================================


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="pulp-tool")
@click.option(
    "--config",
    type=str,
    help="Path to Pulp CLI config file or base64-encoded config content (default: ~/.config/pulp/cli.toml)",
)
@click.option(
    "--build-id",
    help="Build identifier (required for some commands)",
)
@click.option(
    "--namespace",
    help="Namespace for the build (required for some commands)",
)
@click.option(
    "-d",
    "--debug",
    count=True,
    help="Increase verbosity (use -d for INFO, -dd for DEBUG, -ddd for DEBUG with HTTP logs)",
)
@click.option(
    "--max-workers",
    type=int,
    default=4,
    help="Maximum number of concurrent workers (default: 4)",
)
@click.pass_context
def cli(
    ctx: click.Context,
    config: str | None,
    build_id: str | None,
    namespace: str | None,
    debug: int,
    max_workers: int,
) -> None:
    """Pulp Tool - Upload and pull artifacts to/from Pulp repositories."""
    # Store shared options in context for subcommands to access
    ctx.ensure_object(dict)
    # Config can be a file path or base64-encoded content - pass directly to downstream code
    ctx.obj["config"] = config
    ctx.obj["build_id"] = build_id
    ctx.obj["namespace"] = namespace
    ctx.obj["debug"] = debug
    ctx.obj["max_workers"] = max_workers


def _register_entrypoint_commands(group: click.Group) -> None:
    """Load Click commands from ``pulp_tool.commands`` entry points."""
    eps = list(entry_points(group=_ENTRYPOINT_GROUP))
    if eps:
        for ep in sorted(eps, key=lambda e: e.name):
            group.add_command(ep.load())
        return
    # Editable runs without installed dist-info (e.g. bare pytest): register built-ins explicitly.
    from . import create_repository as create_repository_mod
    from . import pull as pull_mod
    from . import search_by as search_by_mod
    from . import upload as upload_mod
    from . import upload_build as upload_build_mod
    from . import upload_files as upload_files_mod

    group.add_command(upload_build_mod.upload_build)
    group.add_command(upload_mod.upload)
    group.add_command(upload_files_mod.upload_files)
    group.add_command(pull_mod.pull)
    group.add_command(search_by_mod.search_by)
    group.add_command(create_repository_mod.create_repository)


_register_entrypoint_commands(cli)


# ============================================================================
# Main Entry Point
# ============================================================================


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()  # pylint: disable=no-value-for-parameter  # Click handles parameters
    except KeyboardInterrupt:
        click.echo("\n\nOperation cancelled by user", err=True)
        sys.exit(130)
    except PulpToolConfigError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(2)
    except PulpToolHTTPError as exc:
        click.echo(f"Pulp API error: {exc}", err=True)
        sys.exit(3)


__all__ = ["cli", "main", "config_option", "debug_option", "_ENTRYPOINT_GROUP"]
