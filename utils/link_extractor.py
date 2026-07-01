"""Utility to extract Telegram channel/chat links from text and message entities."""

import re
from typing import Set
from telethon.tl.types import (
    MessageEntityUrl,
    MessageEntityTextUrl,
    MessageEntityMention,
)


# Regex patterns for Telegram links
TG_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{5,32})",
    re.IGNORECASE
)

# Mention pattern (@username)
MENTION_PATTERN = re.compile(
    r"@([a-zA-Z0-9_]{5,32})",
)


def extract_telegram_links(text: str) -> Set[str]:
    """Extract Telegram usernames from text using regex."""
    if not text:
        return set()

    usernames = set()

    # Skip common paths
    skip_paths = {"s", "c", "joinchat", "addstickers", "login", "share"}

    # Extract from t.me/username links
    for match in TG_URL_PATTERN.finditer(text):
        username = match.group(1).lower()
        if username not in skip_paths:
            usernames.add(username)

    # Extract from @mentions
    for match in MENTION_PATTERN.finditer(text):
        username = match.group(1).lower()
        usernames.add(username)

    return usernames


def extract_from_message_entities(message) -> Set[str]:
    """Extract Telegram usernames from message entities."""
    usernames = set()
    skip_paths = {"s", "c", "joinchat", "addstickers", "login", "share"}

    if not hasattr(message, "entities") or not message.entities:
        return usernames

    for entity in message.entities:
        # URL entities
        if isinstance(entity, (MessageEntityUrl, MessageEntityTextUrl)):
            if hasattr(entity, "url"):
                url = entity.url
            else:
                start = entity.offset
                end = entity.offset + entity.length
                url = message.text[start:end] if message.text else ""

            match = TG_URL_PATTERN.match(url)
            if match:
                username = match.group(1).lower()
                if username not in skip_paths:
                    usernames.add(username)

        # Mention entities
        elif isinstance(entity, MessageEntityMention):
            start = entity.offset
            end = entity.offset + entity.length
            mention = message.text[start:end] if message.text else ""

            if mention.startswith("@"):
                username = mention[1:].lower()
                usernames.add(username)

    return usernames


def extract_all_links_from_message(message) -> Set[str]:
    """Extract all Telegram links from a message (text + entities)."""
    usernames = set()

    # Extract from text
    if hasattr(message, "message") and message.message:
        usernames.update(extract_telegram_links(message.message))

    # Extract from entities
    usernames.update(extract_from_message_entities(message))

    return usernames


def extract_from_messages(messages: list) -> Set[str]:
    """Extract all unique Telegram usernames from a list of messages."""
    all_usernames = set()

    for msg in messages:
        all_usernames.update(extract_all_links_from_message(msg))

    return all_usernames
