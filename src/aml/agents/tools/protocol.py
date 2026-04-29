from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseTool(Protocol):
    """
    Interface that all AML tools (local and external MCPs) must implement.
    Conforms to expected LLM Tool constraints.
    """

    # Internal unique identifier (e.g. SanctionsCheck)
    name: str

    # Critical instruction given to the LLM defining when to use this tool
    description: str

    # Dict representation of the JSON Schema required to invoke this tool
    # Extracted mechanically from Pydantic `model_json_schema()`
    input_schema: dict[str, Any]

    async def execute(self, params: dict[str, Any]) -> str | dict[str, Any]:
        """
        Executes the business logic for the tool.
        Takes unstructured input from the LLM, validates it against the schema internally,
        and returns a stringified observation (or parsed dict observation).
        """
        ...
