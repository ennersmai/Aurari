"""
Test that all OpenCodeClient endpoints exist in the OpenAPI spec (W3-28).

Loads the saved spec and asserts every (method, path template) the client uses exists in it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aura.connections.opencode_client import OPENCODE_CLIENT_ENDPOINTS


def load_openapi_spec() -> dict:
    """Load the OpenCode OpenAPI spec."""
    spec_path = Path(__file__).parent.parent.parent / "docs" / "opencode" / "openapi-v2.3.2.json"
    with open(spec_path, "r") as f:
        return json.load(f)


def normalize_path(path: str) -> str:
    """Normalize a path template for comparison.

    The spec uses {paramName} format, and the client may use the same or similar.
    """
    return path


class TestOpenCodeSpecCoverage:
    """Tests that verify client endpoints are covered by the OpenAPI spec."""

    @pytest.fixture
    def spec(self) -> dict:
        return load_openapi_spec()

    def test_all_client_endpoints_in_spec(self, spec: dict) -> None:
        """Test that every (method, path) in OPENCODE_CLIENT_ENDPOINTS exists in the spec."""
        paths = spec.get("paths", {})

        missing = []
        for method, path in OPENCODE_CLIENT_ENDPOINTS:
            # Normalize path for lookup
            normalized_path = normalize_path(path)

            if normalized_path not in paths:
                missing.append((method, path, "path not in spec"))
                continue

            path_obj = paths[normalized_path]
            method_lower = method.lower()

            if method_lower not in path_obj:
                missing.append((method, path, f"method {method} not in spec for path"))

        if missing:
            # Provide helpful error message
            msg_lines = ["The following client endpoints are not in the OpenAPI spec:"]
            for method, path, reason in missing:
                msg_lines.append(f"  {method} {path} - {reason}")

            # Also show available paths for debugging
            available = sorted(paths.keys())
            msg_lines.append("\nAvailable paths in spec:")
            for p in available:
                msg_lines.append(f"  {p}")

            pytest.fail("\n".join(msg_lines))

    def test_endpoint_parameters_match(self, spec: dict) -> None:
        """Test that path parameters in client endpoints match spec parameters."""
        paths = spec.get("paths", {})

        for method, path in OPENCODE_CLIENT_ENDPOINTS:
            normalized_path = normalize_path(path)

            if normalized_path not in paths:
                continue  # Already caught by test_all_client_endpoints_in_spec

            path_obj = paths[normalized_path]
            method_lower = method.lower()

            if method_lower not in path_obj:
                continue

            op = path_obj[method_lower]
            spec_params = {p["name"] for p in op.get("parameters", [])}

            # Extract parameters from path template
            import re
            path_params = set(re.findall(r"\{(\w+)\}", normalized_path))

            # Check that all path parameters are defined in spec
            for param in path_params:
                assert param in spec_params, (
                    f"Path parameter '{param}' in {method} {path} "
                    f"not defined in spec parameters: {spec_params}"
                )

    def test_spec_has_required_schemas(self, spec: dict) -> None:
        """Test that the spec has the schemas we rely on."""
        components = spec.get("components", {})
        schemas = components.get("schemas", {})

        required_schemas = [
            "V2EventEncoded",
            "V2Event",
            "permission.asked",
            "permission.replied",
            "Permission.ID",
            "Permission.Reply",
            "Session.ID",
            "FileDiff.Info",
            "Session.Message.Info",
            "SessionMessagesResponse",
        ]

        for schema_name in required_schemas:
            assert schema_name in schemas, f"Required schema '{schema_name}' not in spec"

    def test_event_types_in_spec(self, spec: dict) -> None:
        """Test that the event types we handle are in the spec."""
        paths = spec.get("paths", {})
        event_path = paths.get("/api/event", {})
        get_op = event_path.get("get", {})
        params = get_op.get("parameters", [])

        # Find the 'types' parameter
        types_param = None
        for p in params:
            if p.get("name") == "types":
                types_param = p
                break

        assert types_param is not None, "No 'types' parameter in /api/event"

        # Check that the enum includes the event types we care about
        # The enum is nested in anyOf[0].enum
        schema = types_param.get("schema", {})
        any_of = schema.get("anyOf", [])
        enum_values = []
        for item in any_of:
            if "enum" in item:
                enum_values.extend(item["enum"])

        required_event_types = [
            "session.execution.started",
            "session.execution.succeeded",
            "session.execution.failed",
            "session.execution.interrupted",
            "session.step.started",
            "session.step.ended",
            "session.step.failed",
            "session.tool.called",
            "session.tool.success",
            "session.tool.failed",
            "permission.asked",
            "permission.replied",
            "session.idle",
        ]

        for event_type in required_event_types:
            assert event_type in enum_values, (
                f"Event type '{event_type}' not in spec enum for /api/event types"
            )

    def test_permission_reply_schema(self, spec: dict) -> None:
        """Test that the permission reply request body schema matches what we send."""
        paths = spec.get("paths", {})
        reply_path = paths.get("/api/session/{sessionID}/permission/{requestID}/reply", {})
        post_op = reply_path.get("post", {})

        request_body = post_op.get("requestBody", {})
        content = request_body.get("content", {})
        json_schema = content.get("application/json", {}).get("schema", {})

        # Should have 'decision' property with Permission.Reply enum
        properties = json_schema.get("properties", {})
        assert "decision" in properties, "Missing 'decision' in permission reply schema"

        decision_schema = properties["decision"]
        ref = decision_schema.get("$ref", "")
        assert "Permission.Reply" in ref, f"decision should reference Permission.Reply, got {ref}"

    def test_diff_endpoint_exists(self, spec: dict) -> None:
        """Test that the diff endpoint exists with expected response."""
        paths = spec.get("paths", {})
        diff_path = paths.get("/api/session/{sessionID}/diff", {})
        get_op = diff_path.get("get", {})

        assert get_op is not None, "GET /api/session/{sessionID}/diff not in spec"

        # Check response has FileDiff.Info array
        responses = get_op.get("responses", {})
        success = responses.get("200", {})
        content = success.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})

        # Should have data array of FileDiff.Info
        properties = schema.get("properties", {})
        assert "data" in properties
        data_schema = properties["data"]
        assert "items" in data_schema
        items_ref = data_schema["items"].get("$ref", "")
        assert "FileDiff.Info" in items_ref, f"Diff items should be FileDiff.Info, got {items_ref}"

    def test_message_list_endpoint_exists(self, spec: dict) -> None:
        """Test that the message list endpoint exists."""
        paths = spec.get("paths", {})
        msg_path = paths.get("/api/session/{sessionID}/message", {})
        get_op = msg_path.get("get", {})

        assert get_op is not None, "GET /api/session/{sessionID}/message not in spec"

        # Check it supports type parameter
        params = get_op.get("parameters", [])
        param_names = {p.get("name") for p in params}
        assert "type" in param_names, "Missing 'type' parameter in message list endpoint"
        assert "limit" in param_names, "Missing 'limit' parameter in message list endpoint"
        assert "order" in param_names, "Missing 'order' parameter in message list endpoint"

    def test_session_create_body_has_location(self, spec: dict) -> None:
        """Test that session create accepts location with directory."""
        paths = spec.get("paths", {})
        session_path = paths.get("/api/session", {})
        post_op = session_path.get("post", {})

        request_body = post_op.get("requestBody", {})
        content = request_body.get("content", {})
        json_schema = content.get("application/json", {}).get("schema", {})

        properties = json_schema.get("properties", {})
        assert "location" in properties, "Missing 'location' in session create body"

        location_schema = properties["location"]
        # Location should reference Location.PublicRef
        ref = location_schema.get("$ref", "") or location_schema.get("anyOf", [{}])[0].get("$ref", "")
        assert "Location.PublicRef" in ref, f"location should reference Location.PublicRef, got {ref}"