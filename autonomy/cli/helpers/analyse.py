# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Helpers for analyse command"""

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union, cast

import click
from aea.components.base import load_aea_package
from aea.configurations.base import AgentConfig, PackageConfiguration, SkillConfig
from aea.configurations.constants import (
    DEFAULT_SKILL_CONFIG_FILE,
    PACKAGE_TYPE_TO_CONFIG_FILE,
)
from aea.configurations.data_types import (
    ComponentId,
    ComponentType,
    PackageId,
    PackageType,
)
from aea.configurations.loader import load_configuration_object
from aea.package_manager.v1 import PackageManagerV1
from aea_cli_ipfs.ipfs_utils import IPFSTool

from autonomy.analyse.dialogues import check_dialogues_in_a_skill_package
from autonomy.analyse.logs.base import (
    ENTER_ROUND_REGEX,
    EXIT_ROUND_REGEX,
    LOGS_DB,
    LogRow,
    TIME_FORMAT,
)
from autonomy.analyse.logs.collection import FromDirectory, LogCollection
from autonomy.analyse.logs.db import AgentLogsDB
from autonomy.analyse.service import ServiceAnalyser, ServiceValidationFailed
from autonomy.chain.config import ChainType
from autonomy.cli.helpers.chain import get_ledger_and_crypto_objects
from autonomy.cli.utils.click_utils import sys_path_patch
from autonomy.configurations.base import PACKAGE_TYPE_TO_CONFIG_CLASS, Service


def load_package_tree(packages_dir: Path) -> None:
    """Load package tree."""

    pm = PackageManagerV1.from_dir(packages_dir=packages_dir)

    for package_id in pm.iter_dependency_tree():
        if package_id.package_type in (PackageType.AGENT, PackageType.SERVICE):
            continue

        package_path = pm.package_path_from_package_id(package_id=package_id)
        config_obj = load_configuration_object(
            package_type=package_id.package_type, directory=package_path
        )
        config_obj.directory = package_path
        load_aea_package(configuration=config_obj)


def list_all_skill_yaml_files(registry_path: Path) -> List[Path]:
    """List all skill yaml files in a local registry"""
    return sorted(registry_path.glob(f"*/skills/*/{DEFAULT_SKILL_CONFIG_FILE}"))


def run_dialogues_check(
    packages_dir: Path,
    ignore: List[str],
    dialogues: List[str],
) -> None:
    """Run dialogues check."""

    try:
        with sys_path_patch(packages_dir.parent):
            load_package_tree(packages_dir=packages_dir)
            for yaml_file in list_all_skill_yaml_files(packages_dir):
                if yaml_file.parent.name in ignore:
                    click.echo(f"Skipping {yaml_file.parent.name}")
                    continue

                click.echo(f"Checking {yaml_file.parent.name}")
                check_dialogues_in_a_skill_package(
                    config_file=yaml_file,
                    dialogues=dialogues,
                )
    except (ValueError, FileNotFoundError, ImportError) as e:
        raise click.ClickException(str(e))


