import logging
from typing import Any

from aml.agents.tools.protocol import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central repository for mapping tool executions to their respective local/MCP implementations.
    Provides the master schema dictionary demanded by the Reasoner node LLM.
    """

    _instance: "ToolRegistry | None" = None

    def __init__(self) -> None:
        if ToolRegistry._instance is not None:
            raise Exception("ToolRegistry is a singleton. Use ToolRegistry.get_instance().")
        self._tools: dict[str, BaseTool] = {}
        ToolRegistry._instance = self

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls()
        return cls._instance  # type: ignore

    def register(self, tool: BaseTool) -> None:
        """Adds a tool to the active registry."""
        if tool.name in self._tools:
            logger.warning("Tool %s is already registered. Overwriting.", tool.name)
        self._tools[tool.name] = tool

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """
        Returns a list of structured JSON specs for all registered tools,
        designed to be injected directly into system prompts.
        """
        schemas = []
        for name, tool in self._tools.items():
            schemas.append({"name": name, "description": tool.description, "parameters": tool.input_schema})
        return schemas

    async def execute(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        Dynamic router. Routes the parameter payload to the targeted tool class.
        Captures Exceptions (like validation errors from LLM hallucinating schemas)
        and safely returns them as strings context for the LLM to learn from.
        """
        if tool_name not in self._tools:
            return f"Error: Tool '{tool_name}' is not registered."

        tool = self._tools[tool_name]
        try:
            # We await the tool assuming all BaseTools support async execution
            result = await tool.execute(params)
            # Ensure observations map explicitly into stringable formats
            return str(result)
        except Exception as e:
            logger.error("Error executing tool %s: %s", tool_name, str(e), exc_info=True)
            return f"Error executing tool {tool_name}: {e!s}. Please review your parameters."
