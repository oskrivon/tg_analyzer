"""
Prompt templates for LLM content analysis.

Contains system and user prompts for:
- Thematic classification
- Sentiment analysis
- Quality scoring
- Toxicity detection
"""

from dataclasses import dataclass
from typing import Optional


SYSTEM_PROMPT = """You are an expert content analyst specializing in Telegram channels and groups. Your task is to analyze the provided content and return a structured JSON analysis.

IMPORTANT RULES:
1. Return ONLY valid JSON - no explanations, no markdown formatting
2. All scores are 0-100 unless otherwise specified
3. Be objective and precise in your assessments
4. If content is in a non-English language, analyze it in that language
5. Consider the channel's purpose when judging quality

OUTPUT FORMAT:
Return a single JSON object with these exact fields:
{
    "thematic": {
        "primary_category": "<one of: tech, news, crypto, politics, entertainment, education, business, lifestyle, gaming, sports, health, science, travel, food, art, music, relocation, expat_community, foreign_banking, other>",
        "secondary_categories": ["<category>", ...],
        "topics": ["<specific topic>", ...],
        "category_scores": {"<category>": <confidence 0-100>, ...}
    },
    "sentiment": {
        "overall_sentiment": <float -1.0 to 1.0>,
        "sentiment_label": "<positive|negative|neutral|mixed>",
        "emotional_tone": "<formal|casual|aggressive|friendly|neutral|satirical|sensational>",
        "propaganda_score": <float 0-1>
    },
    "quality": {
        "quality_score": <0-100>,
        "originality_score": <0-100>,
        "informativeness_score": <0-100>,
        "professionalism_score": <0-100>,
        "engagement_authenticity": <0-100>
    },
    "toxicity": {
        "toxicity_score": <0-100>,
        "hate_speech_score": <0-100>,
        "harassment_score": <0-100>,
        "misinformation_risk": <0-100>,
        "adult_content_score": <0-100>,
        "violence_score": <0-100>,
        "toxicity_flags": ["<flag>", ...]
    },
    "summary": {
        "description": "<2-3 sentence description of channel content>",
        "target_audience": "<who this content is for>",
        "content_style": "<brief description of content style>"
    }
}

SCORING GUIDELINES:

Thematic Categories:
- tech: Technology, programming, AI, gadgets, software
- news: Current events, journalism, breaking news
- crypto: Cryptocurrency, blockchain, DeFi, NFTs
- politics: Political content, government, policy
- entertainment: Movies, TV, celebrities, memes, humor
- education: Learning, tutorials, courses, academic
- business: Finance, investing, entrepreneurship, marketing
- lifestyle: Fashion, beauty, home, relationships
- gaming: Video games, esports, game reviews
- sports: Sports news, teams, athletes
- health: Medical, fitness, nutrition, mental health
- science: Scientific research, discoveries, nature
- travel: Travel guides, destinations, tourism
- food: Recipes, restaurants, culinary content
- art: Visual arts, design, creative works
- music: Music, artists, albums, concerts
- relocation: Emigration, relocation abroad, moving to another country, visa/immigration info
- expat_community: Russian-speaking communities abroad (UAE, Georgia, Cyprus, Thailand, Turkey, Serbia, Montenegro, Bali, etc.). Local expat chats, community groups
- foreign_banking: Foreign bank accounts, cards abroad, payment systems for expats, crypto for expats, international transfers
- other: Content that doesn't fit other categories

GEOGRAPHIC TAGS (add to topics if relevant):
When content relates to specific countries/cities popular among Russian expats, include them in topics:
- UAE/Dubai/Abu Dhabi, Georgia/Tbilisi/Batumi, Cyprus/Limassol, Thailand/Bangkok/Phuket
- Turkey/Istanbul/Antalya, Serbia/Belgrade, Montenegro, Indonesia/Bali
- Armenia/Yerevan, Kazakhstan/Almaty, Uzbekistan/Tashkent
- Portugal, Spain, Germany, UK, USA, Canada, Israel

Quality Scoring:
- originality_score: How much original content vs reposts/aggregation
- informativeness_score: Educational value, depth of information
- professionalism_score: Writing quality, presentation, consistency
- engagement_authenticity: Does engagement seem genuine? (low = likely bots/fake)
- quality_score: Overall quality composite

Toxicity Scoring:
- hate_speech_score: Discrimination, slurs, targeted hate
- harassment_score: Personal attacks, bullying, threats
- misinformation_risk: Likelihood of spreading false information
- adult_content_score: Sexual/NSFW content
- violence_score: Violent imagery or incitement
- toxicity_flags: List specific issues found (e.g., "xenophobia", "conspiracy theories", "clickbait")

Sentiment:
- overall_sentiment: -1.0 (very negative) to 1.0 (very positive)
- propaganda_score: 0 (balanced) to 1 (heavy propaganda/manipulation)"""


