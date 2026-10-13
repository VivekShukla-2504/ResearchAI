from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pymongo.errors import ServerSelectionTimeoutError

from researchpaper_ai.mongo_store import MongoStore, MongoUnavailable


def test_connect_creates_only_activity_indexes(monkeypatch):
    client = MagicMock()
    database = MagicMock()
    client.__getitem__.return_value = database
    monkeypatch.setattr("researchpaper_ai.mongo_store.MongoClient", lambda *args, **kwargs: client)

    store = MongoStore("mongodb://example", "test_db")
    assert store.connect() is True
    client.admin.command.assert_called_once_with("ping")
    database.bookmarks.create_index.assert_called_once()
    database.search_history.create_index.assert_called_once()
    database.interests.create_index.assert_called_once()
    assert not any(".papers" in str(call) for call in database.mock_calls)


def test_activity_operations_are_session_scoped(monkeypatch):
    client = MagicMock()
    database = MagicMock()
    collections = {name: MagicMock() for name in ("bookmarks", "search_history", "interests")}
    database.__getitem__.side_effect = collections.__getitem__
    database.bookmarks = collections["bookmarks"]
    database.search_history = collections["search_history"]
    database.interests = collections["interests"]
    client.__getitem__.return_value = database
    monkeypatch.setattr("researchpaper_ai.mongo_store.MongoClient", lambda *args, **kwargs: client)
    store = MongoStore("mongodb://example", "test_db")
    assert store.connect() is True

    saved_at = datetime.now(timezone.utc)
    database.bookmarks.find_one.return_value = {
        "session_id": "session-a", "paper_id": "paper-1", "created_at": saved_at
    }
    assert store.add_bookmark("session-a", "paper-1")["paper_id"] == "paper-1"
    database.bookmarks.update_one.assert_called_once()
    assert database.bookmarks.update_one.call_args.args[0] == {
        "session_id": "session-a", "paper_id": "paper-1"
    }

    store.add_search("session-a", "graph papers", 4)
    search_document = database.search_history.insert_one.call_args.args[0]
    assert search_document["session_id"] == "session-a"
    assert search_document["query"] == "graph papers"

    database.interests.find_one.return_value = {
        "session_id": "session-a", "terms": ["cs.AI"], "updated_at": saved_at
    }
    interests = store.set_interests("session-a", ["cs.AI"])
    assert interests["terms"] == ["cs.AI"]
    assert database.interests.update_one.call_args.args[0] == {"session_id": "session-a"}


def test_connection_failure_is_nonfatal_and_error_details_are_redacted(monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise ServerSelectionTimeoutError("offline-private-connection-marker")

    monkeypatch.setattr("researchpaper_ai.mongo_store.MongoClient", unavailable)
    store = MongoStore("mongodb://offline", "test_db", timeout_ms=1)
    with caplog.at_level("WARNING"):
        assert store.connect() is False
    assert "offline-private-connection-marker" not in caplog.text
    with pytest.raises(MongoUnavailable, match="unavailable"):
        store.list_bookmarks("session", 10)


def test_runtime_database_error_closes_client_and_disables_store(monkeypatch, caplog):
    client = MagicMock()
    database = MagicMock()
    client.__getitem__.return_value = database
    monkeypatch.setattr("researchpaper_ai.mongo_store.MongoClient", lambda *args, **kwargs: client)
    store = MongoStore("mongodb://example", "test_db")
    assert store.connect() is True

    def fail_with_driver_error():
        raise ServerSelectionTimeoutError("runtime-private-connection-marker")

    with caplog.at_level("WARNING"), pytest.raises(MongoUnavailable, match="became unavailable"):
        store._run(fail_with_driver_error)

    assert store.available is False
    assert store.client is None
    assert store.database is None
    client.close.assert_called_once()
    assert "runtime-private-connection-marker" not in caplog.text
