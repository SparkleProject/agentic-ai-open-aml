import pytest

from aml.agents.tools.local.screening import SanctionsTool
from aml.agents.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset the singleton between tests"""
    ToolRegistry._instance = None
    yield


@pytest.mark.asyncio
async def test_tool_registry_singleton_and_schema():
    # Instantiate registry
    registry = ToolRegistry.get_instance()

    # Register Sanctions Tool
    s_tool = SanctionsTool()
    registry.register(s_tool)

    # Retrieve schema as if passing to LLM
    schemas = registry.get_tool_schemas()

    assert len(schemas) == 1
    assert schemas[0]["name"] == "SanctionsScreeningTool"
    assert "description" in schemas[0]
    assert "entity_name" in schemas[0]["parameters"]["properties"]


@pytest.mark.asyncio
async def test_tool_registry_successful_execution():
    registry = ToolRegistry.get_instance()
    registry.register(SanctionsTool())

    # A successful hit on the mock db
    result = await registry.execute("SanctionsScreeningTool", {"entity_name": "bin laden"})

    assert "OFAC" in result
    assert "UN" in result


@pytest.mark.asyncio
async def test_tool_registry_failed_validation_execution():
    registry = ToolRegistry.get_instance()
    registry.register(SanctionsTool())

    # Missing the required 'entity_name' parameter. This mimics an LLM hallucination.
    error_result = await registry.execute("SanctionsScreeningTool", {"wrong_param": "some name"})

    # Should catch the pydantic ValidationError gracefully and return the string trace
    assert "Error executing tool" in error_result
    assert "Field required" in error_result


@pytest.mark.asyncio
async def test_tool_registry_unregistered_tool():
    registry = ToolRegistry.get_instance()

    # Call a tool that doesn't exist
    error_result = await registry.execute("HallucinatedTool", {"target": "something"})

    assert "not registered" in error_result
