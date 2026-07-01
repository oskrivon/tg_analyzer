"""Keyword-based category detection for channels/groups.

This is a free (no LLM required) approach to detect categories
based on keywords in the channel/group description and title.
LLM analysis can later refine the category.
"""

import re
from typing import Optional, Tuple

# Category keywords mapping
# Keys: category names
# Values: list of keywords (lowercase, supports both EN and RU)
CATEGORY_KEYWORDS = {
    "crypto": [
        # English
        "crypto", "bitcoin", "btc", "eth", "ethereum", "blockchain", "nft",
        "defi", "trading", "binance", "coinbase", "altcoin", "token", "wallet",
        "mining", "staking", "airdrop", "web3", "dex", "cex", "hodl", "memecoin",
        # Russian
        "крипто", "биткоин", "эфир", "блокчейн", "трейдинг", "токен",
        "майнинг", "стейкинг", "кошелек", "криптовалюта", "криптовалют",
    ],
    "tech": [
        # English
        "tech", "code", "coding", "developer", "programming", "software",
        "ai", "ml", "python", "javascript", "java", "rust", "golang",
        "devops", "linux", "windows", "macos", "ios", "android", "api",
        "backend", "frontend", "fullstack", "database", "cloud", "aws",
        "github", "gitlab", "docker", "kubernetes", "cybersecurity",
        # Russian
        "разработка", "программирование", "разработчик", "айти",
        "программист", "технологии", "инженер", "нейросеть", "нейросети",
    ],
    "news": [
        # English
        "news", "breaking", "headlines", "report", "press", "media",
        "journal", "times", "herald", "gazette", "tribune",
        # Russian  (removed "инфо", "обзор", "дайджест" - too generic)
        "новости", "срочно", "события", "сводка", "хроника", "сми",
    ],
    "politics": [
        # English
        "politics", "government", "election", "parliament", "senate",
        "congress", "president", "minister", "democracy", "vote", "policy",
        # Russian
        "политика", "выборы", "власть", "правительство", "президент",
        "депутат", "парламент", "госдума", "оппозиция", "путин", "война",
    ],
    "entertainment": [
        # English
        "meme", "memes", "fun", "humor", "comedy", "funny", "joke", "lol",
        "entertainment", "viral", "trending",
        # Russian
        "мемы", "мем", "юмор", "приколы", "смешно", "ржака", "угар",
        "развлечения", "веселье", "смешные",
    ],
    "education": [
        # English
        "learn", "learning", "course", "courses", "tutorial", "education",
        "study", "student", "teacher", "school", "university", "lesson",
        "training", "academy", "certificate", "degree",
        # Russian
        "обучение", "курс", "курсы", "урок", "уроки", "учеба", "студент",
        "преподаватель", "школа", "университет", "образование", "егэ", "огэ",
    ],
    "business": [
        # English
        "business", "finance", "invest", "investment", "startup", "entrepreneur",
        "money", "profit", "income", "revenue", "market", "stock", "forex",
        "economy", "bank", "banking", "venture", "capital", "salary",
        # Russian
        "бизнес", "инвестиции", "стартап", "предприниматель", "деньги",
        "прибыль", "доход", "рынок", "акции", "форекс", "экономика",
        "банк", "финансы", "капитал", "заработок", "зарплата",
    ],
    "lifestyle": [
        # English
        "fashion", "beauty", "style", "makeup", "skincare", "hair",
        "outfit", "clothes", "shopping", "luxury", "travel", "food",
        "recipe", "cooking", "home", "decor", "interior", "diy",
        # Russian
        "мода", "красота", "стиль", "макияж", "косметика", "одежда",
        "шопинг", "люкс", "путешествия", "еда", "рецепт", "готовка",
        "интерьер", "декор", "рецепты",
    ],
    "gaming": [
        # English
        "game", "games", "gaming", "gamer", "esport", "esports", "steam",
        "playstation", "xbox", "nintendo", "pc gaming", "rpg", "fps",
        "mmorpg", "twitch", "streamer", "minecraft", "fortnite", "roblox",
        "gacha", "genshin", "valorant", "dota", "csgo", "cs2",
        # Russian
        "игры", "игра", "геймер", "киберспорт", "стрим", "стример",
        "плейстейшн", "иксбокс", "майнкрафт", "роблокс", "дота",
    ],
    "anime": [
        # English
        "anime", "manga", "otaku", "waifu", "cosplay", "hentai", "kawaii",
        "naruto", "one piece", "attack on titan", "demon slayer", "jujutsu",
        # Russian
        "аниме", "манга", "отаку", "косплей", "анимешник", "тян", "кун",
        "наруто", "ван пис", "титаны",
    ],
    "gacha": [
        # Gacha Life / Gacha Club specific (very popular in Russian TG)
        "gacha", "гача", "гачер", "гачеры", "gacha life", "gacha club",
        "гача лайф", "гача клуб", "оц", "oc", "лоты", "лот",
        # Common gacha channel terms
        "приписка", "вп", "мини", "глмв", "glmv", "gcmv", "gmv",
    ],
    "sports": [
        # English
        "sport", "sports", "football", "soccer", "basketball", "tennis",
        "hockey", "baseball", "golf", "mma", "ufc", "boxing", "fitness",
        "gym", "workout", "athlete", "team", "match", "league",
        # Russian
        "спорт", "футбол", "баскетбол", "теннис", "хоккей", "бокс",
        "фитнес", "тренировка", "зал", "атлет", "матч", "лига",
    ],
    "health": [
        # English
        "health", "healthy", "fitness", "medical", "medicine", "doctor",
        "hospital", "wellness", "nutrition", "diet", "mental health",
        "therapy", "psychology", "yoga", "meditation",
        # Russian
        "здоровье", "медицина", "врач", "больница", "питание", "диета",
        "психология", "терапия", "йога", "медитация", "зож",
    ],
    "music": [
        # English
        "music", "song", "songs", "album", "artist", "band", "concert",
        "spotify", "playlist", "dj", "producer", "beats", "rap", "hip hop",
        "rock", "pop", "edm", "jazz", "classical",
        # Russian
        "музыка", "песни", "альбом", "артист", "концерт", "плейлист",
        "рэп", "хип-хоп", "рок", "поп", "джаз", "треки", "трек",
    ],
    "movies": [
        # English
        "movie", "movies", "film", "films", "cinema", "netflix", "series",
        "tv show", "actor", "actress", "director", "trailer", "review",
        "hollywood",
        # Russian
        "фильм", "фильмы", "кино", "сериал", "сериалы", "актер", "актриса",
        "режиссер", "трейлер", "кинотеатр",
    ],
    "art": [
        # English
        "art", "artist", "painting", "drawing", "illustration", "design",
        "graphic", "photography", "photo", "creative", "gallery", "museum",
        "sculpture", "digital art", "artwork",
        # Russian
        "искусство", "художник", "живопись", "рисунок", "иллюстрация",
        "дизайн", "графика", "фотография", "фото", "галерея", "музей",
        "арт", "арты", "рисунки",
    ],
    "science": [
        # English
        "science", "research", "experiment", "physics", "chemistry",
        "biology", "astronomy", "space", "nasa", "scientist", "laboratory",
        "discovery", "nature",
        # Russian
        "наука", "исследование", "физика", "химия", "биология",
        "астрономия", "космос", "ученый", "лаборатория", "открытие",
    ],
    "adult": [
        # English
        "18+", "nsfw", "adult", "xxx", "porn", "sex", "erotic", "onlyfans",
        # Russian
        "18+", "взрослые", "эротика", "интим", "порно",
    ],
    "betting": [
        # English
        "bet", "betting", "casino", "gambling", "poker", "slots",
        "bookmaker", "odds", "jackpot", "roulette",
        # Russian
        "ставки", "казино", "покер", "слоты", "букмекер", "рулетка",
        "азартные", "выигрыш", "1xbet", "фонбет",
    ],
    "dating": [
        # English
        "dating", "date", "relationship", "love", "singles", "tinder",
        "match", "romance",
        # Russian
        "знакомства", "отношения", "любовь", "пара", "свидание",
        "девушки", "парни",
    ],
}


