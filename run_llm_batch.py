#!/usr/bin/env python3
"""
LLM Batch Analyzer with CSV export and prompt versioning.

Usage:
    # Run on top 10 channels by subscribers
    python run_llm_batch.py --session sessions/acc.session --top 10 --output results/

    # Use custom prompt
    python run_llm_batch.py --session sessions/acc.session --top 10 --prompt prompts/v2.txt

    # List available prompts
    python run_llm_batch.py prompts

    # Save current prompt as version
    python run_llm_batch.py save-prompt v1 "Initial prompt"
"""

import asyncio
import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from sqlalchemy import select, desc

import config
from config import API_ID, API_HASH
from database.connection import init_db, async_session_maker
from database.models import PreliminaryScoreDB, LLMAnalysisDB
from services.llm_client import LLMClient
from services.llm_analyzer import LLMAnalyzer
from utils.llm_prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from utils.proxy import parse_proxy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Directories
PROMPTS_DIR = Path("prompts")
RESULTS_DIR = Path("results")


def ensure_dirs():
    """Create necessary directories."""
    PROMPTS_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)


def save_prompt(name: str, description: str = ""):
    """Save current prompt as a version."""
    ensure_dirs()
    prompt_file = PROMPTS_DIR / f"{name}.txt"
    meta_file = PROMPTS_DIR / f"{name}.meta.json"

    # Save prompt
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write("=== SYSTEM PROMPT ===\n")
        f.write(SYSTEM_PROMPT)
        f.write("\n\n=== USER PROMPT TEMPLATE ===\n")
        f.write(USER_PROMPT_TEMPLATE)

    # Save metadata
    meta = {
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "system_prompt_len": len(SYSTEM_PROMPT),
        "user_template_len": len(USER_PROMPT_TEMPLATE),
    }
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"Saved prompt '{name}' to {prompt_file}")


def load_prompt(name: str) -> tuple[str, str]:
    """Load prompt version."""
    prompt_file = PROMPTS_DIR / f"{name}.txt"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt '{name}' not found at {prompt_file}")

    content = prompt_file.read_text(encoding="utf-8")
    parts = content.split("=== USER PROMPT TEMPLATE ===")

    system = parts[0].replace("=== SYSTEM PROMPT ===", "").strip()
    user = parts[1].strip() if len(parts) > 1 else USER_PROMPT_TEMPLATE

    return system, user


def list_prompts():
    """List available prompt versions."""
    ensure_dirs()
    prompts = list(PROMPTS_DIR.glob("*.meta.json"))

    if not prompts:
        print("No saved prompts. Use 'save-prompt' to create one.")
        return

    print("\nAvailable prompts:")
    print("-" * 60)
    for meta_file in sorted(prompts):
        meta = json.loads(meta_file.read_text())
        print(f"  {meta['name']}")
        print(f"    Description: {meta.get('description', 'N/A')}")
        print(f"    Created: {meta['created_at']}")
        print(f"    System prompt: {meta['system_prompt_len']} chars")
        print()


async def get_top_channels(limit: int = 10) -> list[dict]:
    """Get top channels by subscribers from preliminary_scores."""
    async with async_session_maker() as session:
        query = (
            select(
                PreliminaryScoreDB.username,
                PreliminaryScoreDB.title,
                PreliminaryScoreDB.subscribers_api,
                PreliminaryScoreDB.avg_views,
                PreliminaryScoreDB.avg_reactions,
                PreliminaryScoreDB.err,
                PreliminaryScoreDB.preliminary_score,
            )
            .where(PreliminaryScoreDB.status == "analyzed")
            .order_by(desc(PreliminaryScoreDB.subscribers_api))
            .limit(limit)
        )
        result = await session.execute(query)
        rows = result.fetchall()

        return [
            {
                "username": r[0],
                "title": r[1],
                "subscribers": r[2],
                "avg_views": r[3],
                "avg_reactions": r[4],
                "err": r[5],
                "preliminary_score": r[6],
            }
            for r in rows
        ]


