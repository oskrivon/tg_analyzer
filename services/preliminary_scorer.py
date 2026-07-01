"""
Preliminary Scorer - Phase 1 analysis with light requests.

Uses shared modules:
- ChannelAnalyzer for analysis logic
- CrawlerAPIClient for fetching channels
- RequestLogger for request tracking
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from sqlalchemy import select, update

from database.models import PreliminaryScoreDB, PreliminaryGroupScoreDB, AnalysisSessionDB
from database.connection import async_session_maker
from utils.proxy import parse_proxy
from services.channel_analyzer import ChannelAnalyzer, ChannelAnalysisResult
from services.crawler_api import CrawlerAPIClient
from services.request_logger import RequestLogger

logger = logging.getLogger(__name__)


class PreliminaryScorer:
    """
    Phase 1 scorer - light analysis with 3 requests per channel.

    Collects:
    - Channel info (get_entity + GetFullChannel)
    - Posts for engagement (GetMessages)

    Calculates preliminary score based on:
    - ERR (engagement rate)
    - Reach (views/subscribers)
    - Comments availability
    - Posting frequency
    - Subscriber count
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: str,
        proxy: Optional[str] = None,
        account_name: Optional[str] = None,
        posts_count: int = 50,
        request_delay: float = 0.5,
        crawler_api_url: str = os.getenv("CRAWLER_API_URL", "http://localhost:8000"),
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path
        self.proxy_str = proxy
        self.proxy = parse_proxy(proxy) if proxy else None
        self.account_name = account_name or session_path.split("/")[-1].split("\\")[-1].replace(".session", "")
        self.posts_count = posts_count
        self.request_delay = request_delay

        self.client: Optional[TelegramClient] = None
        self.analyzer: Optional[ChannelAnalyzer] = None
        self.request_logger = RequestLogger()
        self.crawler_api = CrawlerAPIClient(crawler_api_url)

        # Session tracking
        self.session_id = str(uuid.uuid4())[:8]

    async def connect(self):
        """Connect to Telegram."""
        self.client = TelegramClient(
            self.session_path,
            self.api_id,
            self.api_hash,
            proxy=self.proxy,
        )
        await self.client.connect()

        if not await self.client.is_user_authorized():
            raise RuntimeError(f"Session {self.session_path} is not authorized")

        me = await self.client.get_me()
        self.account_name = me.username or str(me.id)
        logger.info(f"Connected as {me.first_name} (@{self.account_name})")

        # Initialize analyzer
        self.analyzer = ChannelAnalyzer(
            client=self.client,
            account_name=self.account_name,
            request_logger=self.request_logger,
            request_delay=self.request_delay,
        )

        # Create session record in DB
        async with async_session_maker() as session:
            db_session = AnalysisSessionDB(
                session_id=self.session_id,
                account_name=self.account_name,
                started_at=datetime.utcnow(),
            )
            session.add(db_session)
            await session.commit()

    async def disconnect(self):
        """Disconnect and save session stats."""
        if self.client:
            await self.client.disconnect()

        # Update session record
        if self.analyzer:
            stats = self.analyzer.get_stats()
            async with async_session_maker() as session:
                await session.execute(
                    update(AnalysisSessionDB)
                    .where(AnalysisSessionDB.session_id == self.session_id)
                    .values(
                        total_requests=stats["request_count"],
                        channels_analyzed=stats["channels_analyzed"],
                        flood_wait_hit=stats["flood_wait_hit"],
                        flood_wait_at_request=stats["flood_wait_at_request"],
                        ended_at=datetime.utcnow(),
                        status="flood_wait" if stats["flood_wait_hit"] else "completed",
                    )
                )
                await session.commit()

        self.request_logger.close()
        await self.crawler_api.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def _calculate_channel_score(self, result: ChannelAnalysisResult) -> tuple[float, dict]:
        """
        Calculate preliminary score for CHANNELS (0-100).

        Components:
        - ERR (engagement rate): 25%
        - Reach (views/subs): 25%
        - Has comments: 20%
        - Posting frequency: 15%
        - Subscriber count: 15%
        """
        breakdown = {}
        data = result.to_dict()

        # ERR score (0-25)
        err = data.get("err") or 0
        if err >= 5:
            err_score = 25
        elif err >= 2:
            err_score = 20
        elif err >= 1:
            err_score = 15
        elif err >= 0.5:
            err_score = 10
        else:
            err_score = err * 20
        breakdown["err_score"] = round(err_score, 2)

        # Reach score (0-25)
        reach = data.get("reach") or 0
        if reach >= 50:
            reach_score = 25
        elif reach >= 30:
            reach_score = 20
        elif reach >= 20:
            reach_score = 15
        elif reach >= 10:
            reach_score = 10
        else:
            reach_score = reach / 2
        breakdown["reach_score"] = round(reach_score, 2)

        # Comments score (0-20)
        # Must have linked_chat AND actual comments to get points
        has_comments = data.get("has_linked_chat", False)
        avg_comments = data.get("avg_comments") or 0
        if has_comments and avg_comments > 10:
            comments_score = 20
        elif has_comments and avg_comments > 5:
            comments_score = 15
        elif has_comments and avg_comments > 0:
            comments_score = 10
        else:
            # No comments = no score (even if has_linked_chat)
            comments_score = 0
        breakdown["comments_score"] = comments_score

        # Posting frequency score (0-15)
        ppd = data.get("posts_per_day") or 0
        if 1 <= ppd <= 3:
            freq_score = 15
        elif 0.5 <= ppd < 1 or 3 < ppd <= 5:
            freq_score = 10
        elif 0.2 <= ppd < 0.5 or 5 < ppd <= 10:
            freq_score = 5
        else:
            freq_score = 0
        breakdown["frequency_score"] = freq_score

        # Subscriber score (0-15)
        subs = data.get("subscribers_api") or 0
        if subs >= 100000:
            subs_score = 15
        elif subs >= 50000:
            subs_score = 12
        elif subs >= 10000:
            subs_score = 10
        elif subs >= 5000:
            subs_score = 7
        elif subs >= 1000:
            subs_score = 5
        else:
            subs_score = 2
        breakdown["subscribers_score"] = subs_score

        total = err_score + reach_score + comments_score + freq_score + subs_score
        return round(total, 2), breakdown

    # Hard disqualification thresholds for groups
    MIN_UNIQUE_SENDERS = 3             # fewer than this = bot-only / channel-like
    MAX_TOP_SENDER_SHARE = 0.5         # one sender dominating > 50% = announcement-style

    def _calculate_group_score(self, result: ChannelAnalysisResult) -> tuple[float, dict]:
        """
        Calculate preliminary score for GROUPS (0-100).

        Components:
        - Activity (messages per day): 25%
        - Active users ratio: 25%
        - Online ratio: 20%
        - Group size: 15%
        - Has linked channel: 15%

        Hard disqualifications (return 0):
        - unique_senders < MIN_UNIQUE_SENDERS: messages are all from bots or the
          linked channel — no real humans writing, so the group is inactive.
        - top_sender_share > MAX_TOP_SENDER_SHARE: one sender dominates the
          sample — announcement-style group with little genuine discussion.
        """
        breakdown = {}
        data = result.to_dict()

        unique_senders = data.get("unique_senders") or 0
        top_share = data.get("top_sender_share")

        # Hard disqualifications — return 0 with a reason in breakdown.
        # Only apply when we have enough messages analyzed to trust the sample.
        if (data.get("messages_analyzed") or 0) >= 10:
            if unique_senders < self.MIN_UNIQUE_SENDERS:
                breakdown["disqualified"] = f"unique_senders={unique_senders} < {self.MIN_UNIQUE_SENDERS}"
                return 0.0, breakdown
            if top_share is not None and top_share > self.MAX_TOP_SENDER_SHARE:
                breakdown["disqualified"] = f"top_sender_share={top_share:.2f} > {self.MAX_TOP_SENDER_SHARE}"
                return 0.0, breakdown

        # Activity score (0-25) - messages per day
        mpd = data.get("messages_per_day") or 0
        if mpd >= 100:
            activity_score = 25
        elif mpd >= 50:
            activity_score = 20
        elif mpd >= 20:
            activity_score = 15
        elif mpd >= 10:
            activity_score = 10
        elif mpd >= 5:
            activity_score = 5
        else:
            activity_score = mpd / 2
        breakdown["activity_score"] = round(activity_score, 2)

        # Active users ratio score (0-25)
        aur = (data.get("active_users_ratio") or 0) * 100  # Convert to percentage
        if aur >= 10:
            aur_score = 25
        elif aur >= 5:
            aur_score = 20
        elif aur >= 2:
            aur_score = 15
        elif aur >= 1:
            aur_score = 10
        elif aur >= 0.5:
            aur_score = 5
        else:
            aur_score = aur * 10
        breakdown["active_users_score"] = round(aur_score, 2)

        # Online ratio score (0-20)
        online_ratio = (data.get("online_ratio") or 0) * 100  # Convert to percentage
        if online_ratio >= 5:
            online_score = 20
        elif online_ratio >= 3:
            online_score = 15
        elif online_ratio >= 1:
            online_score = 10
        elif online_ratio >= 0.5:
            online_score = 5
        else:
            online_score = online_ratio * 10
        breakdown["online_score"] = round(online_score, 2)

        # Group size score (0-15)
        participants = data.get("subscribers_api") or 0
        if participants >= 50000:
            size_score = 15
        elif participants >= 20000:
            size_score = 12
        elif participants >= 10000:
            size_score = 10
        elif participants >= 5000:
            size_score = 7
        elif participants >= 1000:
            size_score = 5
        else:
            size_score = 2
        breakdown["size_score"] = size_score

        # Linked channel score (0-15)
        has_linked = data.get("has_linked_channel", False)
        linked_score = 15 if has_linked else 0
        breakdown["linked_channel_score"] = linked_score

        total = activity_score + aur_score + online_score + size_score + linked_score
        return round(total, 2), breakdown

    async def save_channel_result(self, result: ChannelAnalysisResult, score: float, breakdown: dict):
        """Save CHANNEL analysis result to preliminary_scores table."""
        data = result.to_dict()

        async with async_session_maker() as session:
            existing = await session.execute(
                select(PreliminaryScoreDB).where(
                    PreliminaryScoreDB.username == result.username
                )
            )
            existing = existing.scalar_one_or_none()

            if existing:
                # Update existing record
                existing.telegram_id = data.get("telegram_id")
                existing.title = data.get("title")
                existing.subscribers_api = data.get("subscribers_api")
                existing.subscribers_crawler = data.get("subscribers_crawler")
                existing.has_linked_chat = data.get("has_linked_chat", False)
                existing.linked_chat_id = data.get("linked_chat_id")
                existing.posts_analyzed = data.get("posts_analyzed", 0)
                existing.avg_views = data.get("avg_views", 0)
                existing.avg_reactions = data.get("avg_reactions", 0)
                existing.avg_comments = data.get("avg_comments", 0)
                existing.avg_forwards = data.get("avg_forwards", 0)
                existing.err = data.get("err")
                existing.reach = data.get("reach")
                existing.posts_per_day = data.get("posts_per_day")
                existing.preliminary_score = score
                existing.score_breakdown = breakdown
                existing.status = data.get("status", "pending")
                existing.error_message = data.get("error_message")
                existing.account_used = self.account_name
                existing.requests_spent = data.get("requests_spent", 0)
                existing.analyzed_at = datetime.utcnow()
            else:
                # Create new record
                db_record = PreliminaryScoreDB(
                    username=result.username,
                    telegram_id=data.get("telegram_id"),
                    title=data.get("title"),
                    subscribers_api=data.get("subscribers_api"),
                    subscribers_crawler=data.get("subscribers_crawler"),
                    has_linked_chat=data.get("has_linked_chat", False),
                    linked_chat_id=data.get("linked_chat_id"),
                    posts_analyzed=data.get("posts_analyzed", 0),
                    avg_views=data.get("avg_views", 0),
                    avg_reactions=data.get("avg_reactions", 0),
                    avg_comments=data.get("avg_comments", 0),
                    avg_forwards=data.get("avg_forwards", 0),
                    err=data.get("err"),
                    reach=data.get("reach"),
                    posts_per_day=data.get("posts_per_day"),
                    preliminary_score=score,
                    score_breakdown=breakdown,
                    status=data.get("status", "pending"),
                    error_message=data.get("error_message"),
                    account_used=self.account_name,
                    requests_spent=data.get("requests_spent", 0),
                    analyzed_at=datetime.utcnow(),
                )
                session.add(db_record)

            await session.commit()

    async def save_group_result(self, result: ChannelAnalysisResult, score: float, breakdown: dict):
        """Save GROUP analysis result to preliminary_group_scores table."""
        data = result.to_dict()

        async with async_session_maker() as session:
            existing = await session.execute(
                select(PreliminaryGroupScoreDB).where(
                    PreliminaryGroupScoreDB.username == result.username
                )
            )
            existing = existing.scalar_one_or_none()

            if existing:
                # Update existing record
                existing.telegram_id = data.get("telegram_id")
                existing.title = data.get("title")
                existing.participants_count = data.get("subscribers_api")
                existing.participants_crawler = data.get("subscribers_crawler")
                existing.is_megagroup = data.get("is_megagroup", True)
                existing.is_gigagroup = data.get("is_gigagroup", False)
                existing.has_linked_channel = data.get("has_linked_channel", False)
                existing.linked_channel_id = data.get("linked_channel_id")
                existing.slowmode_seconds = data.get("slowmode_seconds")
                existing.messages_analyzed = data.get("messages_analyzed", 0)
                existing.unique_senders = data.get("unique_senders", 0)
                existing.messages_per_day = data.get("messages_per_day")
                existing.active_users_ratio = data.get("active_users_ratio")
                existing.top_sender_share = data.get("top_sender_share")
                existing.online_count = data.get("online_count")
                existing.online_ratio = data.get("online_ratio")
                existing.preliminary_score = score
                existing.score_breakdown = breakdown
                existing.status = data.get("status", "pending")
                existing.error_message = data.get("error_message")
                existing.account_used = self.account_name
                existing.requests_spent = data.get("requests_spent", 0)
                existing.analyzed_at = datetime.utcnow()
            else:
                # Create new record
                db_record = PreliminaryGroupScoreDB(
                    username=result.username,
                    telegram_id=data.get("telegram_id"),
                    title=data.get("title"),
                    participants_count=data.get("subscribers_api"),
                    participants_crawler=data.get("subscribers_crawler"),
                    is_megagroup=data.get("is_megagroup", True),
                    is_gigagroup=data.get("is_gigagroup", False),
                    has_linked_channel=data.get("has_linked_channel", False),
                    linked_channel_id=data.get("linked_channel_id"),
                    slowmode_seconds=data.get("slowmode_seconds"),
                    messages_analyzed=data.get("messages_analyzed", 0),
                    unique_senders=data.get("unique_senders", 0),
                    messages_per_day=data.get("messages_per_day"),
                    active_users_ratio=data.get("active_users_ratio"),
                    top_sender_share=data.get("top_sender_share"),
                    online_count=data.get("online_count"),
                    online_ratio=data.get("online_ratio"),
                    preliminary_score=score,
                    score_breakdown=breakdown,
                    status=data.get("status", "pending"),
                    error_message=data.get("error_message"),
                    account_used=self.account_name,
                    requests_spent=data.get("requests_spent", 0),
                    analyzed_at=datetime.utcnow(),
                )
                session.add(db_record)

            await session.commit()

    async def run(
        self,
        limit: int = 100,
        min_subs: Optional[int] = None,
        max_subs: Optional[int] = None,
        max_requests: int = 200,
    ):
        """
        Run preliminary scoring on channels from crawler API.

        Args:
            limit: Number of channels to fetch
            min_subs: Minimum subscribers filter
            max_subs: Maximum subscribers filter
            max_requests: Stop after this many requests (flood limit safety)
        """
        logger.info(f"Starting preliminary scoring session {self.session_id}")
        logger.info(f"Account: {self.account_name}, max_requests: {max_requests}")

        # Fetch channels
        channels = await self.crawler_api.get_channels_paginated(
            total_limit=limit,
            min_subs=min_subs,
            max_subs=max_subs,
        )
        logger.info(f"Fetched {len(channels)} channels from crawler API")

        for channel in channels:
            # Check limits
            if self.analyzer.request_count >= max_requests - 3:
                logger.warning(f"Approaching request limit ({self.analyzer.request_count}/{max_requests}), stopping")
                break

            if self.analyzer.flood_wait_hit:
                logger.error("Flood wait hit, stopping")
                break

            username = channel.get("username")
            if not username:
                continue

            logger.info(f"Analyzing @{username} (request #{self.analyzer.request_count + 1})")

            try:
                result = await self.analyzer.analyze(
                    username=username,
                    subscribers_crawler=channel.get("subscribers", 0),
                    posts_count=self.posts_count,
                )

                # Route to appropriate scoring and storage based on entity type
                if result.entity_type == "channel":
                    score, breakdown = self._calculate_channel_score(result)
                    await self.save_channel_result(result, score, breakdown)
                elif result.entity_type == "group":
                    score, breakdown = self._calculate_group_score(result)
                    await self.save_group_result(result, score, breakdown)
                else:
                    # Unknown type - save as channel by default
                    score, breakdown = self._calculate_channel_score(result)
                    await self.save_channel_result(result, score, breakdown)

                if result.status == "analyzed":
                    data = result.to_dict()
                    if result.entity_type == "channel":
                        logger.info(
                            f"  [CHANNEL] Score: {score:.1f}, "
                            f"ERR: {data.get('err', 0):.2f}%, "
                            f"Reach: {data.get('reach', 0):.1f}%, "
                            f"Comments: {'Yes' if data.get('has_linked_chat') else 'No'}"
                        )
                    else:
                        logger.info(
                            f"  [GROUP] Score: {score:.1f}, "
                            f"Msgs/day: {data.get('messages_per_day', 0):.1f}, "
                            f"Active: {(data.get('active_users_ratio', 0) or 0) * 100:.2f}%, "
                            f"Online: {data.get('online_count', 0) or 'N/A'}"
                        )
                else:
                    logger.warning(f"  Status: {result.status}, {result.error_message or ''}")

            except FloodWaitError:
                break

            await asyncio.sleep(self.request_delay)

        stats = self.analyzer.get_stats()
        logger.info(
            f"Session complete. Requests: {stats['request_count']}, "
            f"Channels: {stats['channels_analyzed']}, "
            f"FloodWait: {stats['flood_wait_hit']}"
        )
