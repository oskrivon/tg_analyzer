"""SQLAlchemy ORM models for Telegram Analyzer."""

from datetime import datetime, date
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class ChannelDB(Base):
    """Channel information table."""
    __tablename__ = "channels"

    # Primary key - Telegram channel ID
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Basic info
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Type flags
    is_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    is_megagroup: Mapped[bool] = mapped_column(Boolean, default=False)
    is_gigagroup: Mapped[bool] = mapped_column(Boolean, default=False)

    # Statistics
    participants_count: Mapped[int] = mapped_column(Integer, default=0)
    online_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    admins_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    banned_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kicked_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Settings
    slowmode_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    linked_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    auto_delete_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Restrictions
    has_protected_content: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_participants: Mapped[bool] = mapped_column(Boolean, default=True)
    can_set_username: Mapped[bool] = mapped_column(Boolean, default=False)
    can_set_stickers: Mapped[bool] = mapped_column(Boolean, default=False)
    can_set_location: Mapped[bool] = mapped_column(Boolean, default=False)
    can_view_stats: Mapped[bool] = mapped_column(Boolean, default=False)

    # Media
    has_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stickerset_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    theme_emoticon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Links
    invite_link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Meta
    telegram_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    migrated_from_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Database timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    analytics: Mapped[list["ChannelAnalyticsDB"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    engagement_stats: Mapped[list["EngagementStatsDB"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    posting_frequencies: Mapped[list["PostingFrequencyDB"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )
    bots: Mapped[list["ChannelBotDB"]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class ChannelAnalyticsDB(Base):
    """Channel analytics table."""
    __tablename__ = "channel_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    # Channel type
    channel_type: Mapped[str] = mapped_column(String(50), default="unknown")

    # Participant counts
    total_participants: Mapped[int] = mapped_column(Integer, default=0)
    participants_fetched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bot_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bot_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    admin_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    admin_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    premium_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    premium_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    online_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    online_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Data collection metadata
    participants_method: Mapped[str] = mapped_column(String(50), default="unknown")
    data_confidence: Mapped[str] = mapped_column(String(50), default="unknown")
    data_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Health score
    health_score: Mapped[float] = mapped_column(Float, default=0.0)
    health_factors: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Flags
    has_slowmode: Mapped[bool] = mapped_column(Boolean, default=False)
    has_linked_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    has_protected_content: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship
    channel: Mapped["ChannelDB"] = relationship(back_populates="analytics")


class EngagementStatsDB(Base):
    """Engagement statistics table."""
    __tablename__ = "engagement_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    # Post statistics
    posts_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    total_views: Mapped[int] = mapped_column(Integer, default=0)
    total_reactions: Mapped[int] = mapped_column(Integer, default=0)
    total_comments: Mapped[int] = mapped_column(Integer, default=0)
    total_forwards: Mapped[int] = mapped_column(Integer, default=0)
    avg_views: Mapped[int] = mapped_column(Integer, default=0)
    avg_reactions: Mapped[int] = mapped_column(Integer, default=0)
    avg_comments: Mapped[int] = mapped_column(Integer, default=0)
    avg_forwards: Mapped[int] = mapped_column(Integer, default=0)

    # Reactions breakdown (emoji -> count)
    reactions_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Commenters
    unique_commenters_count: Mapped[int] = mapped_column(Integer, default=0)
    bot_commenters_count: Mapped[int] = mapped_column(Integer, default=0)
    commenters_bot_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship
    channel: Mapped["ChannelDB"] = relationship(back_populates="engagement_stats")


class PostingFrequencyDB(Base):
    """Posting frequency table."""
    __tablename__ = "posting_frequency"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    posts_total: Mapped[int] = mapped_column(Integer, default=0)
    days_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    posts_per_day: Mapped[float] = mapped_column(Float, default=0.0)
    frequency_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationship
    channel: Mapped["ChannelDB"] = relationship(back_populates="posting_frequencies")


class ChannelBotDB(Base):
    """Channel bots table."""
    __tablename__ = "channel_bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commands: Mapped[list] = mapped_column(JSONB, default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    channel: Mapped["ChannelDB"] = relationship(back_populates="bots")


class GroupAnalyticsDB(Base):
    """Group analytics table (separate from channel analytics)."""
    __tablename__ = "group_analytics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    # Group type
    group_type: Mapped[str] = mapped_column(String(50), default="group")

    # Participant counts
    total_participants: Mapped[int] = mapped_column(Integer, default=0)
    participants_fetched: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Audience quality
    bot_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bot_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    admin_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    admin_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    premium_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    premium_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verified_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    verified_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Online activity
    online_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    online_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Data collection metadata
    participants_method: Mapped[str] = mapped_column(String(50), default="unknown")
    data_confidence: Mapped[str] = mapped_column(String(50), default="unknown")
    data_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Health score
    health_score: Mapped[float] = mapped_column(Float, default=0.0)
    health_factors: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Settings
    has_slowmode: Mapped[bool] = mapped_column(Boolean, default=False)
    slowmode_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    has_linked_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    has_protected_content: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupActivityStatsDB(Base):
    """Group activity statistics table."""
    __tablename__ = "group_activity_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    # Period
    period_days: Mapped[int] = mapped_column(Integer, default=7)

    # Messages
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    messages_per_day: Mapped[float] = mapped_column(Float, default=0.0)

    # Active users
    active_users_count: Mapped[int] = mapped_column(Integer, default=0)
    active_users_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    messages_per_active_user: Mapped[float] = mapped_column(Float, default=0.0)

    # Top users (JSON: {user_id: message_count})
    top_users_messages: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Spam metrics
    spam_messages_count: Mapped[int] = mapped_column(Integer, default=0)
    spam_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    deleted_messages_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GroupScoreDB(Base):
    """Group scoring results table."""
    __tablename__ = "group_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )

    # Score results
    total_score: Mapped[float] = mapped_column(Float, default=0.0)
    grade: Mapped[str] = mapped_column(String(50), default="unknown")
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Score breakdown
    activity_score: Mapped[float] = mapped_column(Float, default=0.0)
    audience_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    growth_score: Mapped[float] = mapped_column(Float, default=0.0)
    health_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Full breakdown as JSON
    breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Timestamps
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PreliminaryScoreDB(Base):
    """Preliminary scoring results (Phase 1 - light analysis)."""
    __tablename__ = "preliminary_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Channel identification (from crawler API)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Basic info from Telegram API
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subscribers_api: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # from Telegram API
    subscribers_crawler: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # from crawler API

    # Comments availability
    has_linked_chat: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Engagement metrics (from posts)
    posts_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    avg_views: Mapped[int] = mapped_column(Integer, default=0)
    avg_reactions: Mapped[int] = mapped_column(Integer, default=0)
    avg_comments: Mapped[int] = mapped_column(Integer, default=0)
    avg_forwards: Mapped[int] = mapped_column(Integer, default=0)

    # Calculated metrics
    err: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # engagement rate
    reach: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # views/subscribers
    posts_per_day: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Preliminary score (0-100)
    preliminary_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Description (from GetFullChannel)
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Keyword-based category detection (free, no LLM)
    detected_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, analyzed, error, flood_wait
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Analysis metadata
    account_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    requests_spent: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AnalysisSessionDB(Base):
    """Tracks analysis sessions for request counting and flood limit monitoring."""
    __tablename__ = "analysis_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Session identification
    session_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Request tracking
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    successful_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)
    channels_analyzed: Mapped[int] = mapped_column(Integer, default=0)

    # Flood wait tracking
    flood_wait_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    flood_wait_at_request: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    flood_wait_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timing
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="running")  # running, completed, flood_wait, error


class PreliminaryGroupScoreDB(Base):
    """Preliminary scoring results for groups (Phase 1 - light analysis)."""
    __tablename__ = "preliminary_group_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Group identification (from crawler API)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Basic info from Telegram API
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    participants_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # from Telegram API
    participants_crawler: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # from crawler API

    # Group type
    is_megagroup: Mapped[bool] = mapped_column(Boolean, default=True)
    is_gigagroup: Mapped[bool] = mapped_column(Boolean, default=False)

    # Settings
    has_linked_channel: Mapped[bool] = mapped_column(Boolean, default=False)
    linked_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    slowmode_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Activity metrics (from recent messages sample)
    messages_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    unique_senders: Mapped[int] = mapped_column(Integer, default=0)
    messages_per_day: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    active_users_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # unique_senders / participants
    top_sender_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # share of msgs from most active sender (0-1), detects announcement-style groups

    # Online activity (if available)
    online_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    online_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Description (from GetFullChannel)
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Keyword-based category detection (free, no LLM)
    detected_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1

    # Preliminary score (0-100)
    preliminary_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, analyzed, error, flood_wait
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Analysis metadata
    account_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    requests_spent: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CrawlPositionDB(Base):
    """Tracks crawling position for incremental fetching from crawler API."""
    __tablename__ = "crawl_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Position identifier (e.g., "default", "channels", "groups")
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)

    # Last processed ID from crawler API
    last_id: Mapped[int] = mapped_column(Integer, default=0)

    # Statistics
    total_fetched: Mapped[int] = mapped_column(Integer, default=0)
    total_analyzed: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LLMAnalysisDB(Base):
    """LLM-based content analysis results for channels/groups."""
    __tablename__ = "llm_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Entity identification
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), default="channel")  # channel/group

    # === Thematic Classification ===
    primary_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # e.g., tech, news, crypto, politics, entertainment, education, business, lifestyle
    secondary_categories: Mapped[list] = mapped_column(JSONB, default=list)
    topics: Mapped[list] = mapped_column(JSONB, default=list)  # Specific topics within category
    category_scores: Mapped[dict] = mapped_column(JSONB, default=dict)  # {category: confidence}

    # === Sentiment/Tonality ===
    overall_sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # -1.0 to 1.0
    sentiment_label: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # positive/negative/neutral/mixed
    emotional_tone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # formal/casual/aggressive/friendly/neutral
    propaganda_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-1

    # === Quality Scores (0-100) ===
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    originality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    informativeness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    professionalism_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engagement_authenticity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100

    # === Toxicity Scores (0-100) ===
    toxicity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    hate_speech_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    harassment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    misinformation_risk: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    adult_content_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    violence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    toxicity_flags: Mapped[list] = mapped_column(JSONB, default=list)  # List of detected issues

    # === Analysis Metadata ===
    full_analysis: Mapped[dict] = mapped_column(JSONB, default=dict)  # Full LLM response
    posts_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending/completed/error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DiscoveredLinkDB(Base):
    """Discovered Telegram channel/chat links during analysis."""
    __tablename__ = "discovered_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    discovered_from: Mapped[str] = mapped_column(String(255), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Source and status tracking
    source_type: Mapped[str] = mapped_column(String(20), default="analyzer")  # analyzer, manual, etc.
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending, exported, consumed

    # Export tracking
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    export_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Priority for crawler
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)  # 1=high, 0=normal, -1=low


class DiscoveredEntityDB(Base):
    """Non-channel entities (bots, users) discovered during analysis.

    Used for:
    1. Deduplication - skip already-resolved usernames
    2. Future use - catalog of bots/users for analysis
    3. Accurate flood limit tracking - these count towards TG limit!
    """
    __tablename__ = "discovered_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)

    # Entity type: 'user', 'bot'
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Basic info
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Display name
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Flags
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)

    # Discovery tracking
    discovered_from: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
