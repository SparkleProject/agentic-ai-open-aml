"""Transaction ingestion API router (BE-206)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from aml.db.models.transaction import Transaction, TransactionDirection
from aml.db.session import get_db

router = APIRouter(prefix="/transactions", tags=["Transactions"])


class TransactionCreateRequest(BaseModel):
    customer_id: str
    amount: str = Field(description="Decimal string, e.g. '15000.00'")
    currency: str = Field(default="AUD", max_length=3)
    direction: str = Field(description="inbound | outbound | internal")
    counterparty: str | None = None
    description: str | None = None
    transaction_date: datetime
    metadata: dict[str, Any] | None = None


class TransactionBatchRequest(BaseModel):
    transactions: list[TransactionCreateRequest]


def _require_tenant(x_tenant_id: str | None) -> str:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    return x_tenant_id


def _to_direction(raw: str) -> TransactionDirection:
    try:
        return TransactionDirection(raw)
    except ValueError as e:
        valid = [d.value for d in TransactionDirection]
        raise HTTPException(status_code=400, detail=f"Invalid direction '{raw}'. Valid: {valid}") from e


def _build_transaction(body: TransactionCreateRequest, tenant_id: str) -> Transaction:
    return Transaction(
        tenant_id=tenant_id,
        customer_id=uuid.UUID(body.customer_id),
        amount=Decimal(body.amount),
        currency=body.currency,
        direction=_to_direction(body.direction),
        counterparty=body.counterparty,
        description=body.description,
        transaction_date=body.transaction_date,
        metadata_=body.metadata,
    )


@router.post("", status_code=201)
async def ingest_transaction(
    body: TransactionCreateRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    tx = _build_transaction(body, tenant_id)
    db.add(tx)
    await db.commit()

    return {
        "transaction_id": str(tx.id),
        "tenant_id": tenant_id,
        "status": "ingested",
    }


@router.post("/batch", status_code=201)
async def ingest_batch(
    body: TransactionBatchRequest,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _require_tenant(x_tenant_id)
    transactions = [_build_transaction(item, tenant_id) for item in body.transactions]

    for tx in transactions:
        db.add(tx)
    await db.commit()

    return {
        "count": len(transactions),
        "transaction_ids": [str(tx.id) for tx in transactions],
        "tenant_id": tenant_id,
        "status": "ingested",
    }