def detect_category(text: str, title: str = "") -> Tuple[Optional[str], float]:
    """
    Detect category from text (description) and title using keywords.

    Args:
        text: Channel/group description (about)
        title: Channel/group title (optional, adds context)

    Returns:
        Tuple of (category, confidence) or (None, 0.0) if no match.
        confidence is calculated as matches / min(total_keywords, 5)
        capped at 1.0
    """
    if not text and not title:
        return None, 0.0

    # Combine and normalize text
    combined = f"{title} {text}".lower()

    # Remove special characters but keep spaces
    combined = re.sub(r'[^\w\s]', ' ', combined)

    # Split into words for whole-word matching
    words = set(combined.split())

    # Count matches for each category
    category_scores: dict[str, int] = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        matches = 0
        for keyword in keywords:
            # Check if keyword is in words (whole word) or in combined text (substring for multi-word)
            if ' ' in keyword:
                # Multi-word keyword: check substring
                if keyword in combined:
                    matches += 1
            else:
                # Single word: check whole word match
                if keyword in words:
                    matches += 1

        if matches > 0:
            category_scores[category] = matches

    if not category_scores:
        return None, 0.0

    # Find best category
    best_category = max(category_scores, key=category_scores.get)
    best_matches = category_scores[best_category]

    # Calculate confidence
    # More matches = higher confidence, but cap at reasonable threshold
    # 1 match = 0.2, 2 matches = 0.4, 3+ matches = 0.6+, 5+ matches = 1.0
    confidence = min(best_matches / 5.0, 1.0)

    return best_category, round(confidence, 2)


def get_all_categories() -> list[str]:
    """Return list of all available categories."""
    return sorted(CATEGORY_KEYWORDS.keys())


def get_category_keywords(category: str) -> list[str]:
    """Return keywords for a specific category."""
    return CATEGORY_KEYWORDS.get(category, [])
