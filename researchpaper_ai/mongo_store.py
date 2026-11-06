"""MongoDB persistence for anonymous local-development activity only."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)
load_dotenv()


class MongoUnavailable(RuntimeError):
    """Raised when an optional activity persistence operation cannot run."""


class DuplicateUserError(ValueError):
    """Raised when attempting to create a user whose email or ID already exists."""


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
            self.database.users.create_index("email", unique=True)
            self.database.users.create_index("user_id", unique=True)
            self.database.otps.create_index([("email", ASCENDING), ("purpose", ASCENDING)])
            self.database.otps.create_index("expires_at", expireAfterSeconds=0)
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
        except DuplicateKeyError:
            # Business conflict: re-raise directly without closing driver or disabling store
            raise
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

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        clean = email.strip().lower()
        return self._run(lambda: self._collection("users").find_one({"email": clean}, {"_id": 0}))

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self._run(lambda: self._collection("users").find_one({"user_id": user_id}, {"_id": 0}))

    def create_user(
        self,
        *,
        email: str,
        name: str,
        password_hash: str | None = None,
        auth_provider: str = "local",
        is_verified: bool = False,
        picture: str | None = None,
    ) -> dict[str, Any]:
        clean_email = email.strip().lower()
        now = datetime.now(timezone.utc)
        user_id = f"user_{secrets.token_hex(12)}"
        user_doc = {
            "user_id": user_id,
            "email": clean_email,
            "name": name.strip(),
            "password_hash": password_hash,
            "token_version": 0,
            "auth_provider": auth_provider,
            "is_verified": is_verified,
            "picture": picture,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._run(lambda: self._collection("users").insert_one(user_doc))
        except DuplicateKeyError as exc:
            raise DuplicateUserError(f"An account with email {clean_email} already exists.") from exc
        clean_user = dict(user_doc)
        clean_user.pop("password_hash", None)
        clean_user.pop("_id", None)
        return clean_user

    def update_user(self, user_id: str, fields: dict[str, Any]) -> bool:
        update_doc = dict(fields)
        update_doc["updated_at"] = datetime.now(timezone.utc)
        result = self._run(
            lambda: self._collection("users").update_one(
                {"user_id": user_id},
                {"$set": update_doc},
            )
        )
        return result.modified_count > 0

    def update_password_and_revoke_tokens(self, user_id: str, password_hash: str) -> bool:
        result = self._run(
            lambda: self._collection("users").update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "password_hash": password_hash,
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$inc": {"token_version": 1},
                },
            )
        )
        return result.modified_count > 0

    def revoke_user_tokens(self, user_id: str) -> bool:
        result = self._run(
            lambda: self._collection("users").update_one(
                {"user_id": user_id},
                {
                    "$inc": {"token_version": 1},
                    "$set": {"updated_at": datetime.now(timezone.utc)},
                },
            )
        )
        return result.modified_count > 0

    def save_otp(self, email: str, otp: str, purpose: str, ttl_minutes: int = 10) -> None:
        clean = email.strip().lower()
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + ttl_minutes * 60, timezone.utc)
        self._run(
            lambda: self._collection("otps").update_one(
                {"email": clean, "purpose": purpose},
                {"$set": {"otp": otp, "expires_at": expires_at, "created_at": now}},
                upsert=True,
            )
        )

    def verify_and_consume_otp(self, email: str, otp: str, purpose: str) -> bool:
        clean = email.strip().lower()
        now = datetime.now(timezone.utc)
        record = self._run(
            lambda: self._collection("otps").find_one({"email": clean, "purpose": purpose})
        )
        if not record:
            return False
        exp = record.get("expires_at")
        if exp:
            exp_utc = exp.replace(tzinfo=timezone.utc if exp.tzinfo is None else exp.tzinfo)
            if exp_utc < now:
                self._run(lambda: self._collection("otps").delete_one({"_id": record["_id"]}))
                return False
        if str(record.get("otp")).strip() != otp.strip():
            return False
        self._run(lambda: self._collection("otps").delete_one({"_id": record["_id"]}))
        return True