USER_PROMPT_TEMPLATE = """Analyze this Telegram {entity_type}:

=== CHANNEL INFO ===
Title: {title}
Username: @{username}
Subscribers: {subscribers:,}
Description: {description}

=== ENGAGEMENT CONTEXT ===
Average views per post: {avg_views:,}
Average reactions per post: {avg_reactions}
Average comments per post: {avg_comments}

=== RECENT POSTS ({posts_count} posts) ===
{posts_text}

Analyze this content and return the JSON analysis."""


@dataclass
class PostContent:
    """Content from a single post for analysis."""
    text: str
    views: int = 0
    reactions: int = 0
    comments: int = 0


@dataclass
class LLMAnalysisInput:
    """Input data for LLM analysis."""
    username: str
    entity_type: str  # channel/group
    title: str
    description: Optional[str]
    subscribers: int
    posts: list[PostContent]
    avg_views: int = 0
    avg_reactions: int = 0
    avg_comments: int = 0


def format_posts_for_prompt(posts: list[PostContent], max_chars_per_post: int = 500) -> str:
    """Format posts list for the prompt."""
    if not posts:
        return "No posts available."

    formatted = []
    for i, post in enumerate(posts, 1):
        text = post.text[:max_chars_per_post]
        if len(post.text) > max_chars_per_post:
            text += "..."

        formatted.append(
            f"[Post {i}] (views: {post.views}, reactions: {post.reactions}, comments: {post.comments})\n{text}"
        )

    return "\n\n".join(formatted)


def build_analysis_prompt(input_data: LLMAnalysisInput) -> tuple[str, str]:
    """
    Build system and user prompts for analysis.

    Args:
        input_data: LLMAnalysisInput with channel/group data

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    posts_text = format_posts_for_prompt(input_data.posts)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        entity_type=input_data.entity_type,
        title=input_data.title or "Unknown",
        username=input_data.username,
        subscribers=input_data.subscribers,
        description=input_data.description or "No description",
        avg_views=input_data.avg_views,
        avg_reactions=input_data.avg_reactions,
        avg_comments=input_data.avg_comments,
        posts_count=len(input_data.posts),
        posts_text=posts_text,
    )

    return SYSTEM_PROMPT, user_prompt


def estimate_tokens(input_data: LLMAnalysisInput) -> int:
    """
    Estimate token count for an analysis request.

    Rough estimation: ~4 chars per token for English,
    ~2-3 chars per token for other languages (Cyrillic, etc.)
    """
    system_len = len(SYSTEM_PROMPT)
    posts_text = format_posts_for_prompt(input_data.posts)
    user_len = len(USER_PROMPT_TEMPLATE) + len(posts_text) + 500  # metadata overhead

    total_chars = system_len + user_len

    # Conservative estimate (assume mixed content)
    return int(total_chars / 3)


# =============================================================================
# Batch Analysis Prompts
# =============================================================================

BATCH_SYSTEM_PROMPT = """You are an expert content analyst specializing in Telegram channels. Analyze multiple channels in a single request.

RULES:
1. Return ONLY valid JSON array - no explanations
2. All scores are 0-100 unless specified
3. Be objective and precise
4. Analyze each channel independently