class ParseLogs:
    """Parse agent logs."""

    _dbs: Dict[str, AgentLogsDB]
    _collection: LogCollection
    _db_path: Path

    results: Dict[str, List[LogRow]]

    def __init__(self) -> None:
        """Initialize object."""

    @property
    def agents(self) -> List[str]:
        """Available agents."""

        return self._collection.agents

    def from_dir(self, logs_dir: Path) -> "ParseLogs":
        """From directory"""

        self._db_path = logs_dir / LOGS_DB
        self._collection = FromDirectory(directory=logs_dir)
        self._dbs = {
            agent: AgentLogsDB(agent=agent, file=self._db_path)
            for agent in self._collection.agents
        }

        return self

    def create_tables(self, reset: bool = False) -> "ParseLogs":
        """Create required tables."""

        for agent, db in self._dbs.items():
            db_exists = db.exists()
            if db_exists and not reset:
                continue

            self._collection.create_agent_db(
                agent=agent,
                db=db,
                reset=reset,
            )

        return self

    def select(  # pylint: disable=too-many-arguments
        self,
        agents: List[str],
        start_time: Optional[Union[str, datetime]],
        end_time: Optional[Union[str, datetime]],
        log_level: Optional[str],
        period: Optional[int],
        round_name: Optional[str],
        behaviour_name: Optional[str],
    ) -> "ParseLogs":
        """Query and return results."""

        if start_time is not None:
            start_time = datetime.strptime(cast(str, start_time), TIME_FORMAT)

        if end_time is not None:
            end_time = datetime.strptime(cast(str, end_time), TIME_FORMAT)

        results = {}
        for agent in agents:
            results[agent] = self._dbs[agent].select(
                start_time=start_time,
                end_time=end_time,
                log_level=log_level,
                period=period,
                round_name=round_name,
                behaviour_name=behaviour_name,
            )

        self.results = results
        return self

    def re_include(self, regexes: List[str]) -> "ParseLogs":
        """Apply a set of regexes on the result."""
        if len(regexes) == 0:
            return self

        compiled_re = [re.compile(pattern) for pattern in regexes]

        def _apply_filter(row: LogRow) -> bool:
            return any(map(lambda _re: _re.match(row[2]) is not None, compiled_re))

        for agent, logs in self.results.items():
            self.results[agent] = list(filter(_apply_filter, logs))

        return self

    def re_exclude(self, regexes: List[str]) -> "ParseLogs":
        """Apply a set of regexes on the result."""

        if len(regexes) == 0:
            return self

        compiled_re = [re.compile(pattern) for pattern in regexes]

        def _apply_filter(row: LogRow) -> bool:
            return any(map(lambda _re: _re.match(row[2]) is None, compiled_re))

        for agent, logs in self.results.items():
            self.results[agent] = list(filter(_apply_filter, logs))

        return self

    def execution_path(self) -> None:
        """Output FSM path"""
        for agent, logs in self.results.items():
            period = -1
            click.echo(f"Agent {agent}")
            for _, _, message, _, _, _ in logs:
                match = ENTER_ROUND_REGEX.match(message)
                if match is not None:
                    _, _period = cast(Tuple[str, int], match.groups())
                    if _period != period:
                        period = _period
                        click.echo(f"|_ Period {period}")

                match = EXIT_ROUND_REGEX.match(message)
                if match is not None:
                    round_name, exit_event = match.groups()
                    click.echo(f"| |_ {round_name} | {exit_event}")
            click.echo("|_ End\n")

    def table(self) -> None:
        """Print table."""

        for agent, logs in self.results.items():
            click.echo(f"--- {agent} ---")
            for timestamp, log_level, message, _, _, _ in logs:
                click.echo(f"[{timestamp}][{log_level}] {message}")
            click.echo("--- End ---")


def _get_content_from_ipfs(package_id: PackageId, file: str) -> bytes:
    """Read content from the IPFS registry."""
    try:
        ipfs_tool = IPFSTool()
        return ipfs_tool.client.cat(
            f"{package_id.package_hash}/{package_id.name}/{file}"
        )
    except Exception as e:
        raise click.ClickException(
            "Fetching content from the IPFS registry failed"
            f"\n\tPackage: {package_id}\n\tFile: {file}\n\tError: {e}"
        ) from e


def _load_from_ipfs(package_id: PackageId) -> PackageConfiguration:
    """Load agent config from the IPFS hash."""
    with tempfile.TemporaryDirectory() as package_dir:
        config_file = PACKAGE_TYPE_TO_CONFIG_FILE[package_id.package_type.value]
        config_content = _get_content_from_ipfs(package_id=package_id, file=config_file)
        Path(package_dir, config_file).write_bytes(config_content)
        return load_configuration_object(
            package_type=package_id.package_type,
            directory=Path(package_dir),
            package_type_config_class=PACKAGE_TYPE_TO_CONFIG_CLASS,
        )


def _load_from_local(
    package_id: PackageId, package_manager: PackageManagerV1
) -> PackageConfiguration:
    """Load from local repository."""

    return load_configuration_object(
        package_type=package_id.package_type,
        directory=package_manager.package_path_from_package_id(package_id=package_id),
        package_type_config_class=PACKAGE_TYPE_TO_CONFIG_CLASS,
    )


