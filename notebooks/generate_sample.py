"""
Generate a SYNTHETIC sample dataset for the analysis notebook.

No real Telegram data is used or shipped. This script fabricates a plausible
population of public channels with realistic, correlated metrics so the
notebook can demonstrate the analysis end-to-end and reproducibly.

The engagement metrics (ERR, reach) and the 0-100 `preliminary_score` are
computed with the SAME formulas the production code uses
(see utils/metrics.py and services/preliminary_scorer.py), so the sample is
faithful to what the real crawler produces.

Run:  python notebooks/generate_sample.py
Out:  data/sample/channels_sample.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

RNG = np.random.default_rng(20260701)
N = 3000

# Category mix roughly mirroring what a broad RU/EN public-channel crawl surfaces.
CATEGORIES = {
    "news": 0.14, "crypto": 0.11, "business": 0.10, "entertainment": 0.10,
    "tech": 0.09, "education": 0.08, "lifestyle": 0.07, "gaming": 0.07,
    "politics": 0.06, "music": 0.05, "health": 0.05, "sports": 0.04,
    "anime": 0.02, "movies": 0.01, "gacha": 0.01,
}
CATS = list(CATEGORIES)
CAT_P = np.array(list(CATEGORIES.values()))
CAT_P = CAT_P / CAT_P.sum()

# Adjective/noun pools to build obviously-synthetic but readable titles.
ADJ = ["Daily", "Global", "Prime", "Insider", "Open", "Smart", "Alpha",
       "Nova", "Bright", "Core", "Peak", "Vivid", "Urban", "Neon", "Quiet"]
NOUN = {
    "news": ["News", "Wire", "Report", "Digest"],
    "crypto": ["Crypto", "Chain", "Coins", "DeFi"],
    "business": ["Capital", "Market", "Ventures", "Money"],
    "entertainment": ["Memes", "Fun", "Vibes", "Laughs"],
    "tech": ["Tech", "Code", "Dev", "AI"],
    "education": ["Academy", "Lessons", "Learn", "Course"],
    "lifestyle": ["Style", "Living", "Home", "Travel"],
    "gaming": ["Games", "Arena", "Quest", "Esports"],
    "politics": ["Politics", "Policy", "Debate", "Forum"],
    "music": ["Music", "Beats", "Sound", "Tracks"],
    "health": ["Health", "Wellness", "Fit", "Care"],
    "sports": ["Sports", "League", "Match", "Arena"],
    "anime": ["Anime", "Manga", "Otaku", "Sakura"],
    "movies": ["Cinema", "Films", "Screen", "Reel"],
    "gacha": ["Gacha", "OC", "GLMV", "Club"],
}


def err_score(err: float) -> float:
    if err >= 5: return 25
    if err >= 2: return 20
    if err >= 1: return 15
    if err >= 0.5: return 10
    return err * 20


def reach_score(reach: float) -> float:
    if reach >= 50: return 25
    if reach >= 30: return 20
    if reach >= 20: return 15
    if reach >= 10: return 10
    return reach / 2


def comments_score(has_linked_chat: bool, avg_comments: float) -> float:
    if has_linked_chat and avg_comments > 10: return 20
    if has_linked_chat and avg_comments > 5: return 15
    if has_linked_chat and avg_comments > 0: return 10
    return 0


def freq_score(ppd: float) -> float:
    if 1 <= ppd <= 3: return 15
    if 0.5 <= ppd < 1 or 3 < ppd <= 5: return 10
    if 0.2 <= ppd < 0.5 or 5 < ppd <= 10: return 5
    return 0


def subs_score(subs: int) -> float:
    if subs >= 100000: return 15
    if subs >= 50000: return 12
    if subs >= 10000: return 10
    if subs >= 5000: return 7
    if subs >= 1000: return 5
    return 2


def preliminary_score(err, reach, has_linked_chat, avg_comments, ppd, subs) -> float:
    return round(
        err_score(err) + reach_score(reach)
        + comments_score(has_linked_chat, avg_comments)
        + freq_score(ppd) + subs_score(subs),
        2,
    )


def make_channel(i: int) -> dict:
    cat = RNG.choice(CATS, p=CAT_P)

    # Subscribers: heavy-tailed log-normal (the classic long tail).
    subs = int(np.clip(10 ** RNG.normal(3.6, 0.7), 100, 3_000_000))

    # Latent "audience quality" — genuine reach decays as channels grow.
    size_penalty = np.clip((np.log10(subs) - 3.0) * 6, 0, 22)
    reach = float(np.clip(RNG.normal(34 - size_penalty, 8), 0.3, 95))

    # Bots: most channels are clean; a minority bought their audience.
    is_vanity = RNG.random() < 0.08
    if is_vanity:
        bot_ratio = float(np.clip(RNG.normal(0.55, 0.15), 0.30, 0.9))
        reach = float(np.clip(reach * RNG.uniform(0.15, 0.4), 0.2, 95))  # dead audience
    else:
        bot_ratio = float(np.clip(RNG.normal(0.05, 0.04), 0.0, 0.25))

    avg_views = max(1, int(subs * reach / 100))

    # ERR: small channels engage harder; bots kill engagement.
    base_err = np.clip(RNG.normal(3.2, 1.6), 0.05, 12) * (1 - bot_ratio)
    base_err *= 1 + max(0, (4.5 - np.log10(subs))) * 0.15
    err = float(round(np.clip(base_err, 0.02, 14), 2))

    # Split engagement into reactions / comments / forwards off ERR.
    total_eng = err / 100 * avg_views
    avg_reactions = int(max(0, total_eng * RNG.uniform(0.55, 0.75)))
    avg_forwards = int(max(0, total_eng * RNG.uniform(0.1, 0.25)))
    has_linked_chat = RNG.random() < 0.5
    avg_comments = int(max(0, total_eng * RNG.uniform(0.1, 0.25))) if has_linked_chat else 0

    # Posting cadence: mostly steady, some dormant, some spammy.
    roll = RNG.random()
    if roll < 0.10:
        ppd = float(round(RNG.uniform(0.0, 0.2), 2))       # dormant
    elif roll < 0.16:
        ppd = float(round(RNG.uniform(10, 40), 1))         # spammy/aggregators
    else:
        ppd = float(round(np.clip(RNG.normal(1.8, 1.1), 0.2, 8), 2))

    prelim = preliminary_score(err, reach, has_linked_chat, avg_comments, ppd, subs)
    # Health score: preliminary quality eroded by inauthentic (bot) audience.
    health = round(prelim * (1 - 0.6 * bot_ratio), 1)

    return {
        "username": f"@{cat}_{RNG.choice(ADJ).lower()}_{i:04d}",
        "title": f"{RNG.choice(ADJ)} {RNG.choice(NOUN[cat])}",
        "subscribers": subs,
        "avg_views": avg_views,
        "avg_reactions": avg_reactions,
        "avg_comments": avg_comments,
        "avg_forwards": avg_forwards,
        "posts_per_day": ppd,
        "has_linked_chat": has_linked_chat,
        "err": err,
        "reach": round(reach, 2),
        "bot_ratio": round(bot_ratio, 3),
        "detected_category": cat,
        "preliminary_score": prelim,
        "health_score": health,
    }


def main() -> None:
    rows = [make_channel(i) for i in range(N)]
    out = Path(__file__).resolve().parents[1] / "data" / "sample" / "channels_sample.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} synthetic channels -> {out}")


if __name__ == "__main__":
    main()