OUTPUT FORMAT - return a JSON array:
[
  {
    "username": "@channel_name",
    "thematic": {
      "primary_category": "<tech|news|crypto|politics|entertainment|education|business|lifestyle|gaming|sports|health|science|travel|food|art|music|relocation|expat_community|foreign_banking|other>",
      "secondary_categories": ["<category>", ...],
      "topics": ["<topic>", ...]
    },
    "sentiment": {
      "overall_sentiment": <-1.0 to 1.0>,
      "sentiment_label": "<positive|negative|neutral|mixed>",
      "emotional_tone": "<formal|casual|aggressive|friendly|neutral|satirical|sensational>",
      "propaganda_score": <0-1>
    },
    "quality": {
      "quality_score": <0-100>,
      "originality_score": <0-100>,
      "informativeness_score": <0-100>,
      "professionalism_score": <0-100>,
      "engagement_authenticity": <0-100>
    },
    "toxicity": {
      "toxicity_score": <0-100>,
      "hate_speech_score": <0-100>,
      "harassment_score": <0-100>,
      "misinformation_risk": <0-100>,
      "adult_content_score": <0-100>,
      "violence_score": <0-100>,
      "toxicity_flags": []
    }
  },
  ...
]"""


BATCH_CHANNEL_TEMPLATE = """--- CHANNEL {index}: @{username} ---
Title: {title}
Subscribers: {subscribers:,}
Engagement: views={avg_views}, reactions={avg_reactions}, comments={avg_comments}
{unique_commenters_info}
Posts:
{posts_text}
"""


def format_posts_compact(posts: list[PostContent], max_posts: int = 5, max_chars: int = 300) -> str:
    """Format posts compactly for batch analysis."""
    if not posts:
        return "(no posts)"

    formatted = []
    for i, post in enumerate(posts[:max_posts], 1):
        text = post.text[:max_chars].replace('\n', ' ').strip()
        if len(post.text) > max_chars:
            text += "..."
        formatted.append(f"[{i}] {text}")

    return "\n".join(formatted)


def build_batch_prompt(
    channels: list[LLMAnalysisInput],
    max_posts_per_channel: int = 5,
    max_chars_per_post: int = 300,
) -> tuple[str, str]:
    """
    Build batch analysis prompt for multiple channels.

    Args:
        channels: List of LLMAnalysisInput objects
        max_posts_per_channel: Limit posts per channel
        max_chars_per_post: Limit chars per post

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    channel_blocks = []

    for i, channel in enumerate(channels, 1):
        posts_text = format_posts_compact(
            channel.posts,
            max_posts=max_posts_per_channel,
            max_chars=max_chars_per_post,
        )

        # Add unique commenters info if available
        unique_commenters_info = ""
        if hasattr(channel, '_unique_commenters') and channel._unique_commenters:
            unique_commenters_info = f"Unique commenters: {channel._unique_commenters}"
            if hasattr(channel, '_commenters_ratio') and channel._commenters_ratio:
                unique_commenters_info += f" (ratio: {channel._commenters_ratio:.1f})"

        block = BATCH_CHANNEL_TEMPLATE.format(
            index=i,
            username=channel.username,
            title=channel.title or "Unknown",
            subscribers=channel.subscribers,
            avg_views=channel.avg_views,
            avg_reactions=channel.avg_reactions,
            avg_comments=channel.avg_comments,
            unique_commenters_info=unique_commenters_info,
            posts_text=posts_text,
        )
        channel_blocks.append(block)

    user_prompt = f"Analyze these {len(channels)} Telegram channels:\n\n" + "\n".join(channel_blocks)
    user_prompt += "\n\nReturn JSON array with analysis for each channel in order."

    return BATCH_SYSTEM_PROMPT, user_prompt


def estimate_batch_tokens(channels: list[LLMAnalysisInput]) -> int:
    """Estimate tokens for batch request."""
    system_len = len(BATCH_SYSTEM_PROMPT)

    user_len = 100  # base overhead
    for channel in channels:
        posts_text = format_posts_compact(channel.posts)
        user_len += len(BATCH_CHANNEL_TEMPLATE) + len(posts_text) + 200

    total_chars = system_len + user_len
    return int(total_chars / 3)  # Conservative for Cyrillic
