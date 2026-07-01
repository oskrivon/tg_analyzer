"""Engagement metrics calculations."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EngagementMetrics:
    """Calculated engagement metrics for a channel."""
    posts_analyzed: int = 0
    avg_views: int = 0
    avg_reactions: int = 0
    avg_comments: int = 0
    avg_forwards: int = 0
    err: float = 0.0  # Engagement Rate: (reactions + comments + forwards) / views * 100
    reach: float = 0.0  # Reach: views / subscribers * 100
    posts_per_day: Optional[float] = None


def calculate_engagement_metrics(
    posts_stats: list[dict],
    subscribers: int = 0,
) -> EngagementMetrics:
    """
    Calculate engagement metrics from posts statistics.

    Args:
        posts_stats: List of dicts with keys: views, reactions, comments, forwards, date (optional)
        subscribers: Channel subscriber count for reach calculation

    Returns:
        EngagementMetrics dataclass with calculated values
    """
    if not posts_stats:
        return EngagementMetrics()

    n = len(posts_stats)

    total_views = sum(p.get("views", 0) for p in posts_stats)
    total_reactions = sum(p.get("reactions", 0) for p in posts_stats)
    total_comments = sum(p.get("comments", 0) for p in posts_stats)
    total_forwards = sum(p.get("forwards", 0) for p in posts_stats)

    avg_views = total_views // n
    avg_reactions = total_reactions // n
    avg_comments = total_comments // n
    avg_forwards = total_forwards // n

    # ERR = (reactions + comments + forwards) / views * 100
    total_engagement = avg_reactions + avg_comments + avg_forwards
    err = (total_engagement / max(avg_views, 1)) * 100

    # Reach = views / subscribers * 100
    subs = max(subscribers, 1)
    reach = (avg_views / subs) * 100

    # Posts per day (if dates available)
    posts_per_day = None
    dates = [p.get("date") for p in posts_stats if p.get("date")]
    if len(dates) >= 2:
        date_range_days = (max(dates) - min(dates)).days or 1
        posts_per_day = n / date_range_days

    return EngagementMetrics(
        posts_analyzed=n,
        avg_views=avg_views,
        avg_reactions=avg_reactions,
        avg_comments=avg_comments,
        avg_forwards=avg_forwards,
        err=round(err, 2),
        reach=round(reach, 2),
        posts_per_day=round(posts_per_day, 2) if posts_per_day else None,
    )


def extract_post_stats(message) -> Optional[dict]:
    """
    Extract statistics from a Telethon message object.

    Args:
        message: Telethon Message object

    Returns:
        dict with views, reactions, comments, forwards, date
        None if message is None
    """
    if message is None:
        return None

    reactions_count = 0
    if message.reactions and hasattr(message.reactions, "results"):
        for r in message.reactions.results:
            reactions_count += getattr(r, "count", 0)

    return {
        "views": message.views or 0,
        "reactions": reactions_count,
        "comments": message.replies.replies if message.replies else 0,
        "forwards": message.forwards or 0,
        "date": message.date,
    }
