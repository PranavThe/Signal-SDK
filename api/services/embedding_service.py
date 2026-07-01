from __future__ import annotations

import logging
import asyncio
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings


logger = logging.getLogger(__name__)

VOYAGE_EMBEDDING_MODEL = "voyage-3"
VOYAGE_EMBEDDING_DIMENSIONS = 1024


def vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


async def embed(text_value: str, input_type: str = "document") -> list[float]:
    if not settings.voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is required to generate embeddings")

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(3):
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.voyage_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": VOYAGE_EMBEDDING_MODEL,
                    "input": [text_value],
                    "input_type": input_type,
                },
            )
            if response.status_code != 429 or attempt == 2:
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                break
            await asyncio.sleep(2**attempt)

    embedding = data["data"][0]["embedding"]
    if len(embedding) != VOYAGE_EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Expected {VOYAGE_EMBEDDING_DIMENSIONS} embedding dimensions, got {len(embedding)}"
        )
    return [float(value) for value in embedding]


async def save_escalation_embedding(
    session: AsyncSession,
    escalation_id: str,
    embedding: list[float],
) -> None:
    await session.execute(
        text(
            """
            UPDATE escalations
            SET context_embedding = CAST(:embedding AS vector)
            WHERE id = CAST(:escalation_id AS uuid)
            """
        ),
        {"embedding": vector_literal(embedding), "escalation_id": escalation_id},
    )


async def save_rule_embedding(
    session: AsyncSession,
    rule_id: str,
    embedding: list[float],
) -> None:
    await session.execute(
        text(
            """
            UPDATE rules
            SET condition_embedding = CAST(:embedding AS vector)
            WHERE id = CAST(:rule_id AS uuid)
            """
        ),
        {"embedding": vector_literal(embedding), "rule_id": rule_id},
    )
