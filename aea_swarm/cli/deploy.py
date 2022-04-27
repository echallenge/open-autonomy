# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Deploy CLI module."""

import os
import shutil
from pathlib import Path

import click

from aea_swarm.constants import PACKAGE_FOLDER
from aea_swarm.deploy.build import generate_deployment
from aea_swarm.deploy.generators.docker_compose.base import DockerComposeGenerator
from aea_swarm.deploy.generators.kubernetes.base import KubernetesGenerator


@click.group(name="deploy")
def deploy_group() -> None:
    """Deploy an AEA project."""


@deploy_group.command(name="build")
@click.argument(
    "deployment-file-path",
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
)
@click.argument("keys_file", type=str, required=True)
@click.option(
    "--o",
    "output_dir",
    type=click.Path(exists=False, dir_okay=True),
    default=Path.cwd(),
    help="Path to output dir.",
)
@click.option(
    "--docker",
    "deployment_type",
    flag_value=DockerComposeGenerator.deployment_type,
    default=True,
    help="Use docker as a backend.",
)
@click.option(
    "--kubernetes",
    "deployment_type",
    flag_value=KubernetesGenerator.deployment_type,
    help="Use docker as a kubernetes.",
)
@click.option(
    "--package-dir",
    type=click.Path(exists=False, dir_okay=True),
    default=Path.cwd() / PACKAGE_FOLDER,
    help="Path to packages folder (For local usage).",
)
@click.option(
    "--dev",
    "dev_mode",
    is_flag=True,
    default=False,
    help="Create development environment.",
)
@click.option(
    "--force",
    "force_overwrite",
    is_flag=True,
    default=False,
    help="Remove existing build and overwrite with new one.",
)
def build_deployment(
    deployment_file_path: Path,
    keys_file: Path,
    deployment_type: str,
    output_dir: Path,
    package_dir: Path,
    dev_mode: bool,  # pylint: disable=unused-argument
    force_overwrite: bool,
) -> None:
    """Build the agent and its components."""

    package_dir = Path(package_dir)
    build_dir = Path(output_dir, "abci_build")
    if build_dir.is_dir():
        if not force_overwrite:
            raise click.ClickException(f"Build already exists @ {output_dir}")
        shutil.rmtree(build_dir)

    build_dir.mkdir()
    _build_dirs(build_dir)

    try:
        report = generate_deployment(
            type_of_deployment=deployment_type,
            deployment_file_path=deployment_file_path,
            private_keys_file_path=keys_file,
            package_dir=package_dir,
            build_dir=build_dir,
        )
        click.echo(report)
    except ValueError as e:
        raise click.ClickException(str(e)) from e


def _build_dirs(build_dir: Path) -> None:
    """Build necessary directories."""

    for dir_path in [
        ("persistent_data",),
        ("persistent_data", "logs"),
        ("persistent_data", "dumps"),
    ]:
        path = Path(build_dir, *dir_path)
        path.mkdir()
        os.chown(path, 1000, 1000)
