"""Channel analysis logic - single source of truth."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, ChannelFull
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

from utils.metrics import calculate_engagement_metrics, extract_post_stats, EngagementMetrics
from services.request_logger import RequestLogger
from utils.link_extractor import extract_from_messages
from services.link_saver import save_discovered_links
from services.entity_saver import save_discovered_entity
import config

logger = logging.getLogger(__name__)


# Telegram API errors that indicate channel is inaccessible
CHANNEL_ACCESS_ERRORS = (
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)


@dataclass
class ChannelAnalysisResult:
    """Result of channel/group analysis."""
    username: str
    status: str = "pending"  # pending, analyzed, error, flood_wait
    error_message: Optional[str] = None
    requests_spent: int = 0

    # Whether get_entity succeeded (Telegram counts this for flood limit!)
    # True = entity found (channel, group, bot, or user)
    # False = username not found or invalid
    entity_resolved: bool = False

    # Entity type: 'channel' or 'group'
    entity_type: str = "unknown"  # channel, group, unknown

    # Channel/Group info
    telegram_id: Optional[int] = None
    title: Optional[str] = None
    about: Optional[str] = None  # Description from GetFullChannel
    subscribers_api: Optional[int] = None  # participants_count for groups
    subscribers_crawler: Optional[int] = None
    has_linked_chat: bool = False  # For channels: linked discussion group
    linked_chat_id: Optional[int] = None
    has_linked_channel: bool = False  # For groups: linked channel
    linked_channel_id: Optional[int] = None

    # Keyword-based category detection (free, no LLM)
    detected_category: Optional[str] = None
    category_confidence: Optional[float] = None  # 0-1

    # Group-specific flags
    is_megagroup: bool = False
    is_gigagroup: bool = False
    slowmode_seconds: Optional[int] = None

    # Engagement metrics (for channels)
    metrics: Optional[EngagementMetrics] = None

    # Group activity metrics
    messages_analyzed: int = 0
    unique_senders: int = 0
    messages_per_day: Optional[float] = None
    active_users_ratio: Optional[float] = None
    online_count: Optional[int] = None
    online_ratio: Optional[float] = None
    top_sender_share: Optional[float] = None  # share of msgs from the most active sender (0-1)

    # Discovered links
    links_discovered: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        result = {
            "username": self.username,
            "status": self.status,
            "error_message": self.error_message,
            "requests_spent": self.requests_spent,
            "entity_resolved": self.entity_resolved,
            "entity_type": self.entity_type,
            "telegram_id": self.telegram_id,
            "title": self.title,
            "about": self.about,
            "subscribers_api": self.subscribers_api,
            "subscribers_crawler": self.subscribers_crawler,
            # Keyword-based category
            "detected_category": self.detected_category,
            "category_confidence": self.category_confidence,
            # Channel-specific
            "has_linked_chat": self.has_linked_chat,
            "linked_chat_id": self.linked_chat_id,
            # Group-specific
            "has_linked_channel": self.has_linked_channel,
            "linked_channel_id": self.linked_channel_id,
            "is_megagroup": self.is_megagroup,
            "is_gigagroup": self.is_gigagroup,
            "slowmode_seconds": self.slowmode_seconds,
            # Group activity
            "messages_analyzed": self.messages_analyzed,
            "unique_senders": self.unique_senders,
            "messages_per_day": self.messages_per_day,
            "active_users_ratio": self.active_users_ratio,
            "online_count": self.online_count,
            "online_ratio": self.online_ratio,
            "top_sender_share": self.top_sender_share,
            "links_discovered": self.links_discovered,
        }
        if self.metrics:
            result.update({
                "posts_analyzed": self.metrics.posts_analyzed,
                "avg_views": self.metrics.avg_views,
                "avg_reactions": self.metrics.avg_reactions,
                "avg_comments": self.metrics.avg_comments,
                "avg_forwards": self.metrics.avg_forwards,
                "err": self.metrics.err,
                "reach": self.metrics.reach,
                "posts_per_day": self.metrics.posts_per_day,
            })
        return result


class ChannelAnalyzer:
    """
    Analyzes Telegram channels with request tracking and logging.

    Usage:
        analyzer = ChannelAnalyzer(client, "account_name")
        result = await analyzer.analyze("@channel_username", posts_count=50)
    """

    def __init__(
        self,
        client: TelegramClient,
        account_name: str,
        request_logger: Optional[RequestLogger] = None,
        request_delay: float = 0.5,
    ):
        self.client = client
        self.account_name = account_name
        self.request_logger = request_logger
        self.request_delay = request_delay

        # Tracking
        self.request_count = 0
        self.channels_analyzed = 0
        self.flood_wait_hit = False
        self.flood_wait_at_request: Optional[int] = None

    async def _api_call(
        self,
        method_name: str,
        channel: str,
        coro,
        timeout: Optional[float] = None,
    ):
        """
        Execute API call with logging, tracking, and timeout.

        Args:
            method_name: Name of the API method for logging
            channel: Channel/username for logging
            coro: Coroutine to execute
            timeout: Timeout in seconds (default from config.TELEGRAM_API_TIMEOUT)

        Raises:
            FloodWaitError: To caller for handling
            asyncio.TimeoutError: If timeout exceeded
        """
        if timeout is None:
            timeout = config.TELEGRAM_API_TIMEOUT

        self.request_count += 1
        start_time = datetime.now()

        try:
            result = await asyncio.wait_for(coro, timeout=timeout)
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if self.request_logger:
                self.request_logger.log(
                    account=self.account_name,
                    method=method_name,
                    channel=channel,
                    success=True,
                    duration_ms=duration_ms,
                    request_num=self.request_count,
                )

            return result

        except FloodWaitError as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self.flood_wait_hit = True
            self.flood_wait_at_request = self.request_count

            if self.request_logger:
                self.request_logger.log(
                    account=self.account_name,
                    method=method_name,
                    channel=channel,
                    success=False,
                    duration_ms=duration_ms,
                    request_num=self.request_count,
                    error="FloodWaitError",
                    wait_seconds=e.seconds,
                )

            logger.error(f"FloodWait! Request #{self.request_count}, wait {e.seconds}s")
            raise

        except asyncio.TimeoutError:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if self.request_logger:
                self.request_logger.log(
                    account=self.account_name,
                    method=method_name,
                    channel=channel,
                    success=False,
                    duration_ms=duration_ms,
                    request_num=self.request_count,
                    error="TimeoutError",
                )

            logger.warning(f"Timeout on {method_name} for @{channel} after {timeout}s")
            raise

        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if self.request_logger:
                self.request_logger.log(
                    account=self.account_name,
                    method=method_name,
                    channel=channel,
                    success=False,
                    duration_ms=duration_ms,
                    request_num=self.request_count,
                    error=type(e).__name__,
                )
            raise

    async def analyze(
        self,
        username: str,
        subscribers_crawler: int = 0,
        posts_count: int = 50,
    ) -> ChannelAnalysisResult:
        """
        Analyze a single channel or group.

        Makes 3 API requests:
        1. get_entity - resolve username
        2. GetFullChannel - get channel/group info
        3. get_messages - get recent posts/messages

        Args:
            username: Channel/group username (with or without @)
            subscribers_crawler: Subscriber count from crawler (for comparison)
            posts_count: Number of posts/messages to fetch

        Returns:
            ChannelAnalysisResult with all collected data
        """
        username = username.lstrip("@")
        result = ChannelAnalysisResult(
            username=username,
            subscribers_crawler=subscribers_crawler,
        )

        try:
            # Request 1: get_entity
            entity = await self._api_call(
                "get_entity",
                username,
                self.client.get_entity(username),
            )
            result.requests_spent += 1
            # IMPORTANT: entity_resolved=True means Telegram found this username
            # This counts towards flood limit even if it's a bot/user (not channel)!
            result.entity_resolved = True
            await asyncio.sleep(self.request_delay)

            # Check if entity is a channel/group or a user/bot
            # Users and bots cannot be analyzed with GetFullChannel
            from telethon.tl.types import User, Channel as TgChannel
            if isinstance(entity, User):
                # It's a user or bot - save to discovered_entities for deduplication
                is_bot = getattr(entity, "bot", False)
                entity_type = "bot" if is_bot else "user"

                # Save asynchronously (don't wait)
                asyncio.create_task(
                    save_discovered_entity(
                        username=username,
                        telegram_id=entity.id,
                        entity_type=entity_type,
                        first_name=getattr(entity, "first_name", None),
                        last_name=getattr(entity, "last_name", None),
                        is_verified=getattr(entity, "verified", False),
                        is_premium=getattr(entity, "premium", False),
                        discovered_from=f"analyzer:{self.account_name}",
                    )
                )

                result.status = "error"
                result.error_message = f"Not a channel/group: {entity_type}"
                result.entity_type = entity_type
                result.telegram_id = entity.id
                logger.debug(f"@{username} is a {entity_type}, saved to discovered_entities")
                return result

            # Request 2: GetFullChannel
            full_result = await self._api_call(
                "GetFullChannel",
                username,
                self.client(GetFullChannelRequest(entity)),
            )
            result.requests_spent += 1

            full_chat: ChannelFull = full_result.full_chat
            chat: Channel = full_result.chats[0]

            # Determine entity type
            if getattr(chat, "broadcast", False):
                result.entity_type = "channel"
            elif getattr(chat, "megagroup", False) or getattr(chat, "gigagroup", False):
                result.entity_type = "group"
            else:
                result.entity_type = "unknown"

            # Common fields
            result.telegram_id = chat.id
            result.title = chat.title
            result.about = getattr(full_chat, "about", None)
            result.subscribers_api = getattr(full_chat, "participants_count", 0) or 0

            # Keyword-based category detection (free, no LLM required)
            if result.about or result.title:
                from services.category_detector import detect_category
                category, confidence = detect_category(result.about or "", result.title or "")
                if category:
                    result.detected_category = category
                    result.category_confidence = confidence
                    logger.debug(f"[@{username}] Detected category: {category} (confidence: {confidence})")

            # Group-specific fields
            result.is_megagroup = getattr(chat, "megagroup", False)
            result.is_gigagroup = getattr(chat, "gigagroup", False)
            result.slowmode_seconds = getattr(full_chat, "slowmode_seconds", None)

            # Linked chat/channel
            linked_chat_id = getattr(full_chat, "linked_chat_id", None)
            if result.entity_type == "channel":
                result.has_linked_chat = bool(linked_chat_id)
                result.linked_chat_id = linked_chat_id
            else:  # group
                result.has_linked_channel = bool(linked_chat_id)
                result.linked_channel_id = linked_chat_id

            # Online count (for groups, if available)
            result.online_count = getattr(full_chat, "online_count", None)
            if result.online_count and result.subscribers_api:
                result.online_ratio = result.online_count / result.subscribers_api

            await asyncio.sleep(self.request_delay)

            # Request 3: get_messages
            messages = await self._api_call(
                "get_messages",
                username,
                self.client.get_messages(entity, limit=posts_count),
            )
            result.requests_spent += 1

            # Extract Telegram links from messages (free bonus!)
            try:
                discovered_links = extract_from_messages(messages)
                if discovered_links:
                    result.links_discovered = len(discovered_links)
                    # Save to own DB + export to file asynchronously (don't wait)
                    asyncio.create_task(
                        save_discovered_links(
                            discovered_links,
                            discovered_from=f"analyzer:{username}",
                            priority=0,
                            export_immediately=True,
                        )
                    )
                    logger.info(f"[{username}] Discovered {len(discovered_links)} channel/chat links")
            except Exception as e:
                logger.warning(f"[{username}] Error extracting links: {e}")

            if result.entity_type == "channel":
                # Channel: calculate engagement metrics (views, reactions, forwards)
                posts_stats = [extract_post_stats(msg) for msg in messages]
                posts_stats = [p for p in posts_stats if p is not None]

                if posts_stats:
                    result.metrics = calculate_engagement_metrics(
                        posts_stats,
                        subscribers=result.subscribers_api or 0,
                    )
            else:
                # Group: calculate activity metrics (messages, unique senders)
                result.messages_analyzed = len(messages)

                # Count messages per sender to compute unique_senders
                # and top_sender_share (detects announcement-style groups)
                from collections import Counter
                sender_counts: Counter = Counter()
                first_msg_date = None
                last_msg_date = None

                for msg in messages:
                    if hasattr(msg, "from_id") and msg.from_id:
                        sender_id = getattr(msg.from_id, "user_id", None)
                        if sender_id:
                            sender_counts[sender_id] += 1
                    if hasattr(msg, "date") and msg.date:
                        if first_msg_date is None or msg.date < first_msg_date:
                            first_msg_date = msg.date
                        if last_msg_date is None or msg.date > last_msg_date:
                            last_msg_date = msg.date

                result.unique_senders = len(sender_counts)

                # top_sender_share: share of messages from the most active sender
                # among messages that had an attributable user sender. Close to 1
                # means one person dominates (announcement-style) — i.e. low
                # genuine multi-user discussion.
                total_attributed = sum(sender_counts.values())
                if total_attributed > 0:
                    result.top_sender_share = max(sender_counts.values()) / total_attributed

                # Calculate messages per day
                if first_msg_date and last_msg_date and first_msg_date != last_msg_date:
                    days_span = (last_msg_date - first_msg_date).total_seconds() / 86400
                    if days_span > 0:
                        result.messages_per_day = result.messages_analyzed / days_span

                # Calculate active users ratio
                if result.subscribers_api and result.subscribers_api > 0:
                    result.active_users_ratio = result.unique_senders / result.subscribers_api

            result.status = "analyzed"
            self.channels_analyzed += 1

        except FloodWaitError:
            result.status = "flood_wait"
            result.error_message = f"FloodWait at request #{self.request_count}"
            raise

        except CHANNEL_ACCESS_ERRORS as e:
            result.status = "error"
            result.error_message = type(e).__name__

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)
            logger.exception(f"Error analyzing @{username}")

        return result

    def get_stats(self) -> dict:
        """Get current session statistics."""
        return {
            "request_count": self.request_count,
            "channels_analyzed": self.channels_analyzed,
            "flood_wait_hit": self.flood_wait_hit,
            "flood_wait_at_request": self.flood_wait_at_request,
        }