def export_to_csv(results: list[dict], output_path: Path, prompt_name: str = "default"):
    """Export results to CSV."""
    if not results:
        print("No results to export")
        return

    # Add prompt info and costs
    fieldnames = [
        "username", "title", "subscribers",
        # Thematic
        "primary_category", "secondary_categories", "topics",
        # Sentiment
        "overall_sentiment", "sentiment_label", "emotional_tone", "propaganda_score",
        # Quality
        "quality_score", "originality_score", "informativeness_score", "professionalism_score",
        # Toxicity
        "toxicity_score", "hate_speech_score", "harassment_score", "misinformation_risk",
        "adult_content_score", "violence_score", "toxicity_flags",
        # Summary
        "description", "target_audience", "content_style",
        # Costs
        "tokens_used", "cost_usd", "telegram_requests",
        # Meta
        "prompt_version", "model_used", "status", "error",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            row = {
                "username": r.get("username"),
                "title": r.get("title"),
                "subscribers": r.get("subscribers"),
                "primary_category": r.get("primary_category"),
                "secondary_categories": json.dumps(r.get("secondary_categories", [])),
                "topics": json.dumps(r.get("topics", [])),
                "overall_sentiment": r.get("overall_sentiment"),
                "sentiment_label": r.get("sentiment_label"),
                "emotional_tone": r.get("emotional_tone"),
                "propaganda_score": r.get("propaganda_score"),
                "quality_score": r.get("quality_score"),
                "originality_score": r.get("originality_score"),
                "informativeness_score": r.get("informativeness_score"),
                "professionalism_score": r.get("professionalism_score"),
                "toxicity_score": r.get("toxicity_score"),
                "hate_speech_score": r.get("hate_speech_score"),
                "harassment_score": r.get("harassment_score"),
                "misinformation_risk": r.get("misinformation_risk"),
                "adult_content_score": r.get("adult_content_score"),
                "violence_score": r.get("violence_score"),
                "toxicity_flags": json.dumps(r.get("toxicity_flags", [])),
                "description": r.get("description"),
                "target_audience": r.get("target_audience"),
                "content_style": r.get("content_style"),
                "tokens_used": r.get("tokens_used", 0),
                "cost_usd": r.get("cost_usd", 0),
                "telegram_requests": r.get("telegram_requests", 0),
                "prompt_version": prompt_name,
                "model_used": r.get("model_used"),
                "status": r.get("status"),
                "error": r.get("error"),
            }
            writer.writerow(row)

    print(f"Exported {len(results)} results to {output_path}")


async def run_batch(
    session_path: str,
    proxy: Optional[str],
    top: int,
    output_dir: Path,
    prompt_name: Optional[str],
    model: Optional[str],
    posts_count: int,
    delay: float,
    skip_existing: bool,
):
    """Run batch analysis."""
    ensure_dirs()
    await init_db()

    # Load custom prompt if specified
    if prompt_name:
        try:
            system_prompt, user_template = load_prompt(prompt_name)
            logger.info(f"Loaded prompt '{prompt_name}'")
        except FileNotFoundError as e:
            logger.error(str(e))
            return
    else:
        system_prompt = SYSTEM_PROMPT
        user_template = USER_PROMPT_TEMPLATE
        prompt_name = "default"

    # Get top channels
    channels = await get_top_channels(top)
    if not channels:
        logger.error("No channels found")
        return

    logger.info(f"Found {len(channels)} top channels")

    # Skip already analyzed if requested
    if skip_existing:
        async with async_session_maker() as session:
            existing = await session.execute(
                select(LLMAnalysisDB.username)
            )
            existing_usernames = {r[0] for r in existing.fetchall()}
            channels = [c for c in channels if c["username"] not in existing_usernames]
            logger.info(f"After skipping existing: {len(channels)} channels")

    if not channels:
        logger.info("All channels already analyzed")
        return

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
        logger.error("Session not authorized")
        await telegram_client.disconnect()
        return

    me = await telegram_client.get_me()
    logger.info(f"Connected as @{me.username or me.id}")

    # Create LLM client
    llm_client = LLMClient(model=model or config.LLM_MODEL)

    # Create analyzer
    analyzer = LLMAnalyzer(
        telegram_client=telegram_client,
        llm_client=llm_client,
        request_delay=delay,
        max_posts=posts_count,
    )

    # Results
    results = []
    total_tokens = 0
    total_cost = 0.0
    total_tg_requests = 0

    # Print header
    print("\n" + "=" * 80)
    print(f"LLM BATCH ANALYSIS - Top {top} channels")
    print("=" * 80)
    print(f"Prompt: {prompt_name}")
    print(f"Model: {model or config.LLM_MODEL}")
    print(f"Posts per channel: {posts_count}")
    print("=" * 80 + "\n")

    try:
        for i, channel in enumerate(channels, 1):
            username = channel["username"]
            print(f"[{i}/{len(channels)}] @{username} ({channel['subscribers']:,} subs)...", end=" ", flush=True)

            try:
                # Analyze
                result = await analyzer.analyze_channel(username, posts_count)
                tg_requests = 3  # get_entity + GetFullChannel + get_messages

                if result.status == "completed":
                    # Extract full analysis
                    full = result.full_analysis or {}
                    summary = full.get("summary", {})

                    row = {
                        "username": username,
                        "title": channel["title"],
                        "subscribers": channel["subscribers"],
                        "primary_category": result.primary_category,
                        "secondary_categories": result.secondary_categories,
                        "topics": result.topics,
                        "overall_sentiment": result.overall_sentiment,
                        "sentiment_label": result.sentiment_label,
                        "emotional_tone": result.emotional_tone,
                        "propaganda_score": result.propaganda_score,
                        "quality_score": result.quality_score,
                        "originality_score": result.originality_score,
                        "informativeness_score": result.informativeness_score,
                        "professionalism_score": result.professionalism_score,
                        "toxicity_score": result.toxicity_score,
                        "hate_speech_score": result.hate_speech_score,
                        "harassment_score": result.harassment_score,
                        "misinformation_risk": result.misinformation_risk,
                        "adult_content_score": result.adult_content_score,
                        "violence_score": result.violence_score,
                        "toxicity_flags": result.toxicity_flags,
                        "description": summary.get("description"),
                        "target_audience": summary.get("target_audience"),
                        "content_style": summary.get("content_style"),
                        "tokens_used": result.tokens_used,
                        "cost_usd": result.cost_usd,
                        "telegram_requests": tg_requests,
                        "model_used": result.model_used,
                        "status": "ok",
                        "error": None,
                    }

                    total_tokens += result.tokens_used
                    total_cost += result.cost_usd
                    total_tg_requests += tg_requests

                    print(f"✓ {result.primary_category}, Q:{result.quality_score}, T:{result.toxicity_score}, ${result.cost_usd:.4f}")

                    # Save to DB
                    await analyzer.save_result(result)
                else:
                    row = {
                        "username": username,
                        "title": channel["title"],
                        "subscribers": channel["subscribers"],
                        "status": "error",
                        "error": result.error_message,
                        "telegram_requests": tg_requests,
                    }
                    print(f"✗ {result.error_message}")

                results.append(row)

            except FloodWaitError as e:
                print(f"✗ FloodWait {e.seconds}s")
                results.append({
                    "username": username,
                    "title": channel["title"],
                    "subscribers": channel["subscribers"],
                    "status": "flood_wait",
                    "error": f"FloodWait {e.seconds}s",
                })
                break

            except Exception as e:
                print(f"✗ {e}")
                results.append({
                    "username": username,
                    "title": channel["title"],
                    "subscribers": channel["subscribers"],
                    "status": "error",
                    "error": str(e),
                })

            await asyncio.sleep(delay)

    finally:
        await telegram_client.disconnect()

    # Export results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"llm_batch_{prompt_name}_{timestamp}.csv"
    export_to_csv(results, csv_path, prompt_name)

    # Save prompt used
    prompt_path = output_dir / f"llm_batch_{prompt_name}_{timestamp}_prompt.txt"
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write("=== SYSTEM PROMPT ===\n")
        f.write(system_prompt)
        f.write("\n\n=== USER PROMPT TEMPLATE ===\n")
        f.write(user_template)
    print(f"Saved prompt to {prompt_path}")

    # Print summary
    successful = len([r for r in results if r.get("status") == "ok"])
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Channels analyzed: {successful}/{len(channels)}")
    print(f"Total Telegram requests: {total_tg_requests}")
    print(f"Total LLM tokens: {total_tokens:,}")
    print(f"Total LLM cost: ${total_cost:.4f}")
    if successful > 0:
        print(f"Avg tokens/channel: {total_tokens // successful:,}")
        print(f"Avg cost/channel: ${total_cost / successful:.4f}")
    print("=" * 80)

    # Cost projections
    print("\n--- Cost Projections ---")
    for n in [100, 500, 1000, 5000]:
        if successful > 0:
            projected_cost = (total_cost / successful) * n
            projected_requests = (total_tg_requests / successful) * n
            print(f"{n:,} channels: ${projected_cost:.2f} LLM, {projected_requests:.0f} TG requests")


async def main():
    parser = argparse.ArgumentParser(description="LLM Batch Analyzer")
    subparsers = parser.add_subparsers(dest="command")

    # prompts command
    subparsers.add_parser("prompts", help="List saved prompts")

    # save-prompt command
    save_parser = subparsers.add_parser("save-prompt", help="Save current prompt")
    save_parser.add_argument("name", help="Prompt version name")
    save_parser.add_argument("description", nargs="?", default="", help="Description")

    # Main args
    parser.add_argument("--session", "-s", help="Telegram session path")
    parser.add_argument("--proxy", "-p", help="Proxy string")
    parser.add_argument("--top", "-t", type=int, default=10, help="Number of top channels")
    parser.add_argument("--output", "-o", type=Path, default=RESULTS_DIR, help="Output directory")
    parser.add_argument("--prompt", help="Prompt version name to use")
    parser.add_argument("--model", "-m", help="LLM model")
    parser.add_argument("--posts", type=int, default=20, help="Posts per channel")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests")
    parser.add_argument("--skip-existing", action="store_true", help="Skip already analyzed")

    args = parser.parse_args()

    if args.command == "prompts":
        list_prompts()
        return

    if args.command == "save-prompt":
        save_prompt(args.name, args.description)
        return

    if not args.session:
        parser.error("--session is required")

    await run_batch(
        session_path=args.session,
        proxy=args.proxy,
        top=args.top,
        output_dir=args.output,
        prompt_name=args.prompt,
        model=args.model,
        posts_count=args.posts,
        delay=args.delay,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    asyncio.run(main())
