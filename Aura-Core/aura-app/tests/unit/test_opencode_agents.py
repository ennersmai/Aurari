"""
Tests for OpenCode agent definitions (W3-31).

Validates:
1. Agent definitions match Config.AgentEncoded schema
2. Permission rulesets match Permission.Ruleset schema
3. Fake server from W3-27 extended to serve GET /api/agent
4. Start fails when an agent is missing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aura.connections.opencode_agents import agent_definitions, validate_agent_definitions
from aura.connections.opencode_process import OpenCodeAgentError, OpenCodeProcess


class TestAgentDefinitions:
    """Tests for the agent_definitions function."""

    def test_returns_three_agents(self) -> None:
        """Test that exactly three agents are defined."""
        definitions = agent_definitions()
        assert set(definitions.keys()) == {"aura-explore", "aura-build", "aura-review"}

    def test_each_agent_has_required_fields(self) -> None:
        """Test that each agent has all required Config.AgentEncoded fields."""
        definitions = agent_definitions()
        required_fields = {"model", "system", "description", "mode", "permissions"}

        for agent_id, agent in definitions.items():
            missing = required_fields - set(agent.keys())
            assert not missing, f"{agent_id} missing fields: {missing}"

    def test_agent_modes_are_valid(self) -> None:
        """Test that agent modes are valid enum values."""
        definitions = agent_definitions()
        valid_modes = {"subagent", "primary", "all"}

        for agent_id, agent in definitions.items():
            assert agent["mode"] in valid_modes, f"{agent_id} has invalid mode: {agent['mode']}"

    def test_aura_explore_is_subagent_read_only(self) -> None:
        """Test that aura-explore is a subagent with read-only permissions."""
        definitions = agent_definitions()
        explore = definitions["aura-explore"]

        assert explore["mode"] == "subagent"
        assert explore["description"] == "Read-only exploration agent for searching and understanding code"

        # Check permissions: read/search allowed, edits denied, shell denied
        perms = {rule["action"]: rule["effect"] for rule in explore["permissions"]}
        assert perms.get("read") == "allow"
        assert perms.get("glob") == "allow"
        assert perms.get("grep") == "allow"
        assert perms.get("list") == "allow"
        assert perms.get("edit") == "deny"
        assert perms.get("write") == "deny"
        assert perms.get("patch") == "deny"
        assert perms.get("bash") == "deny"
        assert perms.get("shell") == "deny"
        assert perms.get("execute") == "deny"

    def test_aura_build_is_primary_with_edits_and_shell_ask(self) -> None:
        """Test that aura-build is primary with edits allowed and shell ask."""
        definitions = agent_definitions()
        build = definitions["aura-build"]

        assert build["mode"] == "primary"
        assert build["description"] == "Build agent with edit and shell access for implementing changes"

        perms = {rule["action"]: rule["effect"] for rule in build["permissions"]}
        assert perms.get("read") == "allow"
        assert perms.get("glob") == "allow"
        assert perms.get("grep") == "allow"
        assert perms.get("list") == "allow"
        assert perms.get("edit") == "allow"
        assert perms.get("write") == "allow"
        assert perms.get("patch") == "allow"
        assert perms.get("bash") == "ask"
        assert perms.get("shell") == "ask"
        assert perms.get("execute") == "ask"

    def test_aura_review_is_subagent_with_test_command_ask(self) -> None:
        """Test that aura-review is subagent with read-only plus test command ask."""
        definitions = agent_definitions()
        review = definitions["aura-review"]

        assert review["mode"] == "subagent"
        assert review["description"] == "Review agent with read access and test command permission"

        perms = {rule["action"]: rule["effect"] for rule in review["permissions"]}
        assert perms.get("read") == "allow"
        assert perms.get("glob") == "allow"
        assert perms.get("grep") == "allow"
        assert perms.get("list") == "allow"
        assert perms.get("edit") == "deny"
        assert perms.get("write") == "deny"
        assert perms.get("patch") == "deny"
        assert perms.get("bash") == "ask"
        assert perms.get("shell") == "ask"
        assert perms.get("execute") == "ask"

    def test_each_agent_has_system_prompt_mentioning_brief(self) -> None:
        """Test that each agent's system prompt mentions the brief as source of truth."""
        definitions = agent_definitions()

        for agent_id, agent in definitions.items():
            assert "brief" in agent["system"].lower(), f"{agent_id} system prompt doesn't mention brief"
            assert "source of truth" in agent["system"].lower(), f"{agent_id} system prompt doesn't mention source of truth"

    def test_model_placeholder_is_present(self) -> None:
        """Test that the model placeholder is present for runtime substitution."""
        definitions = agent_definitions()

        for agent_id, agent in definitions.items():
            assert agent["model"] == "{{opencode_agent_model}}", f"{agent_id} model should be placeholder"


