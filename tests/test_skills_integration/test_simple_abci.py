# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021 Valory AG
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

"""Integration tests for the valory/simple_abci skill."""
import json
import logging
from pathlib import Path
from typing import List

from aea.test_tools.test_cases import AEATestCaseMany

from tests.helpers.tendermint_utils import (
    BaseTendermintTestClass,
    TendermintLocalNetworkBuilder,
)


# check log messages of the happy path
CHECK_STRINGS = (
    "Entered in the 'tendermint_healthcheck' behaviour state",
    "'tendermint_healthcheck' behaviour state is done",
    "Entered in the 'registration' round for period 0",
    "'registration' round is done",
    "Entered in the 'randomness_startup' round for period 0",
    "'randomness_startup' round is done",
    "Entered in the 'select_keeper_a_startup' round for period 0",
    "'select_keeper_a_startup' round is done",
    "Entered in the 'reset_and_pause' round for period 0",
    "'reset_and_pause' round is done",
    "Period end",
    "Entered in the 'randomness_startup' round for period 1",
    "Entered in the 'select_keeper_a_startup' round for period 1",
    "Entered in the 'reset_and_pause' round for period 1",
)


class BaseTestSimpleABCISkill(AEATestCaseMany, BaseTendermintTestClass):
    """
    Base class for Price estimation skill tests.

    The setup test function of this class will configure a set of 'n'
    agents with the simple_abci skill, and a Tendermint network
    of 'n' nodes, one for each agent.

    Test subclasses must set NB_AGENTS.
    """

    NB_AGENTS: int
    IS_LOCAL = True
    capture_log = True
    KEEPER_TIMEOUT = 10
    cli_log_options = ["-v", "DEBUG"]
    processes: List

    def setup(self) -> None:
        """Set up the test."""
        self.agent_names = [f"agent_{i:05d}" for i in range(self.NB_AGENTS)]
        self.processes = []
        self.create_agents(*self.agent_names, is_local=self.IS_LOCAL)
        self.tendermint_net_builder = TendermintLocalNetworkBuilder(
            self.NB_AGENTS, Path(self.t)
        )

        for agent_id, agent_name in enumerate(self.agent_names):
            logging.debug(f"Processing agent {agent_name}...")
            node = self.tendermint_net_builder.nodes[agent_id]
            self.set_agent_context(agent_name)
            self.generate_private_key("ethereum", "ethereum_private_key.txt")
            self.add_private_key("ethereum", "ethereum_private_key.txt")
            self.set_config("agent.default_ledger", "ethereum")
            self.set_config("agent.required_ledgers", '["ethereum"]', type_="list")
            self.add_item("skill", "valory/simple_abci:0.1.0", local=False)
            self.set_config(
                "vendor.valory.connections.abci.config.target_skill_id",
                "valory/simple_abci:0.1.0",
            )
            # each agent has its Tendermint node instance
            self.set_config(
                "vendor.valory.connections.abci.config.use_tendermint", True
            )
            self.set_config(
                "vendor.valory.connections.abci.config.tendermint_config.consensus_create_empty_blocks",
                True,
            )

            self.set_config(
                "vendor.valory.connections.abci.config.port",
                node.abci_port,
            )
            self.set_config(
                "vendor.valory.connections.abci.config.tendermint_config.rpc_laddr",
                node.rpc_laddr,
            )
            self.set_config(
                "vendor.valory.connections.abci.config.tendermint_config.p2p_laddr",
                node.p2p_laddr,
            )
            self.set_config(
                "vendor.valory.connections.abci.config.tendermint_config.home",
                str(node.home),
            )
            self.set_config(
                "vendor.valory.connections.abci.config.tendermint_config.p2p_seeds",
                json.dumps(self.tendermint_net_builder.get_p2p_seeds()),
                "list",
            )
            self.set_config(
                "vendor.valory.skills.simple_abci.models.params.args.consensus.max_participants",
                self.NB_AGENTS,
            )
            self.set_config(
                "vendor.valory.skills.simple_abci.models.params.args.round_timeout_seconds",
                self.KEEPER_TIMEOUT,
            )
            self.set_config(
                "vendor.valory.skills.simple_abci.models.params.args.tendermint_url",
                node.get_http_addr("localhost"),
            )

        # run 'aea install' in only one AEA project, to save time
        self.set_agent_context(self.agent_names[0])
        self.run_install()

    def _launch_agent_i(self, i: int) -> None:
        """Launch the i-th agent."""
        agent_name = self.agent_names[i]
        logging.debug(f"Launching agent {agent_name}...")
        self.set_agent_context(agent_name)
        process = self.run_agent()
        self.processes.append(process)


class BaseTestSimpleAbciSkillNormalExecution(BaseTestSimpleABCISkill):
    """Test that the ABCI simple skill works together with Tendermint under normal circumstances."""

    def test_run(self) -> None:
        """Run the ABCI skill."""
        for agent_id in range(self.NB_AGENTS):
            self._launch_agent_i(agent_id)

        logging.info("Waiting Tendermint nodes to be up")
        self.health_check(
            self.tendermint_net_builder, max_retries=20, sleep_interval=3.0
        )

        # check that *each* AEA prints these messages
        for process in self.processes:
            missing_strings = self.missing_from_output(process, CHECK_STRINGS, 40)
            assert (
                missing_strings == []
            ), "Strings {} didn't appear in agent output.".format(missing_strings)

            assert self.is_successfully_terminated(
                process
            ), "ABCI agent wasn't successfully terminated."


class TestABCIPriceEstimationSingleAgent(
    BaseTestSimpleAbciSkillNormalExecution,
    BaseTendermintTestClass,
):
    """Test that the ABCI simple_abci skill with only one agent."""

    NB_AGENTS = 1


class TestABCIPriceEstimationTwoAgents(
    BaseTestSimpleAbciSkillNormalExecution,
    BaseTendermintTestClass,
):
    """Test that the ABCI simple_abci skill with two agents."""

    NB_AGENTS = 2


class TestABCIPriceEstimationFourAgents(
    BaseTestSimpleAbciSkillNormalExecution,
    BaseTendermintTestClass,
):
    """Test that the ABCI simple_abci skill with four agents."""

    NB_AGENTS = 4
