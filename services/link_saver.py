"""Service to save discovered Telegram links to DB.

Links are saved to DB with status='pending'. A background task (LinkSenderBackground)
periodically flushes pending links to the crawler API.

This decoupling prevents crawler API issues from blocking workers or exhausting
the DB connection pool.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Set, Optional, TYPE_CHECKING
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select, func, update
from database.models import DiscoveredLinkDB
from database.connection import async_session_maker

if TYPE_CHECKING:
    # Optional analyzer-queue integration is not part of this public build.
    from typing import Any as ChannelQueue  # type: ignore

logger = logging.getLogger(__name__)

# Username validation (Telegram: 5-32 chars, starts with letter, a-z0-9_)
USERNAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')


def is_valid_username(username: str) -> bool:
    """Check if username is valid for Telegram."""
    if not username or len(username) < 5 or len(username) > 32:
        return False
    return bool(USERNAME_PATTERN.match(username))

# Batch settings
CRAWLER_BATCH_SIZE = int(os.getenv("CRAWLER_BATCH_SIZE", "5000"))
CRAWLER_AUTO_FLUSH_THRESHOLD = int(os.getenv("CRAWLER_AUTO_FLUSH_THRESHOLD", "5000"))
# Auto-flush disabled by default - use LinkSenderBackground instead
CRAWLER_AUTO_FLUSH_ENABLED = os.getenv("CRAWLER_AUTO_FLUSH_ENABLED", "false").lower() == "true"


class LinkSaver:
    """Save discovered Telegram channel/chat links to DB and send to crawler in batches."""

    def __init__(
        self,
        export_dir: Optional[str] = None,
        analyzer_queue: Optional["ChannelQueue"] = None,
        batch_size: int = CRAWLER_BATCH_SIZE,
        auto_flush_threshold: int = CRAWLER_AUTO_FLUSH_THRESHOLD,
        auto_flush_enabled: bool = CRAWLER_AUTO_FLUSH_ENABLED,
    ):
        """
        Initialize link saver.

        Args:
            export_dir: Directory for exporting link files for crawler.
                       Defaults to ./discovered_links/
            analyzer_queue: Optional ChannelQueue to automatically add discovered
                          links for immediate analysis (hybrid mode)
            batch_size: Max links per API request (default 5000)
            auto_flush_threshold: Auto-flush when pending count exceeds this (default 5000)
            auto_flush_enabled: Whether to auto-flush (default False, use background sender)
        """
        self.export_dir = Path(export_dir or os.getenv(
            "DISCOVERED_LINKS_DIR",
            "./discovered_links"
        ))
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.analyzer_queue = analyzer_queue
        self.batch_size = batch_size
        self.auto_flush_threshold = auto_flush_threshold
        self.auto_flush_enabled = auto_flush_enabled
        self._pending_count = 0  # Track pending links for auto-flush

    async def save_links(
        self,
        usernames: Set[str],
        discovered_from: str,
        priority: int = 0,
        export_immediately: bool = False,
        add_to_analyzer: bool = True,
    ) -> dict:
        """
        Save discovered links to database. Links are batched and sent to crawler
        when threshold is reached (call flush_to_crawler() to force send).

        Args:
            usernames: Set of channel/chat usernames (without @)
            discovered_from: Source description (e.g., "channel:durov")
            priority: Priority level (1=high, 0=normal, -1=low)
            export_immediately: Whether to export to file immediately
            add_to_analyzer: Whether to add to analyzer queue (if queue is set)

        Returns:
            Dict with stats: {saved: int, duplicates: int, exported: int, export_file: str,
                            added_to_queue: int, pending_total: int, flushed: int}
        """
        if not usernames:
            return {"saved": 0, "duplicates": 0, "exported": 0, "export_file": None,
                    "added_to_queue": 0, "pending_total": 0, "flushed": 0}

        saved_count = 0
        duplicates = 0
        export_file = None
        added_to_queue = 0
        flushed = 0

        async with async_session_maker() as session:
            try:
                # Save to database using ON CONFLICT
                for username in usernames:
                    stmt = insert(DiscoveredLinkDB).values(
                        username=username,
                        discovered_from=discovered_from,
                        priority=priority,
                        source_type="analyzer",
                    )
                    stmt = stmt.on_conflict_do_nothing(index_elements=["username"])

                    result = await session.execute(stmt)
                    if result.rowcount > 0:
                        saved_count += 1
                    else:
                        duplicates += 1

                await session.commit()
                self._pending_count += saved_count

                if saved_count > 0:
                    logger.info(
                        f"Saved {saved_count} new links to DB "
                        f"(discovered_from: {discovered_from}, pending: {self._pending_count})"
                    )

                # Export to file if requested
                exported_count = 0
                if export_immediately and saved_count > 0:
                    export_file, exported_count = await self._export_pending_links(session)

                # Add to analyzer queue if enabled (hybrid mode)
                if add_to_analyzer and self.analyzer_queue and saved_count > 0:
                    try:
                        queue_stats = await self.analyzer_queue.add_discovered_links(
                            usernames=usernames,
                            priority=10,
                            check_analyzed=True,
                        )
                        added_to_queue = queue_stats["added"]

                        if added_to_queue > 0:
                            logger.info(
                                f"Added {added_to_queue} discovered links to analyzer queue "
                                f"(priority=10)"
                            )
                    except Exception as e:
                        logger.warning(f"Could not add links to analyzer queue: {e}")

                # Auto-flush to crawler if enabled and threshold reached
                # Note: By default disabled - use LinkSenderBackground instead
                if self.auto_flush_enabled and self._pending_count >= self.auto_flush_threshold:
                    flushed = await self.flush_to_crawler()

                return {
                    "saved": saved_count,
                    "duplicates": duplicates,
                    "exported": exported_count,
                    "export_file": export_file,
                    "added_to_queue": added_to_queue,
                    "pending_total": self._pending_count,
                    "flushed": flushed,
                }

            except Exception as e:
                logger.error(f"Error saving links: {e}")
                await session.rollback()
                return {"saved": 0, "duplicates": 0, "exported": 0, "export_file": None,
                        "added_to_queue": 0, "pending_total": 0, "flushed": 0}

    async def flush_to_crawler(self) -> int:
        """
        Send accumulated links (pending or exported) to crawler API in batches.

        Returns:
            Total number of links accepted by crawler
        """
        total_sent = 0

        # The external crawler webhook integration is not bundled with this
        # public build. Discovered links are still persisted to the database and
        # can be exported to files via export_batch(); pushing them to a crawler
        # is a no-op here.
        try:
            from services.crawler_webhook import submit_to_crawler  # type: ignore
        except ImportError:
            logger.info(
                "Crawler webhook integration not available; "
                "links remain in DB with status 'pending'/'exported'."
            )
            return 0

        async with async_session_maker() as session:
            while True:
                # Get batch of pending or exported links (not yet synced)
                stmt = select(DiscoveredLinkDB).where(
                    DiscoveredLinkDB.status.in_(["pending", "exported"])
                ).order_by(
                    DiscoveredLinkDB.priority.desc(),
                    DiscoveredLinkDB.discovered_at
                ).limit(self.batch_size)

                result = await session.execute(stmt)
                links = result.scalars().all()

                if not links:
                    break

                # Filter valid usernames
                valid_links = [(link.id, link.username) for link in links
                               if is_valid_username(link.username)]
                invalid_ids = [link.id for link in links
                               if not is_valid_username(link.username)]

                # Mark invalid as 'invalid' status
                if invalid_ids:
                    await session.execute(
                        update(DiscoveredLinkDB).where(
                            DiscoveredLinkDB.id.in_(invalid_ids)
                        ).values(status="invalid")
                    )
                    await session.commit()
                    logger.warning(f"Marked {len(invalid_ids)} invalid usernames")

                if not valid_links:
                    continue

                usernames = {username for _, username in valid_links}
                valid_ids = [id for id, _ in valid_links]

                try:
                    # Send to crawler
                    api_result = await submit_to_crawler(
                        usernames=usernames,
                        priority=0,
                        source="analyzer:batch",
                    )

                    # Mark as synced
                    await session.execute(
                        update(DiscoveredLinkDB).where(
                            DiscoveredLinkDB.id.in_(valid_ids)
                        ).values(
                            status="synced",
                            exported_at=datetime.utcnow(),
                        )
                    )
                    await session.commit()

                    total_sent += api_result.accepted
                    self._pending_count = max(0, self._pending_count - len(valid_links))

                    logger.info(
                        f"Flushed {len(valid_links)} links to crawler: "
                        f"accepted={api_result.accepted}, dupes={api_result.duplicates}, "
                        f"already_crawled={api_result.already_crawled}"
                    )

                except Exception as e:
                    logger.error(f"Error flushing to crawler: {e}")
                    await session.rollback()

                # If we got less than batch_size, we're done
                if len(links) < self.batch_size:
                    break

        if total_sent > 0:
            logger.info(f"Total flushed to crawler: {total_sent} links")

        return total_sent

    async def get_pending_count(self) -> int:
        """Get count of links waiting to be synced (pending or exported)."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(func.count(DiscoveredLinkDB.id)).where(
                    DiscoveredLinkDB.status.in_(["pending", "exported"])
                )
            )
            count = result.scalar() or 0
            self._pending_count = count
            return count

    async def _export_pending_links(
        self,
        session: AsyncSession,
        batch_size: int = 1000,
    ) -> tuple[Optional[str], int]:
        """
        Export pending links to file for crawler.

        Args:
            session: Database session
            batch_size: Max links per file

        Returns:
            Tuple of (filename, count)
        """
        try:
            # Get pending links
            stmt = select(DiscoveredLinkDB).where(
                DiscoveredLinkDB.status == "pending"
            ).order_by(
                DiscoveredLinkDB.priority.desc(),
                DiscoveredLinkDB.discovered_at
            ).limit(batch_size)

            result = await session.execute(stmt)
            links = result.scalars().all()

            if not links:
                return None, 0

            # Create export file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"links_{timestamp}.txt"
            filepath = self.export_dir / filename

            # Write links to file (one username per line)
            with open(filepath, "w", encoding="utf-8") as f:
                for link in links:
                    f.write(f"{link.username}\n")

            # Update status in DB
            link_ids = [link.id for link in links]
            await session.execute(
                DiscoveredLinkDB.__table__.update().where(
                    DiscoveredLinkDB.id.in_(link_ids)
                ).values(
                    status="exported",
                    exported_at=datetime.utcnow(),
                    export_file=filename,
                )
            )
            await session.commit()

            logger.info(f"Exported {len(links)} links to {filepath}")

            return filename, len(links)

        except Exception as e:
            logger.error(f"Error exporting links: {e}")
            return None, 0

    async def export_batch(self, batch_size: int = 1000) -> tuple[Optional[str], int]:
        """
        Export a batch of pending links to file.

        Args:
            batch_size: Max links per file

        Returns:
            Tuple of (filename, count)
        """
        async with async_session_maker() as session:
            return await self._export_pending_links(session, batch_size)

    async def get_stats(self) -> dict:
        """
        Get statistics about discovered links.

        Returns:
            Dict with counts by status
        """
        async with async_session_maker() as session:
            # Count by status
            stmt = select(
                DiscoveredLinkDB.status,
                DiscoveredLinkDB.id
            )
            result = await session.execute(stmt)
            links = result.all()

            stats = {"pending": 0, "exported": 0, "consumed": 0, "total": 0}
            for status, _ in links:
                stats[status] = stats.get(status, 0) + 1
                stats["total"] += 1

            return stats


