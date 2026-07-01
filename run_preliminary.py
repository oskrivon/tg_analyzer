#!/usr/bin/env python3
"""
Run Preliminary Scorer - Phase 1 analysis.

Usage:
    python run_preliminary.py --session sessions/account1.session --proxy "host:port:user:pass"

Options:
    --session       Path to .session file (required)
    --proxy         Proxy in format host:port:user:pass (optional)
    --limit         Number of channels to analyze (default: 100)
    --min-subs      Minimum subscribers filter (optional)
    --max-requests  Stop after N requests (default: 200, for flood limit safety)
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import API_ID, API_HASH, validate_config
from database.connection import init_db
from services.preliminary_scorer import PreliminaryScorer

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"logs/preliminary_{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}.log"),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Run Preliminary Scorer (Phase 1)")
    parser.add_argument(
        "--session", "-s",
        required=True,
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
        help="Number of channels to fetch from API (default: 100)",
    )
    parser.add_argument(
        "--min-subs",
        type=int,
        help="Minimum subscribers filter",
    )
    parser.add_argument(
        "--max-subs",
        type=int,
        help="Maximum subscribers filter",
    )
    parser.add_argument(
        "--max-requests", "-m",
        type=int,
        default=200,
        help="Stop after N requests (default: 200)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between requests in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--posts",
        type=int,
        default=50,
        help="Number of posts to analyze per channel (default: 50)",
    )

    args = parser.parse_args()

    # Validate config
    try:
        validate_config()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Check session file
    session_path = Path(args.session)
    if not session_path.exists() and not Path(str(session_path) + ".session").exists():
        logger.error(f"Session file not found: {args.session}")
        sys.exit(1)

    # Create logs directory
    Path("logs").mkdir(exist_ok=True)

    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Run scorer
    logger.info("=" * 60)
    logger.info("PRELIMINARY SCORER - Phase 1")
    logger.info("=" * 60)
    logger.info(f"Session: {args.session}")
    logger.info(f"Proxy: {args.proxy or 'None'}")
    logger.info(f"Limit: {args.limit} channels")
    logger.info(f"Max requests: {args.max_requests}")
    logger.info(f"Min subs: {args.min_subs or 'Any'}")
    logger.info("=" * 60)

    async with PreliminaryScorer(
        api_id=API_ID,
        api_hash=API_HASH,
        session_path=str(session_path),
        proxy=args.proxy,
        posts_count=args.posts,
        request_delay=args.delay,
    ) as scorer:
        await scorer.run(
            limit=args.limit,
            min_subs=args.min_subs,
            max_subs=args.max_subs,
            max_requests=args.max_requests,
        )

    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
