"""Shared Notion API client with retry logic and rate limiting."""

import logging
import os
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when a required environment variable is missing."""


def _build_session() -> requests.Session:
    """Create a requests.Session with retry/backoff for Notion API calls."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class NotionClient:
    """Thin wrapper around the Notion REST API with rate-limit throttling."""

    def __init__(self) -> None:
        self.session = _build_session()
        self._headers = self.get_headers()
        self._db_id = self.get_db_id()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_headers() -> dict[str, str]:
        """Return Notion API headers.  Raises ConfigurationError if the key is missing."""
        api_key = os.environ.get("NOTION_API_KEY")
        if not api_key:
            raise ConfigurationError("NOTION_API_KEY environment variable is not set")
        return {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    @staticmethod
    def get_db_id() -> str:
        """Return the Notion Training DB ID.  Raises ConfigurationError if missing."""
        db_id = os.environ.get("NOTION_TRAINING_DB_ID")
        if not db_id:
            raise ConfigurationError(
                "NOTION_TRAINING_DB_ID environment variable is not set"
            )
        return db_id

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep briefly to stay within the Notion 3-req/s rate limit."""
        time.sleep(0.35)

    def check_existing(self, external_id: str) -> bool:
        """Return True if a page with this External ID already exists."""
        self._rate_limit()
        resp = self.session.post(
            f"{NOTION_API_URL}/databases/{self._db_id}/query",
            headers=self._headers,
            json={
                "filter": {
                    "property": "External ID",
                    "rich_text": {"equals": external_id},
                }
            },
            timeout=30,
        )
        resp.raise_for_status()
        return len(resp.json().get("results", [])) > 0

    def create_page(self, properties: dict[str, Any]) -> dict[str, Any]:
        """Create a page in the training sessions database."""
        return self.create_page_in_db(self._db_id, properties)

    def create_page_in_db(
        self, db_id: str, properties: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a page in any Notion database."""
        self._rate_limit()
        resp = self.session.post(
            f"{NOTION_API_URL}/pages",
            headers=self._headers,
            json={
                "parent": {"database_id": db_id},
                "properties": properties,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    def check_existing_in_db(self, db_id: str, external_id: str) -> bool:
        """Return True if a page with this External ID already exists in any DB."""
        self._rate_limit()
        resp = self.session.post(
            f"{NOTION_API_URL}/databases/{db_id}/query",
            headers=self._headers,
            json={
                "filter": {
                    "property": "External ID",
                    "rich_text": {"equals": external_id},
                }
            },
            timeout=30,
        )
        resp.raise_for_status()
        return len(resp.json().get("results", [])) > 0

    # ------------------------------------------------------------------
    # Generic API methods (used by dashboard updater, etc.)
    # ------------------------------------------------------------------

    def query_database(
        self,
        db_id: str,
        filter_obj: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a Notion database with optional filter/sorts. Handles pagination."""
        results: list[dict[str, Any]] = []
        payload: dict[str, Any] = {}
        if filter_obj:
            payload["filter"] = filter_obj
        if sorts:
            payload["sorts"] = sorts

        has_more = True
        while has_more:
            self._rate_limit()
            resp = self.session.post(
                f"{NOTION_API_URL}/databases/{db_id}/query",
                headers=self._headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            if has_more:
                payload["start_cursor"] = data["next_cursor"]
        return results

    def get_block_children(self, block_id: str) -> list[dict[str, Any]]:
        """Get all child blocks of a block/page. Handles pagination."""
        results: list[dict[str, Any]] = []
        url = f"{NOTION_API_URL}/blocks/{block_id}/children"
        params: dict[str, str] = {}

        has_more = True
        while has_more:
            self._rate_limit()
            resp = self.session.get(
                url, headers=self._headers, params=params, timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            if has_more:
                params["start_cursor"] = data["next_cursor"]
        return results

    def delete_block(self, block_id: str) -> None:
        """Delete (archive) a single block."""
        self._rate_limit()
        resp = self.session.delete(
            f"{NOTION_API_URL}/blocks/{block_id}",
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()

    def append_block_children(
        self, block_id: str, children: list[dict[str, Any]]
    ) -> None:
        """Append child blocks to a block/page. Chunks in batches of 100."""
        for i in range(0, len(children), 100):
            chunk = children[i : i + 100]
            self._rate_limit()
            resp = self.session.patch(
                f"{NOTION_API_URL}/blocks/{block_id}/children",
                headers=self._headers,
                json={"children": chunk},
                timeout=30,
            )
            resp.raise_for_status()
