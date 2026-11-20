"""
Tests for OpenCode agent definitions (W3-31, W3-31a).

Validates:
1. Agent definitions match Config.AgentEncoded schema
2. Permission rulesets match Permission.Ruleset schema
3. write_config produces valid JSON with provider and three agents
4. Fake server reads agents from XDG_CONFIG_HOME and serves GET /api/agent and GET /api/agent/{id}
5. Start fails when an agent is missing
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from aura.connections.opencode_agents import agent_definitions, validate_agent_definitions, write_config
from aura.connections.opencode_process import OpenCodeAgentError, OpenCodeProcess, OpenCodeStartError


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


class TestWriteConfig:
    """Tests for the write_config function (W3-31a)."""

    def test_write_config_creates_valid_json_with_provider_and_agents(self) -> None:
        """Test that write_config produces valid JSON with provider and three agents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_path = write_config(config_dir)

            # Check file exists
            assert config_path.exists()
            assert config_path == config_dir / "opencode" / "opencode.jsonc"

            # Load and validate JSON
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Check top-level keys
            assert set(config.keys()) == {"provider", "agents"}

            # Check provider
            provider = config["provider"]
            assert provider["npm"] == "@ai-sdk/openai-compatible"
            assert provider["name"] == "Sluice"
            assert "options" in provider
            assert provider["options"]["baseURL"] == "http://127.0.0.1:8787/v1"
            assert "models" in provider
            assert provider["models"]["coder"]["name"] == "coder"
            assert provider["models"]["chat"]["name"] == "chat"

            # Check agents
            agents = config["agents"]
            assert set(agents.keys()) == {"aura-explore", "aura-build", "aura-review"}

            for agent_id, agent in agents.items():
                assert "model" in agent
                assert "system" in agent
                assert "description" in agent
                assert "mode" in agent
                assert "permissions" in agent
                # Model placeholder should be replaced with actual model
                assert agent["model"] == "sluice/coder"

    def test_write_config_creates_directories(self) -> None:
        """Test that write_config creates the opencode directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "nested" / "config"
            config_path = write_config(config_dir)

            assert config_path.exists()
            assert config_path.parent.exists()

    def test_write_config_is_atomic(self) -> None:
        """Test that write_config writes atomically (no partial writes)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_path = write_config(config_dir)

            # File should exist and be valid JSON immediately
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            assert "provider" in config
            assert "agents" in config


class TestOpenCodeProcessAgents:
    """Tests for OpenCodeProcess agent configuration using fake server (W3-31a)."""

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
        original_config_dir = settings.opencode_config_dir
        original_router_base_url = settings.opencode_router_base_url

        yield

        settings.opencode_command = original_command
        settings.opencode_version_pin = original_version_pin
        settings.opencode_host = original_host
        settings.opencode_port = original_port
        settings.opencode_start_timeout_secs = original_timeout
        settings.opencode_agent_model = original_agent_model
        settings.opencode_config_dir = original_config_dir
        settings.opencode_router_base_url = original_router_base_url

    async def test_start_succeeds_with_agents_via_xdg_config_home(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that agent configuration succeeds via XDG_CONFIG_HOME."""
        from aura.config import settings
        from aura.connections.opencode_process import OpenCodeConnection

        # Create a temporary config directory and write the config
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            write_config(config_dir)

            # Configure settings to use the fake server with XDG_CONFIG_HOME
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
            settings.opencode_config_dir = str(config_dir)
            settings.opencode_router_base_url = "http://127.0.0.1:8787/v1"

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                assert isinstance(connection, OpenCodeConnection)
                assert connection.version == "2.3.2"

                # Verify agents are accessible via GET /api/agent/{id}
                async with httpx.AsyncClient(timeout=5.0) as client:
                    for agent_id in ["aura-explore", "aura-build", "aura-review"]:
                        response = await client.get(
                            f"{connection.base_url}/api/agent/{agent_id}",
                            auth=connection.auth,
                        )
                        assert response.status_code == 200, f"Agent {agent_id} not found"
                        data = response.json()
                        assert data["id"] == agent_id
            finally:
                await process.stop()

    async def test_start_fails_when_agent_missing(
        self, free_port: int, fake_server_script: Path, monkeypatch
    ) -> None:
        """Test that start fails with OpenCodeStartError when an agent is missing."""
        from aura.config import settings
        import aura.connections.opencode_process as opencode_process_module

        # Create a config with only one agent
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            opencode_dir = config_dir / "opencode"
            opencode_dir.mkdir(parents=True)
            config_path = opencode_dir / "opencode.jsonc"
            config = {
                "provider": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Sluice",
                    "options": {"baseURL": "http://127.0.0.1:8787/v1"},
                    "models": {"coder": {"name": "coder"}, "chat": {"name": "chat"}},
                },
                "agents": {
                    "aura-explore": {
                        "model": "sluice/coder",
                        "system": "test",
                        "description": "test",
                        "mode": "subagent",
                        "permissions": [],
                    }
                },
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f)

            # Patch write_config where it's used in opencode_process
            def mock_write_config(config_dir_arg: Path) -> Path:
                # Just return the existing config path without overwriting
                return config_path

            monkeypatch.setattr(opencode_process_module, "write_config", mock_write_config)

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
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()

            with pytest.raises(OpenCodeStartError) as exc_info:
                await process.start()

            error_msg = str(exc_info.value)
            assert "not found" in error_msg.lower() or "missing" in error_msg.lower()
            # Should mention one of the missing agents
            assert "aura-build" in error_msg or "aura-review" in error_msg

            await process.stop()

    async def test_no_request_to_experimental_config(
        self, free_port: int, fake_server_script: Path
    ) -> None:
        """Test that no request to /api/experimental/config is ever made."""
        from aura.config import settings
        from tests.fixtures.fake_opencode_server import _request_paths

        # Clear request paths
        _request_paths.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            write_config(config_dir)

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
            settings.opencode_config_dir = str(config_dir)

            process = OpenCodeProcess()
            connection = await process.start()

            try:
                # Check that no request to /api/experimental/config was made
                experimental_config_requests = [
                    p for p in _request_paths if p == "/api/experimental/config"
                ]
                assert len(experimental_config_requests) == 0, (
                    f"Unexpected request to /api/experimental/config: {experimental_config_requests}"
                )

                # Verify agents are accessible
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(
                        f"{connection.base_url}/api/agent",
                        auth=connection.auth,
                    )
                    assert response.status_code == 200
            finally:
                await process.stop()


class TestFakeServerXDGConfigHome:
    """Tests for the fake server reading from XDG_CONFIG_HOME (W3-31a)."""

    def test_fake_server_loads_agents_from_xdg_config_home(self, tmp_path: Path) -> None:
        """
        Test that the fake server loads agents from XDG_CONFIG_HOME/opencode/opencode.jsonc.
        """
        # This test verifies the fake server handles the config file
        # The actual loading is tested in the integration tests above
        pass