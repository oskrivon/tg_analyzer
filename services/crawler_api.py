"""Client for Crawler API to fetch channels list."""

import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class CrawlerAPIClient:
    """
    Async client for fetching channels from Crawler API.

    Usage:
        async with CrawlerAPIClient() as client:
            channels = await client.get_channels(limit=100)
    """

    def __init__(
        self,
        base_url: str = os.getenv("CRAWLER_API_URL", "http://localhost:8000"),
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get_channels(
        self,
        limit: int = 100,
        page: int = 1,
        min_subs: Optional[int] = None,
        max_subs: Optional[int] = None,
        entity_type: Optional[str] = None,
        sort: str = "subscribers",
        order: str = "desc",
        status: str = "public",
        after_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Fetch channels from crawler API.

        Args:
            limit: Number of channels per page
            page: Page number
            min_subs: Minimum subscribers filter
            max_subs: Maximum subscribers filter
            entity_type: "channel", "group", "supergroup", or None for all
            sort: Sort field (subscribers, crawled_at, id)
            order: "asc" or "desc"
            status: "public" or "private"
            after_id: Return only channels with id > after_id

        Returns:
            List of channel dicts with username, subscribers, etc.
        """
        params = {
            "per_page": limit,
            "page": page,
            "sort": sort,
            "order": order,
            "status": status,
        }
        if entity_type is not None:
            params["entity_type"] = entity_type
        if min_subs is not None:
            params["min_subs"] = min_subs
        if max_subs is not None:
            params["max_subs"] = max_subs
        if after_id is not None:
            params["after_id"] = after_id

        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/channels/search",
                params=params,
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Crawler API error: {resp.status}")
                    return []
                data = await resp.json()
                return data.get("items", [])
        except aiohttp.ClientError as e:
            logger.error(f"Crawler API connection error: {e}")
            return []

    async def get_channels_paginated(
        self,
        total_limit: int = 100,
        per_page: int = 100,
        min_subs: Optional[int] = None,
        max_subs: Optional[int] = None,
        entity_type: Optional[str] = None,
        sort: str = "subscribers",
        order: str = "desc",
        after_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Fetch channels with pagination until total_limit reached.

        Args:
            total_limit: Total number of channels to fetch
            per_page: Channels per API request
            min_subs: Minimum subscribers filter
            max_subs: Maximum subscribers filter
            entity_type: "channel", "group", "supergroup", or None for all
            sort: Sort field (subscribers, crawled_at, id)
            order: Sort order (asc, desc)
            after_id: Start from channels with id > after_id

        Returns:
            List of channel dicts
        """
        all_channels = []
        page = 1

        while len(all_channels) < total_limit:
            channels = await self.get_channels(
                limit=per_page,
                page=page,
                min_subs=min_subs,
                max_subs=max_subs,
                entity_type=entity_type,
                sort=sort,
                order=order,
                after_id=after_id,
            )
            if not channels:
                break

            all_channels.extend(channels)
            logger.info(f"Fetched page {page}: {len(channels)} channels (total: {len(all_channels)})")
            page += 1

            if len(channels) < per_page:
                break

        return all_channels[:total_limit]

    async def get_groups(
        self,
        limit: int = 100,
        page: int = 1,
        sort: str = "crawled_at",
        order: str = "desc",
        status: str = "public",
        after_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Fetch groups from crawler API /groups endpoint.

        Args:
            limit: Number of groups per page
            page: Page number
            sort: Sort field (crawled_at, id)
            order: "asc" or "desc"
            status: "public" or "private"
            after_id: Return only groups with id > after_id

        Returns:
            List of group dicts with username, title, etc.
        """
        params = {
            "per_page": limit,
            "page": page,
            "sort": sort,
            "order": order,
            "status": status,
        }
        if after_id is not None:
            params["after_id"] = after_id

        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/groups",
                params=params,
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Crawler API /groups error: {resp.status}")
                    return []
                data = await resp.json()
                return data.get("items", [])
        except aiohttp.ClientError as e:
            logger.error(f"Crawler API /groups connection error: {e}")
            return []

    async def get_groups_paginated(
        self,
        total_limit: int = 100,
        per_page: int = 100,
        sort: str = "crawled_at",
        order: str = "desc",
        after_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Fetch groups with pagination until total_limit reached.

        Args:
            total_limit: Total number of groups to fetch
            per_page: Groups per API request
            sort: Sort field (crawled_at, id)
            order: Sort order (asc, desc)
            after_id: Start from groups with id > after_id

        Returns:
            List of group dicts
        """
        all_groups = []
        page = 1

        while len(all_groups) < total_limit:
            groups = await self.get_groups(
                limit=per_page,
                page=page,
                sort=sort,
                order=order,
                after_id=after_id,
            )
            if not groups:
                break

            all_groups.extend(groups)
            logger.info(f"Fetched groups page {page}: {len(groups)} groups (total: {len(all_groups)})")
            page += 1

            if len(groups) < per_page:
                break

        return all_groups[:total_limit]