# Global instance
_saver: Optional[LinkSaver] = None


async def get_link_saver(analyzer_queue: Optional["ChannelQueue"] = None) -> LinkSaver:
    """
    Get global LinkSaver instance.

    Args:
        analyzer_queue: Optional queue to set for hybrid mode (first call only)
    """
    global _saver
    if _saver is None:
        _saver = LinkSaver(analyzer_queue=analyzer_queue)
    return _saver


def set_global_analyzer_queue(queue: Optional["ChannelQueue"]) -> None:
    """
    Set analyzer queue for global LinkSaver instance.
    Call this at startup to enable hybrid mode.
    """
    global _saver
    if _saver is None:
        _saver = LinkSaver(analyzer_queue=queue)
    else:
        _saver.analyzer_queue = queue

    if queue:
        logger.info("Hybrid mode enabled: discovered links will be added to analyzer queue")


async def save_discovered_links(
    usernames: Set[str],
    discovered_from: str,
    priority: int = 0,
    export_immediately: bool = False,
    add_to_analyzer: bool = True,
) -> dict:
    """
    Convenience function to save links using global saver.
    Links are batched and sent to crawler when threshold is reached.

    Args:
        usernames: Set of channel/chat usernames
        discovered_from: Source description
        priority: Priority level
        export_immediately: Whether to export to file immediately
        add_to_analyzer: Whether to add to analyzer queue (if enabled)

    Returns:
        Dict with stats
    """
    saver = await get_link_saver()
    return await saver.save_links(
        usernames, discovered_from, priority,
        export_immediately, add_to_analyzer
    )


async def flush_links_to_crawler() -> int:
    """
    Flush all pending links to crawler API.
    Call this at end of scenario or periodically.

    Returns:
        Number of links accepted by crawler
    """
    saver = await get_link_saver()
    return await saver.flush_to_crawler()


async def get_pending_links_count() -> int:
    """Get count of pending links waiting to be sent to crawler."""
    saver = await get_link_saver()
    return await saver.get_pending_count()
