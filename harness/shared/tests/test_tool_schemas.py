"""Tests for harness/shared/tool_schemas.py.

test_orchestrator_tools.py already pins that every declared tool has a
dispatcher handler and that handlers return strings -- but nothing checked
the schemas themselves for internal consistency. A `required` entry naming
a property the schema never declares, or a missing `additionalProperties:
False`, would pass every existing test silently. This is the genuine gap
docs/specs/... (coverage-gap-closure) identified, not a re-test of what
test_orchestrator_tools.py already covers.
"""

from __future__ import annotations

from typing import Any

from harness.shared.meta_tools import META_TOOLS_SCHEMA as _META_TOOLS_SCHEMA
from harness.shared.tool_schemas import NEMOTRON_TOOLS as _NEMOTRON_TOOLS

# Re-annotated: the module-level literal infers a narrower structural type
# than its actual shape (nested dicts alongside str values), which mypy
# then can't index into. test_orchestrator_tools.py works around the same
# inference gap the same way.
NEMOTRON_TOOLS: list[dict[str, Any]] = _NEMOTRON_TOOLS
META_TOOLS_SCHEMA: list[dict[str, Any]] = _META_TOOLS_SCHEMA


class TestSchemaShape:
    def test_every_entry_is_a_function_tool(self) -> None:
        for tool in NEMOTRON_TOOLS:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert tool["function"]["description"], f"{tool['function']['name']} has an empty description"

    def test_every_entry_declares_object_parameters(self) -> None:
        for tool in NEMOTRON_TOOLS:
            params = tool["function"]["parameters"]
            assert params["type"] == "object"
            assert "properties" in params

    def test_no_two_tools_share_a_name(self) -> None:
        names = [tool["function"]["name"] for tool in NEMOTRON_TOOLS]
        assert len(names) == len(set(names)), f"duplicate tool name(s) in NEMOTRON_TOOLS: {names}"


class TestRequiredFieldsAreDeclaredProperties:
    """The specific drift class nothing previously checked: `required` naming
    a field `properties` never declares (or vice versa going undetected)."""

    def test_every_required_field_is_a_declared_property(self) -> None:
        for tool in NEMOTRON_TOOLS:
            name = tool["function"]["name"]
            params = tool["function"]["parameters"]
            properties = set(params.get("properties", {}))
            required = set(params.get("required", []))
            undeclared = required - properties
            assert not undeclared, f"{name}: required field(s) {undeclared} are not in properties"

    def test_every_property_has_a_type_and_description(self) -> None:
        for tool in NEMOTRON_TOOLS:
            name = tool["function"]["name"]
            for prop_name, prop_schema in tool["function"]["parameters"].get("properties", {}).items():
                assert "type" in prop_schema, f"{name}.{prop_name} has no declared type"
                assert "description" in prop_schema, f"{name}.{prop_name} has no description"


class TestAdditionalPropertiesIsClosed:
    """Every one of the four hand-written tool schemas sets
    `additionalProperties: False` today -- pin it so a future tool added to
    this list without it doesn't silently accept arbitrary extra model
    arguments (the meta-tools, defined in meta_tools.py, are checked
    separately below since they are a different module's responsibility)."""

    def test_all_four_orchestrator_tools_close_additional_properties(self) -> None:
        meta_tool_names = {t["function"]["name"] for t in META_TOOLS_SCHEMA}
        for tool in NEMOTRON_TOOLS:
            if tool["function"]["name"] in meta_tool_names:
                continue
            assert tool["function"]["parameters"]["additionalProperties"] is False, (
                f"{tool['function']['name']} does not close additionalProperties"
            )


class TestMetaToolsAreIncluded:
    def test_nemotron_tools_includes_every_meta_tool(self) -> None:
        nemotron_names = {t["function"]["name"] for t in NEMOTRON_TOOLS}
        meta_names = {t["function"]["name"] for t in META_TOOLS_SCHEMA}
        assert meta_names <= nemotron_names

    def test_knowledge_gap_log_and_hypothesis_register_are_present(self) -> None:
        names = {t["function"]["name"] for t in NEMOTRON_TOOLS}
        assert "knowledge_gap_log" in names
        assert "hypothesis_register" in names