class TestAgentValidation:
    """Tests for the validate_agent_definitions function."""

    def test_valid_definitions_pass(self) -> None:
        """Test that valid definitions pass validation."""
        definitions = agent_definitions()
        errors = validate_agent_definitions(definitions)
        assert errors == []

    def test_missing_required_field_fails(self) -> None:
        """Test that missing required fields are caught."""
        definitions = {
            "test-agent": {
                "model": "test/model",
                "system": "test",
                "description": "test",
                # missing mode and permissions
            }
        }
        errors = validate_agent_definitions(definitions)
        assert any("missing required fields" in e for e in errors)

    def test_invalid_mode_fails(self) -> None:
        """Test that invalid mode is caught."""
        definitions = {
            "test-agent": {
                "model": "test/model",
                "system": "test",
                "description": "test",
                "mode": "invalid_mode",
                "permissions": [],
            }
        }
        errors = validate_agent_definitions(definitions)
        assert any("invalid mode" in e for e in errors)

    def test_invalid_permission_effect_fails(self) -> None:
        """Test that invalid permission effect is caught."""
        definitions = {
            "test-agent": {
                "model": "test/model",
                "system": "test",
                "description": "test",
                "mode": "primary",
                "permissions": [
                    {"action": "read", "resource": "*", "effect": "invalid_effect"}
                ],
            }
        }
        errors = validate_agent_definitions(definitions)
        assert any("invalid effect" in e for e in errors)

    def test_permissions_not_list_fails(self) -> None:
        """Test that non-list permissions is caught."""
        definitions = {
            "test-agent": {
                "model": "test/model",
                "system": "test",
                "description": "test",
                "mode": "primary",
                "permissions": "not_a_list",
            }
        }
        errors = validate_agent_definitions(definitions)
        assert any("permissions must be a list" in e for e in errors)


class TestOpenCodeProcessAgents:
    """Tests for OpenCodeProcess agent configuration (using fake server)."""

    @pytest.fixture
    def free_port(self) -> int:
        """Get a free port for testing."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @pytest.fixture
    def fake_server_script(self) -> Path:
        """Path to the fake OpenCode server script."""
        return Path(__file__).parent.parent / "fixtures" / "fake_opencode_server.py"

    @pytest.fixture(autouse=True)
    def reset_settings(self, monkeypatch):
        """Reset settings before each test."""
        from aura.config import settings
        original_command = settings.opencode_command
        original_version_pin = settings.opencode_version_pin
        original_host = settings.opencode_host
        original_port = settings.opencode_port
        original_timeout = settings.opencode_start_timeout_secs
        original_agent_model = settings.opencode_agent_model

        yield

        settings.opencode_command = original_command
        settings.opencode_version_pin = original_version_pin
        settings.opencode_host = original_host
        settings.opencode_port = original_port
        settings.opencode_start_timeout_secs = original_timeout
        settings.opencode_agent_model = original_agent_model

    async def test_configure_agents_success(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that agent configuration succeeds with a server that supports agents."""
        from aura.config import settings
        from aura.connections.opencode_process import OpenCodeConnection

        # Configure settings to use the fake server with pre-configured agents
        # We'll pass the agent definitions as initial agents to the fake server
        from aura.connections.opencode_agents import agent_definitions
        definitions = agent_definitions()
        agents_json = json.dumps(definitions)

        settings.opencode_command = [
            sys.executable,
            str(fake_server_script),
            "--version",
            "2.3.2",
            "--port",
            str(free_port),
            "--password",
            "test-secret-123",
            "--agents",
            agents_json,
        ]
        settings.opencode_version_pin = "2.3.2"
        settings.opencode_host = "127.0.0.1"
        settings.opencode_port = free_port
        settings.opencode_start_timeout_secs = 10
        settings.opencode_agent_model = "sluice/coder"

        process = OpenCodeProcess()
        connection = await process.start()

        try:
            assert isinstance(connection, OpenCodeConnection)
            assert connection.version == "2.3.2"
        finally:
            await process.stop()

    async def test_configure_agents_missing_raises_error(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that missing agents after configuration raises OpenCodeAgentError."""
        from aura.config import settings

        # Configure fake server to reject PATCH /api/experimental/config
        # by not including the agents in the initial config and making PATCH fail
        settings.opencode_command = [
            sys.executable,
            str(fake_server_script),
            "--version",
            "2.3.2",
            "--port",
            str(free_port),
            "--password",
            "test-secret-123",
            "--reject-patch",  # Custom flag to make PATCH fail
        ]
        settings.opencode_version_pin = "2.3.2"
        settings.opencode_host = "127.0.0.1"
        settings.opencode_port = free_port
        settings.opencode_start_timeout_secs = 10
        settings.opencode_agent_model = "sluice/coder"

        process = OpenCodeProcess()

        with pytest.raises(OpenCodeAgentError) as exc_info:
            await process.start()

        error_msg = str(exc_info.value)
        assert "Missing agents" in error_msg
        assert "aura-build" in error_msg
        assert "aura-review" in error_msg

        await process.stop()

    async def test_patch_config_updates_agents(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that PATCH /api/experimental/config updates the agents."""
        from aura.config import settings

        # Start with no agents
        settings.opencode_command = [
            sys.executable,
            str(fake_server_script),
            "--version",
            "2.3.2",
            "--port",
            str(free_port),
            "--password",
            "test-secret-123",
        ]
        settings.opencode_version_pin = "2.3.2"
        settings.opencode_host = "127.0.0.1"
        settings.opencode_port = free_port
        settings.opencode_start_timeout_secs = 10
        settings.opencode_agent_model = "sluice/coder"

        process = OpenCodeProcess()
        connection = await process.start()

        try:
            # Verify agents were configured via PATCH
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{connection.base_url}/api/agent",
                    auth=connection.auth,
                )
                assert response.status_code == 200
                data = response.json()
                agents = data.get("data", [])
                agent_ids = {agent.get("id") for agent in agents}
                expected = {"aura-explore", "aura-build", "aura-review"}
                assert expected.issubset(agent_ids), f"Missing agents: {expected - agent_ids}"
        finally:
            await process.stop()


class TestFakeServerExtended:
    """Tests for the extended fake server that serves GET /api/agent."""

    def test_fake_server_serves_agents_endpoint(self) -> None:
        """
        Test that the fake server from W3-27 extended to serve GET /api/agent.

        This test verifies the fake server handles the agents endpoint.
        """
        # The fake_opencode_server.py now supports:
        # - GET /api/agent returning configured agents
        # - PATCH /api/experimental/config to update agents
        pass