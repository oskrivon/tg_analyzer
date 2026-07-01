#!/usr/bin/env python3
"""
Run LLM Content Analyzer - Claude API analysis of Telegram channels/groups.

Usage:
    # Analyze unanalyzed channels with min score 50
    python run_llm_analysis.py --session sessions/account1.session --limit 100 --min-score 50

    # With specific model
    python run_llm_analysis.py --session sessions/account1.session --model claude-3-5-sonnet-20241022

    # Analyze single channel
    python run_llm_analysis.py --session sessions/account1.session --username durov

    # Show cost statistics
    python run_llm_analysis.py stats

    # Dry run - estimate cost without actual API calls
    python run_llm_analysis.py --session sessions/account1.session --dry-run --limit 10
"""

import asyncio
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from telethon import TelegramClient
from sqlalchemy import select, func

import config
from config import API_ID, API_HASH, validate_config
from database.connection import init_db, async_session_maker
from database.models import LLMAnalysisDB
from services.llm_client import LLMClient
from services.llm_analyzer import LLMAnalyzer
from utils.proxy import parse_proxy

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/llm_analysis_{datetime.now().strftime('%Y-%m-%d')}.log"),
    ],
)
logger = logging.getLogger(__name__)


async def show_stats():
    """Show LLM analysis statistics from database."""
    await init_db()

    async with async_session_maker() as session:
        # Total analyzed
        total = await session.execute(
            select(func.count(LLMAnalysisDB.id)).where(LLMAnalysisDB.status == "completed")
        )
        total_count = total.scalar() or 0

        # Total cost
        cost = await session.execute(
            select(func.sum(LLMAnalysisDB.cost_usd)).where(LLMAnalysisDB.status == "completed")
        )
        total_cost = cost.scalar() or 0

        # Total tokens
        tokens = await session.execute(
            select(func.sum(LLMAnalysisDB.tokens_used)).where(LLMAnalysisDB.status == "completed")
        )
        total_tokens = tokens.scalar() or 0

        # By category
        categories = await session.execute(
            select(
                LLMAnalysisDB.primary_category,
                func.count(LLMAnalysisDB.id)
            )
            .where(LLMAnalysisDB.status == "completed")
            .group_by(LLMAnalysisDB.primary_category)
            .order_by(func.count(LLMAnalysisDB.id).desc())
        )

        # Errors
        errors = await session.execute(
            select(func.count(LLMAnalysisDB.id)).where(LLMAnalysisDB.status == "error")
        )
        error_count = errors.scalar() or 0

        # Models used
        models = await session.execute(
            select(
                LLMAnalysisDB.model_used,
                func.count(LLMAnalysisDB.id),
                func.sum(LLMAnalysisDB.cost_usd)
            )
            .where(LLMAnalysisDB.status == "completed")
            .group_by(LLMAnalysisDB.model_used)
        )

    print("\n" + "=" * 60)
    print("LLM Analysis Statistics")
    print("=" * 60)
    print(f"\nTotal analyzed: {total_count}")
    print(f"Total errors: {error_count}")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total cost: ${total_cost:.4f}")
    if total_count > 0:
        print(f"Average cost per channel: ${total_cost / total_count:.4f}")

    print("\n--- By Model ---")
    for row in models.fetchall():
        model, count, model_cost = row
        print(f"  {model or 'unknown'}: {count} channels, ${model_cost or 0:.4f}")

    print("\n--- By Category ---")
    for row in categories.fetchall():
        category, count = row
        print(f"  {category or 'unknown'}: {count}")

    print("=" * 60)


