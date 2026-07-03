from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import secrets
import string
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.database import AsyncSessionLocal
from api.models import Account, ApiKey, Organization


KEY_PREFIX = "sk_live_"
KEY_RANDOM_LENGTH = 32


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "org"


def _new_api_key() -> str:
    alphabet = string.ascii_letters + string.digits
    return KEY_PREFIX + "".join(secrets.choice(alphabet) for _ in range(KEY_RANDOM_LENGTH))


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def create_org(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        account = Account(
            name=f"{args.name} account",
            plan_tier=args.plan_tier,
            billing_status="active",
        )
        session.add(account)
        await session.flush()
        org = Organization(name=args.name, slack_channel_id=args.slack_channel_id, account_id=account.id)
        session.add(org)
        await session.flush()
        await session.commit()
        print(f"Created org {_slugify(org.name)} (id: {org.id}, account_id: {account.id})")


async def create_api_key(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        org_id = UUID(args.org_id)
        org = (await session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"No organization found for id {args.org_id}")

        api_key = _new_api_key()
        record = ApiKey(
            org_id=org.id,
            key_hash=_hash_key(api_key),
            key_prefix=api_key[:8],
            name=args.name,
        )
        session.add(record)
        await session.commit()
        print(api_key)


async def set_webhook(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        org_id = UUID(args.org_id)
        org = (await session.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
        if org is None:
            raise SystemExit(f"No organization found for id {args.org_id}")

        org.webhook_url = args.url
        org.webhook_secret = args.secret
        await session.commit()
        print(f"Webhook configured for org {org.id}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Signal organizations and API keys.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_org_parser = subparsers.add_parser("create-org", help="Create an organization")
    create_org_parser.add_argument("--name", required=True)
    create_org_parser.add_argument("--slack-channel-id")
    create_org_parser.add_argument("--plan-tier", choices=["free", "pro", "scale", "enterprise"], default="free")
    create_org_parser.set_defaults(func=create_org)

    create_key_parser = subparsers.add_parser("create-api-key", help="Create an API key for an organization")
    create_key_parser.add_argument("--org-id", required=True)
    create_key_parser.add_argument("--name", default="Default")
    create_key_parser.set_defaults(func=create_api_key)

    webhook_parser = subparsers.add_parser("set-webhook", help="Configure an organization webhook")
    webhook_parser.add_argument("--org-id", required=True)
    webhook_parser.add_argument("--url", required=True)
    webhook_parser.add_argument("--secret", required=True)
    webhook_parser.set_defaults(func=set_webhook)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
