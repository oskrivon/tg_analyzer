"""
LLM Content Analyzer service.

Uses Claude API to analyze Telegram channel/group content for:
- Thematic classification (category, topics)
- Sentiment analysis (tone, propaganda)
- Quality scoring (originality, informativeness)
- Toxicity detection (hate speech, misinformation)
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from telethon import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors import (
    FloodWaitError,
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from sqlalchemy import select, and_

from database.models import LLMAnalysisDB, PreliminaryScoreDB, PreliminaryGroupScoreDB
from database.connection import async_session_maker
from services.llm_client import LLMClient
from services.link_saver import save_discovered_links
from utils.llm_prompts import (
    LLMAnalysisInput,
    PostContent,
    build_analysis_prompt,
    estimate_tokens,
)
from utils.link_extractor import extract_all_links_from_message

logger = logging.getLogger(__name__)


CHANNEL_ACCESS_ERRORS = (
    ChannelPrivateError,
    ChannelInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)


@dataclass
class LLMAnalysisResult:
    """Result of LLM analysis."""
    username: str
    entity_type: str = "channel"
    status: str = "pending"  # pending, completed, error
    error_message: Optional[str] = None

    # Thematic
    primary_category: Optional[str] = None
    secondary_categories: list = None
    topics: list = None
    category_scores: dict = None

    # Sentiment
    overall_sentiment: Optional[float] = None
    sentiment_label: Optional[str] = None
    emotional_tone: Optional[str] = None
    propaganda_score: Optional[float] = None

    # Quality (0-100)
    quality_score: Optional[float] = None
    originality_score: Optional[float] = None
    informativeness_score: Optional[float] = None
    professionalism_score: Optional[float] = None
    engagement_authenticity: Optional[float] = None

    # Toxicity (0-100)
    toxicity_score: Optional[float] = None
    hate_speech_score: Optional[float] = None
    harassment_score: Optional[float] = None
    misinformation_risk: Optional[float] = None
    adult_content_score: Optional[float] = None
    violence_score: Optional[float] = None
    toxicity_flags: list = None

    # Metadata
    full_analysis: dict = None
    posts_analyzed: int = 0
    links_discovered: int = 0  # Number of Telegram links found in posts
    model_used: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0

    def __post_init__(self):
        if self.secondary_categories is None:
            self.secondary_categories = []
        if self.topics is None:
            self.topics = []
        if self.category_scores is None:
            self.category_scores = {}
        if self.toxicity_flags is None:
            self.toxicity_flags = []
        if self.full_analysis is None:
            self.full_analysis = {}


class LLMAnalyzer:
    """
    Analyzes Telegram channel/group content using Claude API.

    Usage:
        analyzer = LLMAnalyzer(telegram_client, llm_client)
        result = await analyzer.analyze_channel("username", posts_count=20)
    """

    def __init__(
        self,
        telegram_client: Optional[TelegramClient] = None,
        llm_client: Optional[LLMClient] = None,
        request_delay: float = 0.5,
        max_posts: int = 20,
        max_chars_per_post: int = 500,
    ):
        self.telegram_client = telegram_client
        self.llm_client = llm_client or LLMClient()
        self.request_delay = request_delay
        self.max_posts = max_posts
        self.max_chars_per_post = max_chars_per_post

        # Stats
        self.channels_analyzed = 0
        self.flood_wait_hit = False

    async def fetch_channel_data(
        self,
        username: str,
        posts_count: int = 20,
    ) -> Optional[LLMAnalysisInput]:
        """
        Fetch channel/group data from Telegram.

        Args:
            username: Channel username (without @)
            posts_count: Number of posts to fetch

        Returns:
            LLMAnalysisInput with channel data, or None if error
        """
        if not self.telegram_client:
            raise ValueError("Telegram client not provided")

        username = username.lstrip("@")

        try:
            # Get entity
            entity = await self.telegram_client.get_entity(username)
            await asyncio.sleep(self.request_delay)

            # Get full channel info
            full_result = await self.telegram_client(GetFullChannelRequest(entity))
            await asyncio.sleep(self.request_delay)

            full_chat = full_result.full_chat
            chat = full_result.chats[0]

            # Determine entity type
            if getattr(chat, "broadcast", False):
                entity_type = "channel"
            else:
                entity_type = "group"

            # Get messages
            messages = await self.telegram_client.get_messages(entity, limit=posts_count)

            # Extract posts with text and discover links
            posts = []
            total_views = 0
            total_reactions = 0
            total_comments = 0
            discovered_links = set()

            for msg in messages:
                if not msg or not hasattr(msg, "message") or not msg.message:
                    continue

                text = msg.message.strip()
                if not text or len(text) < 10:  # Skip very short messages
                    continue

                # Extract Telegram links from this message
                msg_links = extract_all_links_from_message(msg)
                discovered_links.update(msg_links)

                views = getattr(msg, "views", 0) or 0
                reactions_count = 0
                if hasattr(msg, "reactions") and msg.reactions:
                    for r in getattr(msg.reactions, "results", []):
                        reactions_count += getattr(r, "count", 0)
                comments = 0
                if hasattr(msg, "replies") and msg.replies:
                    comments = getattr(msg.replies, "replies", 0) or 0

                posts.append(PostContent(
                    text=text[:self.max_chars_per_post],
                    views=views,
                    reactions=reactions_count,
                    comments=comments,
                ))

                total_views += views
                total_reactions += reactions_count
                total_comments += comments

                if len(posts) >= self.max_posts:
                    break

            if not posts:
                logger.warning(f"No posts with text found for @{username}")
                return None

            # Save discovered links
            if discovered_links:
                logger.info(f"[{username}] Discovered {len(discovered_links)} channel/chat links")
                try:
                    await save_discovered_links(
                        usernames=discovered_links,
                        discovered_from=f"llm_analyzer:{username}",
                        priority=0,
                        export_immediately=True,
                        add_to_analyzer=True,
                    )
                except Exception as e:
                    logger.warning(f"[{username}] Failed to save discovered links: {e}")

            # Calculate averages
            avg_views = total_views // len(posts) if posts else 0
            avg_reactions = total_reactions // len(posts) if posts else 0
            avg_comments = total_comments // len(posts) if posts else 0

            input_data = LLMAnalysisInput(
                username=username,
                entity_type=entity_type,
                title=chat.title,
                description=getattr(full_chat, "about", None),
                subscribers=getattr(full_chat, "participants_count", 0) or 0,
                posts=posts,
                avg_views=avg_views,
                avg_reactions=avg_reactions,
                avg_comments=avg_comments,
            )

            # Store discovered links count for tracking
            input_data._discovered_links_count = len(discovered_links)

            return input_data

        except CHANNEL_ACCESS_ERRORS as e:
            logger.warning(f"Cannot access @{username}: {type(e).__name__}")
            return None
        except FloodWaitError as e:
            logger.error(f"FloodWait for {e.seconds}s while fetching @{username}")
            self.flood_wait_hit = True
            raise
        except Exception as e:
            logger.exception(f"Error fetching @{username}: {e}")
            return None

    def analyze_content(self, input_data: LLMAnalysisInput) -> LLMAnalysisResult:
        """
        Analyze content using Claude API (synchronous).

        Args:
            input_data: Channel data with posts

        Returns:
            LLMAnalysisResult with all scores
        """
        result = LLMAnalysisResult(
            username=input_data.username,
            entity_type=input_data.entity_type,
            posts_analyzed=len(input_data.posts),
        )

        try:
            # Build prompts
            system_prompt, user_prompt = build_analysis_prompt(input_data)

            # Estimate tokens
            estimated_tokens = estimate_tokens(input_data)
            logger.debug(f"Estimated tokens: {estimated_tokens}")

            # Call LLM
            llm_response = self.llm_client.analyze(system_prompt, user_prompt)

            result.tokens_used = llm_response.total_tokens
            result.cost_usd = llm_response.cost_usd
            result.model_used = llm_response.model

            if not llm_response.success:
                result.status = "error"
                result.error_message = llm_response.error
                return result

            if not llm_response.parsed_json:
                result.status = "error"
                result.error_message = "Failed to parse JSON response"
                result.full_analysis = {"raw_response": llm_response.content}
                return result

            # Extract data from parsed JSON
            data = llm_response.parsed_json
            result.full_analysis = data

            # Thematic
            thematic = data.get("thematic", {})
            result.primary_category = thematic.get("primary_category")
            result.secondary_categories = thematic.get("secondary_categories", [])
            result.topics = thematic.get("topics", [])
            result.category_scores = thematic.get("category_scores", {})

            # Sentiment
            sentiment = data.get("sentiment", {})
            result.overall_sentiment = sentiment.get("overall_sentiment")
            result.sentiment_label = sentiment.get("sentiment_label")
            result.emotional_tone = sentiment.get("emotional_tone")
            result.propaganda_score = sentiment.get("propaganda_score")

            # Quality
            quality = data.get("quality", {})
            result.quality_score = quality.get("quality_score")
            result.originality_score = quality.get("originality_score")
            result.informativeness_score = quality.get("informativeness_score")
            result.professionalism_score = quality.get("professionalism_score")
            result.engagement_authenticity = quality.get("engagement_authenticity")

            # Toxicity
            toxicity = data.get("toxicity", {})
            result.toxicity_score = toxicity.get("toxicity_score")
            result.hate_speech_score = toxicity.get("hate_speech_score")
            result.harassment_score = toxicity.get("harassment_score")
            result.misinformation_risk = toxicity.get("misinformation_risk")
            result.adult_content_score = toxicity.get("adult_content_score")
            result.violence_score = toxicity.get("violence_score")
            result.toxicity_flags = toxicity.get("toxicity_flags", [])

            result.status = "completed"

        except Exception as e:
            logger.exception(f"Error analyzing content: {e}")
            result.status = "error"
            result.error_message = str(e)

        return result

    async def analyze_channel(
        self,
        username: str,
        posts_count: int = 20,
    ) -> LLMAnalysisResult:
        """
        Full analysis: fetch from Telegram + analyze with LLM.

        Args:
            username: Channel username
            posts_count: Number of posts to analyze

        Returns:
            LLMAnalysisResult with all analysis data
        """
        result = LLMAnalysisResult(username=username)

        # Fetch data from Telegram
        input_data = await self.fetch_channel_data(username, posts_count)

        if not input_data:
            result.status = "error"
            result.error_message = "Failed to fetch channel data"
            return result

        # Analyze with LLM
        result = self.analyze_content(input_data)

        # Add discovered links count
        if hasattr(input_data, '_discovered_links_count'):
            result.links_discovered = input_data._discovered_links_count

        self.channels_analyzed += 1

        return result

    async def save_result(self, result: LLMAnalysisResult):
        """Save analysis result to database."""
        async with async_session_maker() as session:
            # Check if exists
            existing = await session.execute(
                select(LLMAnalysisDB).where(LLMAnalysisDB.username == result.username)
            )
            existing = existing.scalar_one_or_none()

            if existing:
                # Update
                existing.entity_type = result.entity_type
                existing.primary_category = result.primary_category
                existing.secondary_categories = result.secondary_categories
                existing.topics = result.topics
                existing.category_scores = result.category_scores
                existing.overall_sentiment = result.overall_sentiment
                existing.sentiment_label = result.sentiment_label
                existing.emotional_tone = result.emotional_tone
                existing.propaganda_score = result.propaganda_score
                existing.quality_score = result.quality_score
                existing.originality_score = result.originality_score
                existing.informativeness_score = result.informativeness_score
                existing.professionalism_score = result.professionalism_score
                existing.engagement_authenticity = result.engagement_authenticity
                existing.toxicity_score = result.toxicity_score
                existing.hate_speech_score = result.hate_speech_score
                existing.harassment_score = result.harassment_score
                existing.misinformation_risk = result.misinformation_risk
                existing.adult_content_score = result.adult_content_score
                existing.violence_score = result.violence_score
                existing.toxicity_flags = result.toxicity_flags
                existing.full_analysis = result.full_analysis
                existing.posts_analyzed = result.posts_analyzed
                existing.model_used = result.model_used
                existing.tokens_used = result.tokens_used
                existing.cost_usd = result.cost_usd
                existing.status = result.status
                existing.error_message = result.error_message
                existing.analyzed_at = datetime.utcnow()
            else:
                # Create new
                db_record = LLMAnalysisDB(
                    username=result.username,
                    entity_type=result.entity_type,
                    primary_category=result.primary_category,
                    secondary_categories=result.secondary_categories,
                    topics=result.topics,
                    category_scores=result.category_scores,
                    overall_sentiment=result.overall_sentiment,
                    sentiment_label=result.sentiment_label,
                    emotional_tone=result.emotional_tone,
                    propaganda_score=result.propaganda_score,
                    quality_score=result.quality_score,
                    originality_score=result.originality_score,
                    informativeness_score=result.informativeness_score,
                    professionalism_score=result.professionalism_score,
                    engagement_authenticity=result.engagement_authenticity,
                    toxicity_score=result.toxicity_score,
                    hate_speech_score=result.hate_speech_score,
                    harassment_score=result.harassment_score,
                    misinformation_risk=result.misinformation_risk,
                    adult_content_score=result.adult_content_score,
                    violence_score=result.violence_score,
                    toxicity_flags=result.toxicity_flags,
                    full_analysis=result.full_analysis,
                    posts_analyzed=result.posts_analyzed,
                    model_used=result.model_used,
                    tokens_used=result.tokens_used,
                    cost_usd=result.cost_usd,
                    status=result.status,
                    error_message=result.error_message,
                    analyzed_at=datetime.utcnow(),
                )
                session.add(db_record)

            await session.commit()

    async def get_channels_for_analysis(
        self,
        limit: int = 100,
        min_score: float = 50.0,
        entity_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Get channels/groups that need LLM analysis.

        Fetches from preliminary_scores and preliminary_group_scores tables
        where LLM analysis hasn't been done yet.

        Args:
            limit: Maximum number of channels to return
            min_score: Minimum preliminary score threshold
            entity_type: Filter by type ('channel', 'group', or None for both)

        Returns:
            List of dicts with username and entity_type
        """
        result = []

        async with async_session_maker() as session:
            # Get already analyzed usernames
            analyzed_query = select(LLMAnalysisDB.username)
            analyzed_result = await session.execute(analyzed_query)
            analyzed_usernames = {row[0] for row in analyzed_result.fetchall()}

            # Get channels
            if entity_type is None or entity_type == "channel":
                channels_query = (
                    select(PreliminaryScoreDB.username)
                    .where(
                        and_(
                            PreliminaryScoreDB.status == "analyzed",
                            PreliminaryScoreDB.preliminary_score >= min_score,
                            PreliminaryScoreDB.username.notin_(analyzed_usernames),
                        )
                    )
                    .order_by(PreliminaryScoreDB.preliminary_score.desc())
                    .limit(limit)
                )
                channels_result = await session.execute(channels_query)
                for row in channels_result.fetchall():
                    result.append({"username": row[0], "entity_type": "channel"})

            # Get groups
            if entity_type is None or entity_type == "group":
                remaining = limit - len(result)
                if remaining > 0:
                    groups_query = (
                        select(PreliminaryGroupScoreDB.username)
                        .where(
                            and_(
                                PreliminaryGroupScoreDB.status == "analyzed",
                                PreliminaryGroupScoreDB.preliminary_score >= min_score,
                                PreliminaryGroupScoreDB.username.notin_(analyzed_usernames),
                            )
                        )
                        .order_by(PreliminaryGroupScoreDB.preliminary_score.desc())
                        .limit(remaining)
                    )
                    groups_result = await session.execute(groups_query)
                    for row in groups_result.fetchall():
                        result.append({"username": row[0], "entity_type": "group"})

        return result

    def get_stats(self) -> dict:
        """Get analysis statistics."""
        llm_stats = self.llm_client.get_stats()
        return {
            "channels_analyzed": self.channels_analyzed,
            "flood_wait_hit": self.flood_wait_hit,
            **llm_stats,
        }

    def print_stats(self):
        """Print formatted statistics."""
        self.llm_client.print_stats()
        print(f"Channels analyzed: {self.channels_analyzed}")
        if self.flood_wait_hit:
            print("WARNING: FloodWait was hit during analysis")