async def run_analysis(
    session_path: str,
    proxy: str = None,
    limit: int = 100,
    min_score: float = 50.0,
    username: str = None,
    model: str = None,
    posts_count: int = 20,
    delay: float = 0.5,
    dry_run: bool = False,
):
    """Run LLM analysis on channels/groups."""
    # Validate config
    try:
        validate_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set. Add it to .env file.")
        sys.exit(1)

    # Check session file
    session_path_obj = Path(session_path)
    if not session_path_obj.exists() and not Path(str(session_path_obj) + ".session").exists():
        logger.error(f"Session file not found: {session_path}")
        sys.exit(1)

    # Create logs directory
    Path("logs").mkdir(exist_ok=True)

    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Create LLM client
    llm_client = LLMClient(
        api_key=config.ANTHROPIC_API_KEY,
        model=model or config.LLM_MODEL,
    )

    # Connect to Telegram
    proxy_config = parse_proxy(proxy) if proxy else None
    telegram_client = TelegramClient(
        session_path,
        API_ID,
        API_HASH,
        proxy=proxy_config,
    )

    await telegram_client.connect()
    if not await telegram_client.is_user_authorized():
        logger.error(f"Session {session_path} is not authorized")
        await telegram_client.disconnect()
        sys.exit(1)

    me = await telegram_client.get_me()
    logger.info(f"Connected as {me.first_name} (@{me.username or me.id})")

    # Create analyzer
    analyzer = LLMAnalyzer(
        telegram_client=telegram_client,
        llm_client=llm_client,
        request_delay=delay,
        max_posts=posts_count,
    )

    # Log settings
    logger.info("=" * 60)
    logger.info("LLM CONTENT ANALYZER")
    logger.info("=" * 60)
    logger.info(f"Session: {session_path}")
    logger.info(f"Proxy: {proxy or 'None'}")
    logger.info(f"Model: {model or config.LLM_MODEL}")
    logger.info(f"Posts per channel: {posts_count}")
    logger.info(f"Min score: {min_score}")
    logger.info(f"Dry run: {dry_run}")
    logger.info("=" * 60)

    try:
        if username:
            # Analyze single channel
            channels_to_analyze = [{"username": username, "entity_type": "unknown"}]
        else:
            # Get channels needing analysis
            channels_to_analyze = await analyzer.get_channels_for_analysis(
                limit=limit,
                min_score=min_score,
            )

        if not channels_to_analyze:
            logger.info("No channels found for analysis")
            return

        logger.info(f"Found {len(channels_to_analyze)} channels to analyze")

        if dry_run:
            # Estimate cost without actual analysis
            estimated_tokens_per_channel = 4500  # ~4500 tokens per channel
            estimated_cost_per_channel = 0.002  # ~$0.002 for Haiku
            if "sonnet" in (model or config.LLM_MODEL).lower():
                estimated_cost_per_channel = 0.02
            elif "opus" in (model or config.LLM_MODEL).lower():
                estimated_cost_per_channel = 0.10

            total_estimated = len(channels_to_analyze) * estimated_cost_per_channel
            logger.info(f"\n--- DRY RUN ESTIMATE ---")
            logger.info(f"Channels: {len(channels_to_analyze)}")
            logger.info(f"Estimated tokens per channel: ~{estimated_tokens_per_channel}")
            logger.info(f"Estimated cost per channel: ~${estimated_cost_per_channel:.4f}")
            logger.info(f"Total estimated cost: ~${total_estimated:.2f}")
            logger.info(f"------------------------\n")
            return

        # Analyze channels
        for i, channel_info in enumerate(channels_to_analyze, 1):
            channel_username = channel_info["username"]

            if analyzer.flood_wait_hit:
                logger.error("FloodWait hit, stopping")
                break

            logger.info(f"\n[{i}/{len(channels_to_analyze)}] Analyzing @{channel_username}...")

            try:
                result = await analyzer.analyze_channel(
                    username=channel_username,
                    posts_count=posts_count,
                )

                # Save to database
                await analyzer.save_result(result)

                if result.status == "completed":
                    logger.info(
                        f"  Category: {result.primary_category}, "
                        f"Quality: {result.quality_score:.0f}, "
                        f"Toxicity: {result.toxicity_score:.0f}, "
                        f"Cost: ${result.cost_usd:.4f}"
                    )
                else:
                    logger.warning(f"  Status: {result.status}, Error: {result.error_message}")

            except Exception as e:
                logger.exception(f"Error analyzing @{channel_username}: {e}")

            # Rate limit between channels
            await asyncio.sleep(delay)

    finally:
        await telegram_client.disconnect()
        analyzer.print_stats()


async def main():
    parser = argparse.ArgumentParser(
        description="Run LLM Content Analyzer on Telegram channels/groups",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Analyze 100 channels with min score 50
    python run_llm_analysis.py -s sessions/acc1.session -l 100 --min-score 50

    # Use Sonnet model
    python run_llm_analysis.py -s sessions/acc1.session --model claude-3-5-sonnet-20241022

    # Single channel
    python run_llm_analysis.py -s sessions/acc1.session --username durov

    # Show statistics
    python run_llm_analysis.py stats
        """,
    )

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("stats", help="Show analysis statistics")

    parser.add_argument(
        "--session", "-s",
        help="Path to .session file",
    )
    parser.add_argument(
        "--proxy", "-p",
        help="Proxy in format host:port:user:pass",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=100,
        help="Number of channels to analyze (default: 100)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=50.0,
        help="Minimum preliminary score threshold (default: 50)",
    )
    parser.add_argument(
        "--username", "-u",
        help="Analyze specific channel/group by username",
    )
    parser.add_argument(
        "--model", "-m",
        help="Claude model to use (default: claude-3-haiku-20240307)",
    )
    parser.add_argument(
        "--posts",
        type=int,
        default=20,
        help="Number of posts to analyze per channel (default: 20)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between Telegram requests (default: 0.5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate cost without making API calls",
    )

    args = parser.parse_args()

    if args.command == "stats":
        await show_stats()
        return

    if not args.session:
        parser.error("--session is required")

    await run_analysis(
        session_path=args.session,
        proxy=args.proxy,
        limit=args.limit,
        min_score=args.min_score,
        username=args.username,
        model=args.model,
        posts_count=args.posts,
        delay=args.delay,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    asyncio.run(main())
