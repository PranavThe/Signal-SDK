from __future__ import annotations

import logging

from api.database import AsyncSessionLocal
from api.config import settings
from api.models import Escalation, Organization
from api.services.embedding_service import embed, save_escalation_embedding
from api.services.semantic_service import find_similar_escalations
from api.services.slack_service import SlackService


logger = logging.getLogger(__name__)


def slack_delivery_available(org: Organization | None = None) -> bool:
    if org is not None and not org.slack_notifications_enabled:
        return False
    if not settings.slack_bot_token:
        return False
    return bool((org and org.slack_channel_id) or settings.slack_channel_id)


async def prepare_escalation_surfaces(escalation_id: str) -> None:
    async with AsyncSessionLocal() as session:
        escalation = await session.get(Escalation, escalation_id)
        if escalation is None:
            return

        similar_decisions = []
        try:
            embedding = await embed(escalation.context)
            await save_escalation_embedding(session, str(escalation.id), embedding)
            await session.commit()
            similar_decisions = await find_similar_escalations(
                session,
                embedding,
                str(escalation.id),
                str(escalation.org_id) if escalation.org_id else None,
            )
        except Exception:
            logger.exception("Could not prepare semantic context for escalation %s", escalation_id)
            await session.rollback()
            escalation = await session.get(Escalation, escalation_id)
            if escalation is None:
                return

        org = await session.get(Organization, escalation.org_id) if escalation.org_id else None
        if not slack_delivery_available(org):
            return

        channel_id = org.slack_channel_id if org and org.slack_channel_id else settings.slack_channel_id
        slack_response = await SlackService().send_escalation_card(
            escalation,
            similar_decisions,
            channel_id=channel_id,
        )
        escalation.slack_channel_id = slack_response["channel"]
        escalation.slack_message_ts = slack_response["ts"]
        await session.commit()


async def prepare_escalation_slack_card(escalation_id: str) -> None:
    await prepare_escalation_surfaces(escalation_id)
