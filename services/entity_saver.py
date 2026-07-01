"""Service to save discovered entities (bots, users) to DB for deduplication."""

import logging
from typing import Optional, Set
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select

from database.models import DiscoveredEntityDB, PreliminaryScoreDB, PreliminaryGroupScoreDB
from database.connection import async_session_maker

logger = logging.getLogger(__name__)


async def save_discovered_entity(
    username: str,
    telegram_id: Optional[int],
    entity_type: str,  # 'user', 'bot'
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    is_verified: bool = False,
    is_premium: bool = False,
    discovered_from: Optional[str] = None,
) -> bool:
    """
    Save a discovered entity (bot or user) to database.

    Args:
        username: Entity username (without @)
        telegram_id: Telegram ID
        entity_type: 'user' or 'bot'
        first_name: First name
        last_name: Last name
        is_verified: Is verified account
        is_premium: Is premium user
        discovered_from: Source of discovery

    Returns:
        True if saved (new), False if duplicate
    """
    async with async_session_maker() as session:
        try:
            # Build display title
            title = None
            if first_name:
                title = first_name
                if last_name:
                    title += f" {last_name}"

            stmt = insert(DiscoveredEntityDB).values(
                username=username,
                telegram_id=telegram_id,
                entity_type=entity_type,
                title=title,
                first_name=first_name,
                last_name=last_name,
                is_verified=is_verified,
                is_premium=is_premium,
                discovered_from=discovered_from,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["username"])

            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount > 0:
                logger.debug(f"Saved new {entity_type}: @{username}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error saving entity @{username}: {e}")
            await session.rollback()
            return False


async def is_username_known(username: str) -> Optional[str]:
    """
    Check if username is already known in any table.

    Returns:
        - 'channel' if found in preliminary_scores
        - 'group' if found in preliminary_group_scores
        - 'bot' or 'user' if found in discovered_entities
        - None if not found
    """
    username = username.lstrip("@").lower()

    async with async_session_maker() as session:
        try:
            # Check preliminary_scores (channels)
            stmt = select(PreliminaryScoreDB.id).where(
                PreliminaryScoreDB.username.ilike(username)
            ).limit(1)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                return "channel"

            # Check preliminary_group_scores (groups)
            stmt = select(PreliminaryGroupScoreDB.id).where(
                PreliminaryGroupScoreDB.username.ilike(username)
            ).limit(1)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                return "group"

            # Check discovered_entities (bots, users)
            stmt = select(DiscoveredEntityDB.entity_type).where(
                DiscoveredEntityDB.username.ilike(username)
            ).limit(1)
            result = await session.execute(stmt)
            entity_type = result.scalar_one_or_none()
            if entity_type:
                return entity_type

            return None

        except Exception as e:
            logger.error(f"Error checking username @{username}: {e}")
            return None


async def filter_unknown_usernames(usernames: Set[str]) -> Set[str]:
    """
    Filter out usernames that are already known.

    Args:
        usernames: Set of usernames to check

    Returns:
        Set of unknown usernames (not in any table)
    """
    unknown = set()

    for username in usernames:
        if not await is_username_known(username):
            unknown.add(username)

    logger.debug(f"Filtered {len(usernames)} usernames: {len(unknown)} unknown, {len(usernames) - len(unknown)} known")
    return unknown


async def get_entity_stats() -> dict:
    """Get statistics about discovered entities."""
    async with async_session_maker() as session:
        try:
            stmt = select(
                DiscoveredEntityDB.entity_type,
                DiscoveredEntityDB.id
            )
            result = await session.execute(stmt)
            rows = result.all()

            stats = {"user": 0, "bot": 0, "total": 0}
            for entity_type, _ in rows:
                stats[entity_type] = stats.get(entity_type, 0) + 1
                stats["total"] += 1

            return stats

        except Exception as e:
            logger.error(f"Error getting entity stats: {e}")
            return {"user": 0, "bot": 0, "total": 0}