def _get_chained_abci_skill(
    agent_config: AgentConfig,
    package_manager: PackageManagerV1,
    is_on_chain_check: bool = False,
) -> Optional[SkillConfig]:
    """
    Get chained ABCI skill config

    This method cycles through the component overrides defined inside an agent package
    and tries to find out the chained ABCI app.

    :param agent_config: Agent configuration object.
    :param package_manager: Package manager.
    :param is_on_chain_check: A boolean flag to specify whether this is an on-chain
                            check or a local check
    :return: Skill configuration object if found
    """

    for skill_id in agent_config.skills:
        override = agent_config.component_configurations.get(
            ComponentId(component_type=ComponentType.SKILL, public_id=skill_id)
        )
        if override is None:
            continue

        package_id = PackageId(
            package_type=PackageType.SKILL,
            public_id=skill_id,
        )

        skill_config = cast(
            SkillConfig,
            (
                _load_from_ipfs(package_id=package_id)
                if is_on_chain_check
                else _load_from_local(
                    package_id=package_id, package_manager=package_manager
                )
            ),
        )

        # Check if the skill override has the `is_abstract` property set to true
        if override.get("is_abstract", False):
            continue

        # Check if the skill has the `is_abstract` property set to true
        if skill_config.is_abstract:
            continue

        # This statement makes an assumption skills other than the chained/main
        # abci are defined as abstract
        return skill_config

    return None


def _get_ipfs_pins(is_on_chain_check: bool = False) -> Set[str]:
    """Get IPFS pins."""
    ipfs_tool = IPFSTool()
    if is_on_chain_check:
        if not ipfs_tool.daemon.is_started():
            raise click.ClickException("Cannot connect to the IPFS daemon.")
        return ipfs_tool.all_pins()

    return set()


def _get_service_hash(service_id: PackageId, package_manager: PackageManagerV1) -> str:
    """Iterate through the available packages and find the hash for the service"""

    for package_id, package_hash in package_manager.dev_packages.items():
        if (
            package_id.package_type == PackageType.SERVICE
            and package_id.public_id.to_any() == service_id.public_id.to_any()
        ):
            return package_hash

    raise click.ClickException(
        f"Service with public id `{service_id.public_id}` not found"
    )


def check_service_readiness(
    token_id: Optional[int],
    service_id: PackageId,
    chain_type: ChainType,
    packages_dir: Path,
) -> None:
    """Check deployment readiness of a service."""

    package_manager = PackageManagerV1.from_dir(packages_dir=packages_dir)
    is_on_chain_check = token_id is not None
    ipfs_pins = _get_ipfs_pins(is_on_chain_check=is_on_chain_check)

    service_id = service_id.with_hash(
        package_hash=_get_service_hash(
            service_id=service_id,
            package_manager=package_manager,
        )
    )
    service_config = cast(
        Service,
        (
            _load_from_ipfs(package_id=service_id)
            if is_on_chain_check
            else _load_from_local(
                package_id=service_id, package_manager=package_manager
            )
        ),
    )

    agent_id = PackageId(
        package_type=PackageType.AGENT,
        public_id=service_config.agent,
    )
    agent_config = cast(
        AgentConfig,
        (
            _load_from_ipfs(package_id=agent_id)
            if is_on_chain_check
            else _load_from_local(package_id=agent_id, package_manager=package_manager)
        ),
    )

    skill_config = _get_chained_abci_skill(
        agent_config=agent_config,
        package_manager=package_manager,
        is_on_chain_check=is_on_chain_check,
    )

    if skill_config is None:
        raise click.ClickException(
            "Please make sure the agent package configuration contains overrides for the chained ABCI app"
        )

    try:
        service_analyser = ServiceAnalyser(
            service_config=service_config,
            is_on_chain_check=is_on_chain_check,
        )
        ledger_api, _ = get_ledger_and_crypto_objects(chain_type=chain_type)
        service_analyser.check_on_chain_state(
            ledger_api=ledger_api,
            chain_type=chain_type,
            token_id=cast(int, token_id),
        )
        service_analyser.validate_service_overrides()
        service_analyser.validate_agent_overrides(agent_config=agent_config)
        service_analyser.validate_skill_config(skill_config=skill_config)
        service_analyser.cross_verify_overrides(
            agent_config=agent_config, skill_config=skill_config
        )
        service_analyser.check_agent_dependencies_published(
            ipfs_pins=ipfs_pins, agent_config=agent_config
        )

        click.echo("Service is ready to be deployed.")
    except ServiceValidationFailed as e:
        raise click.ClickException(str(e)) from e
