from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BaseTool(Protocol):
    """
    Interface that all AML tools (local and external MCPs) must implement.
    Conforms to expected LLM Tool constraints.
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> dict[str, Any]: ...

    async def execute(self, params: dict[str, Any]) -> str | dict[str, Any]:
        """
        Executes the business logic for the tool.
        Takes unstructured input from the LLM, validates it against the schema internally,
        and returns a stringified observation (or parsed dict observation).
        """
        ...
