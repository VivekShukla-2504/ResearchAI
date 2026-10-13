"""MongoDB persistence for anonymous local-development activity only."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)
load_dotenv()


class MongoUnavailable(RuntimeError):
    """Raised when an optional activity persistence operation cannot run."""


class MongoStore:
    """Stores bookmarks, searches, and interests; paper documents stay in CSV/model."""

    def __init__(self, uri: str, database: str, timeout_ms: int = 1500) -> None:
        self.uri = uri
        self.database_name = database
        self.timeout_ms = timeout_ms
        self.client = None
        self.database = None
        self.available = False

    @classmethod
    def from_environment(cls) -> "MongoStore":
        return cls(
            uri=os.getenv("MONGODB_URI", "mongodb://localhost:27017"),
            database=os.getenv("MONGODB_DATABASE", "researchpaper_ai"),
            timeout_ms=int(os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "1500")),
        )

    def connect(self) -> bool:
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=self.timeout_ms)
            self.client.admin.command("ping")
            self.database = self.client[self.database_name]
            self.database.bookmarks.create_index(
                [("session_id", ASCENDING), ("paper_id", ASCENDING)], unique=True
            )
            self.database.search_history.create_index(
                [("session_id", ASCENDING), ("created_at", DESCENDING)]
            )
            self.database.interests.create_index("session_id", unique=True)
            self.available = True
        except PyMongoError as exc:
            logger.warning("MongoDB unavailable; activity persistence disabled (%s)", type(exc).__name__)
            self.available = False
            self.close()
        return self.available

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None
        self.database = None
        self.available = False

    def _collection(self, name: str):
        if not self.available or self.database is None:
            raise MongoUnavailable("MongoDB is unavailable; activity persistence is disabled")
        return self.database[name]

    def _run(self, operation):
        try:
            return operation()
        except PyMongoError as exc:
            logger.warning("MongoDB operation failed; disabling activity persistence (%s)", type(exc).__name__)
            self.close()
            raise MongoUnavailable("MongoDB became unavailable") from exc

    def add_bookmark(self, session_id: str, paper_id: str) -> dict[str, Any]:
        collection = self._collection("bookmarks")
        now = datetime.now(timezone.utc)
        self._run(
            lambda: collection.update_one(
                {"session_id": session_id, "paper_id": paper_id},
                {"$setOnInsert": {"created_at": now}},
                upsert=True,
            )
        )
        return self._run(lambda: collection.find_one({"session_id": session_id, "paper_id": paper_id}))

    def remove_bookmark(self, session_id: str, paper_id: str) -> bool:
        result = self._run(
            lambda: self._collection("bookmarks").delete_one(
                {"session_id": session_id, "paper_id": paper_id}
            )
        )
        return result.deleted_count > 0

    def list_bookmarks(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        return self._run(
            lambda: list(
                self._collection("bookmarks")
                .find({"session_id": session_id}, {"_id": 0})
                .sort("created_at", DESCENDING)
                .limit(limit)
            )
        )

    def add_search(self, session_id: str, query: str, result_count: int) -> None:
        self._run(
            lambda: self._collection("search_history").insert_one(
                {
                    "session_id": session_id,
                    "query": query,
                    "result_count": result_count,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        )

    def list_searches(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        return self._run(
            lambda: list(
                self._collection("search_history")
                .find({"session_id": session_id}, {"_id": 0})
                .sort("created_at", DESCENDING)
                .limit(limit)
            )
        )

    def get_interests(self, session_id: str) -> dict[str, Any] | None:
        return self._run(
            lambda: self._collection("interests").find_one({"session_id": session_id}, {"_id": 0})
        )

    def set_interests(self, session_id: str, terms: list[str]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        self._run(
            lambda: self._collection("interests").update_one(
                {"session_id": session_id},
                {"$set": {"terms": terms, "updated_at": now}},
                upsert=True,
            )
        )
        return self.get_interests(session_id) or {
            "session_id": session_id,
            "terms": terms,
            "updated_at": now,
        }
