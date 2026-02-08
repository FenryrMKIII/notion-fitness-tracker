"""Tests for scripts.notion_client."""

import pytest

from scripts.notion_client import ConfigurationError, NotionClient


class TestConfigurationError:
    def test_is_exception(self) -> None:
        assert issubclass(ConfigurationError, Exception)

    def test_message(self) -> None:
        exc = ConfigurationError("oops")
        assert str(exc) == "oops"


class TestGetHeaders:
    def test_raises_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        with pytest.raises(ConfigurationError, match="NOTION_API_KEY"):
            NotionClient.get_headers()

    def test_returns_headers_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTION_API_KEY", "test-key-123")
        headers = NotionClient.get_headers()
        assert headers["Authorization"] == "Bearer test-key-123"
        assert "Notion-Version" in headers
        assert headers["Content-Type"] == "application/json"


class TestGetDbId:
    def test_raises_when_db_id_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOTION_TRAINING_DB_ID", raising=False)
        with pytest.raises(ConfigurationError, match="NOTION_TRAINING_DB_ID"):
            NotionClient.get_db_id()

    def test_returns_db_id_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTION_TRAINING_DB_ID", "abc123")
        assert NotionClient.get_db_id() == "abc123"


class TestNotionClientInit:
    def test_raises_without_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        monkeypatch.delenv("NOTION_TRAINING_DB_ID", raising=False)
        with pytest.raises(ConfigurationError):
            NotionClient()

    def test_initializes_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOTION_API_KEY", "test-key")
        monkeypatch.setenv("NOTION_TRAINING_DB_ID", "test-db-id")
        client = NotionClient()
        assert client._db_id == "test-db-id"
        assert client.session is not None
