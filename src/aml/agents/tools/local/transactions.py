import json
from typing import Any

from pydantic import BaseModel, Field

from aml.agents.tools.protocol import BaseTool


class TransactionLookupInput(BaseModel):
    customer_id: str = Field(description="The UUID or standard identifier for the customer.")
    limit: int = Field(default=10, description="Max number of recent transactions to return. Default 10.")
    days_back: int = Field(default=30, description="How many days back to look for transaction history.")


class TransactionLookupTool(BaseTool):
    """
    Mock Transaction Lookup Tool implementation.
    """

    @property
    def name(self) -> str:
        return "TransactionLookupTool"

    @property
    def description(self) -> str:
        return (
            "Retrieves a summarized history of recent financial transactions "
            "for a specific customer to analyze for structuring or anomalous flows."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return TransactionLookupInput.model_json_schema()

    async def execute(self, params: dict[str, Any]) -> str:
        validated_input = TransactionLookupInput(**params)

        # Mock logic. In a real system, we'd inject an async DB session here
        # and query the models.Transaction table.
        return json.dumps(
            {
                "customer_id": validated_input.customer_id,
                "period": f"Last {validated_input.days_back} days",
                "transactions": [
                    {
                        "date": "2026-04-10",
                        "amount": 9500.00,
                        "currency": "USD",
                        "type": "WIRE_OUT",
                        "merchant": "Acme Shell Co",
                    },
                    {"date": "2026-04-09", "amount": 1000.00, "currency": "USD", "type": "CASH_DEPOSIT"},
                ],
            }
        )
