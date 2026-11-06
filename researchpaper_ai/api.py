"""FastAPI layer for the Phase 2 fitted recommendation engine."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Path as ApiPath, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .data import Paper
from .engine import ResearchPaperRecommender
from .model_artifact import load_model_artifact
from .mongo_store import MongoStore, MongoUnavailable
from .auth import (
    hash_password,
    verify_password,
    create_jwt,
    decode_jwt,
    generate_otp,
    verify_google_id_token,
    send_otp_email,
)

load_dotenv()
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PaperResult(BaseModel):
    paper_id: str
    title: str
    abstract: str
    terms: list[str]
    similarity: float | None = None
    matching_terms: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    results: list[PaperResult]
    history_saved: bool


class SuggestResponse(BaseModel):
    query: str
    suggestions: list[str]


class PaperDetails(PaperResult):
    source_rows: list[int]


class RecommendationResponse(BaseModel):
    paper_id: str
    recommendations: list[PaperResult]


class PersonalizedResponse(BaseModel):
    recommendations: list[PaperResult]
    based_on: dict[str, int]


class BookmarkRequest(BaseModel):
    paper_id: str = Field(min_length=1, max_length=80)

    @field_validator("paper_id")
    @classmethod
    def normalize_paper_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("paper_id must contain non-whitespace text")
        return cleaned


class InterestRequest(BaseModel):
    terms: list[str] = Field(max_length=50)

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        cleaned = sorted({value.strip() for value in values if value.strip()}, key=str.casefold)
        if any(len(value) > 100 for value in cleaned):
            raise ValueError("Each interest must be at most 100 characters")
        return cleaned


class BookmarkEntry(BaseModel):
    paper_id: str
    title: str
    created_at: datetime


class BookmarkList(BaseModel):
    bookmarks: list[BookmarkEntry]


class SearchHistoryEntry(BaseModel):
    query: str
    result_count: int
    created_at: datetime


class SearchHistoryList(BaseModel):
    history: list[SearchHistoryEntry]


class InterestResponse(BaseModel):
    terms: list[str]
    updated_at: datetime | None = None


class SendOtpRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    purpose: str = "signup"

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        c = v.strip().lower()
        if "@" not in c or "." not in c:
            raise ValueError("Invalid email address")
        return c


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    otp: str = Field(min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        c = v.strip().lower()
        if "@" not in c or "." not in c:
            raise ValueError("Invalid email address")
        return c


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        c = v.strip().lower()
        if "@" not in c or "." not in c:
            raise ValueError("Invalid email address")
        return c


class LoginOtpRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    otp: str = Field(min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        c = v.strip().lower()
        if "@" not in c or "." not in c:
            raise ValueError("Invalid email address")
        return c


class GoogleAuthRequest(BaseModel):
    credential: str = Field(min_length=10)


class ResetPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    otp: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=6, max_length=128)

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        c = v.strip().lower()
        if "@" not in c or "." not in c:
            raise ValueError("Invalid email address")
        return c


class UserProfile(BaseModel):
    user_id: str
    email: str
    name: str
    auth_provider: str = "local"
    picture: str | None = None
    created_at: datetime | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserProfile
    message: str = "Authenticated successfully"


SessionId = Annotated[
    str,
    Header(
        alias="X-Session-ID",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Untrusted local-development session label; not authentication.",
    ),
]


def _resolve_path(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


def _paper_response(paper: Paper) -> PaperDetails:
    return PaperDetails(
        paper_id=paper.paper_id,
        title=paper.title,
        abstract=paper.abstract,
        terms=list(paper.terms),
        source_rows=list(paper.source_rows),
    )


def create_app(
    *,
    model: ResearchPaperRecommender | None = None,
    artifact_path: str | Path | None = None,
    mongo_store_factory: Callable[[], MongoStore] | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    artifact = _resolve_path(
        artifact_path or os.getenv("MODEL_ARTIFACT_PATH", "artifacts/recommender.joblib")
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = model or load_model_artifact(artifact)
        store_factory = mongo_store_factory or MongoStore.from_environment
        store = None
        try:
            store = store_factory()
            store.connect()
        except Exception as exc:  # API retrieval remains available without MongoDB.
            # Avoid logging driver/configuration exception text, which can include
            # connection details supplied in the Mongo URI.
            logger.warning("Could not initialize MongoDB activity store (%s)", type(exc).__name__)
            if store is not None:
                store.close()
            store = MongoStore(uri="", database="")
        application.state.mongo = store
        try:
            yield
        finally:
            store.close()

    application = FastAPI(
        title="ResearchPaper AI API",
        description=(
            "Local research-paper search and recommendations using the fitted Phase 2 model. "
            "Activity persistence is anonymous and is not an authentication system."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )
    origins = cors_origins if cors_origins is not None else [
        value.strip()
        for value in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if value.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Session-ID", "Authorization"],
    )

    def engine_for(request: Request) -> ResearchPaperRecommender:
        return request.app.state.engine

    def mongo_for(request: Request):
        store = request.app.state.mongo
        if not store.available:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MongoDB is unavailable; activity storage is disabled.",
            )
        return store

    def identity_for(request: Request, session_id: str | None = None) -> tuple[dict | None, str]:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            secret = os.getenv("JWT_SECRET", "410d4c5cd89ec92e2169894a1af55e33e32d262fafe718274a3be497f52ca9cc")
            payload = decode_jwt(token, secret)
            if payload and "user_id" in payload:
                return payload, str(payload["user_id"])
        return None, session_id or "local-anonymous"

    @application.post("/auth/send-otp")
    def send_otp(payload: SendOtpRequest, request: Request) -> dict:
        store = mongo_for(request)
        otp = generate_otp(6)
        ttl = int(os.getenv("OTP_TTL_MINUTES", "10"))
        store.save_otp(payload.email, otp, payload.purpose, ttl_minutes=ttl)
        sent = send_otp_email(payload.email, otp, payload.purpose)
        return {
            "message": f"Verification code sent to {payload.email}",
            "email": payload.email,
            "purpose": payload.purpose,
            "dispatched": sent,
        }

    @application.post("/auth/signup", response_model=AuthResponse)
    def signup(payload: SignupRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        verified = store.verify_and_consume_otp(payload.email, payload.otp, "signup")
        if not verified:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        existing = store.get_user_by_email(payload.email)
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email already exists.")
        pwd_hash = hash_password(payload.password)
        user = store.create_user(
            email=payload.email,
            name=payload.name,
            password_hash=pwd_hash,
            auth_provider="local",
            is_verified=True,
        )
        secret = os.getenv("JWT_SECRET", "410d4c5cd89ec92e2169894a1af55e33e32d262fafe718274a3be497f52ca9cc")
        days = int(os.getenv("JWT_EXPIRES_DAYS", "7"))
        token = create_jwt(
            {"user_id": user["user_id"], "email": user["email"], "name": user["name"]},
            secret,
            expires_in_seconds=days * 86400,
        )
        return AuthResponse(token=token, user=UserProfile(**user), message="Account created successfully.")

    @application.post("/auth/login", response_model=AuthResponse)
    def login(payload: LoginRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        user = store.get_user_by_email(payload.email)
        if not user or not verify_password(payload.password, user.get("password_hash")):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        secret = os.getenv("JWT_SECRET", "410d4c5cd89ec92e2169894a1af55e33e32d262fafe718274a3be497f52ca9cc")
        days = int(os.getenv("JWT_EXPIRES_DAYS", "7"))
        token = create_jwt(
            {"user_id": user["user_id"], "email": user["email"], "name": user["name"]},
            secret,
            expires_in_seconds=days * 86400,
        )
        clean_user = dict(user)
        clean_user.pop("password_hash", None)
        return AuthResponse(token=token, user=UserProfile(**clean_user), message="Welcome back!")

    @application.post("/auth/login-otp", response_model=AuthResponse)
    def login_with_otp(payload: LoginOtpRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        verified = store.verify_and_consume_otp(payload.email, payload.otp, "login")
        if not verified:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        user = store.get_user_by_email(payload.email)
        if not user:
            name = payload.email.split("@")[0].capitalize()
            user = store.create_user(
                email=payload.email,
                name=name,
                auth_provider="local",
                is_verified=True,
            )
        secret = os.getenv("JWT_SECRET", "410d4c5cd89ec92e2169894a1af55e33e32d262fafe718274a3be497f52ca9cc")
        days = int(os.getenv("JWT_EXPIRES_DAYS", "7"))
        token = create_jwt(
            {"user_id": user["user_id"], "email": user["email"], "name": user["name"]},
            secret,
            expires_in_seconds=days * 86400,
        )
        clean_user = dict(user)
        clean_user.pop("password_hash", None)
        return AuthResponse(token=token, user=UserProfile(**clean_user), message="Logged in with OTP.")

    @application.post("/auth/google", response_model=AuthResponse)
    def google_auth(payload: GoogleAuthRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        info = verify_google_id_token(payload.credential, expected_client_id=google_client_id)
        if not info:
            raise HTTPException(status_code=401, detail="Invalid Google OAuth credential.")
        user = store.get_user_by_email(info["email"])
        if not user:
            user = store.create_user(
                email=info["email"],
                name=info["name"],
                auth_provider="google",
                is_verified=True,
                picture=info.get("picture"),
            )
        else:
            if info.get("picture") and not user.get("picture"):
                store.update_user(user["user_id"], {"picture": info["picture"]})
                user["picture"] = info["picture"]
        secret = os.getenv("JWT_SECRET", "410d4c5cd89ec92e2169894a1af55e33e32d262fafe718274a3be497f52ca9cc")
        days = int(os.getenv("JWT_EXPIRES_DAYS", "7"))
        token = create_jwt(
            {"user_id": user["user_id"], "email": user["email"], "name": user["name"]},
            secret,
            expires_in_seconds=days * 86400,
        )
        clean_user = dict(user)
        clean_user.pop("password_hash", None)
        return AuthResponse(token=token, user=UserProfile(**clean_user), message="Logged in with Google.")

    @application.get("/auth/me", response_model=UserProfile)
    def get_current_user_profile(request: Request) -> UserProfile:
        user_payload, _ = identity_for(request)
        if not user_payload:
            raise HTTPException(status_code=401, detail="Authentication required.")
        store = request.app.state.mongo
        if store.available:
            db_user = store.get_user_by_id(user_payload["user_id"])
            if db_user:
                db_user.pop("password_hash", None)
                return UserProfile(**db_user)
        return UserProfile(
            user_id=user_payload["user_id"],
            email=user_payload["email"],
            name=user_payload.get("name", "Researcher"),
            auth_provider="jwt",
        )

    @application.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordRequest, request: Request) -> dict:
        store = mongo_for(request)
        verified = store.verify_and_consume_otp(payload.email, payload.otp, "reset_password")
        if not verified:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        user = store.get_user_by_email(payload.email)
        if not user:
            raise HTTPException(status_code=404, detail="No user found with this email.")
        new_hash = hash_password(payload.new_password)
        store.update_user(user["user_id"], {"password_hash": new_hash})
        return {"message": "Password reset successfully. You can now log in with your new password."}

    @application.get("/health")
    def health(request: Request) -> dict:
        engine = engine_for(request)
        mongo_available = bool(request.app.state.mongo.available)
        return {
            "status": "ok" if mongo_available else "degraded",
            "model_loaded": True,
            "paper_count": len(engine.papers),
            "mongodb": "available" if mongo_available else "unavailable",
        }

    @application.get("/papers/suggest", response_model=SuggestResponse)
    def suggest_queries(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=100)],
        limit: Annotated[int, Query(ge=1, le=10)] = 6,
    ) -> SuggestResponse:
        engine = engine_for(request)
        suggestions = engine.suggest(prefix=q, limit=limit)
        return SuggestResponse(query=q, suggestions=suggestions)

    @application.get("/papers/search", response_model=SearchResponse)
    def search_papers(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=512)],
        category: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        session_id: SessionId = "local-anonymous",
    ) -> SearchResponse:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="Query must contain non-whitespace text.")
        engine = engine_for(request)
        results = engine.recommend(query=query, category=category, top_k=limit)
        history_saved = False
        store = request.app.state.mongo
        _, identity_id = identity_for(request, session_id)
        if store.available:
            try:
                store.add_search(identity_id, query, len(results))
                history_saved = True
            except MongoUnavailable:
                logger.warning("Search succeeded but its history was not persisted")
        return SearchResponse(query=query, results=results, history_saved=history_saved)

    @application.get("/papers/{paper_id}", response_model=PaperDetails)
    def get_paper(
        paper_id: Annotated[str, ApiPath(min_length=1, max_length=80)], request: Request
    ) -> PaperDetails:
        engine = engine_for(request)
        index = engine.id_to_index.get(paper_id)
        if index is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        return _paper_response(engine.papers[index])

    @application.get("/papers/{paper_id}/recommendations", response_model=RecommendationResponse)
    def get_recommendations(
        paper_id: Annotated[str, ApiPath(min_length=1, max_length=80)],
        request: Request,
        category: Annotated[str | None, Query(max_length=64)] = None,
        k: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> RecommendationResponse:
        engine = engine_for(request)
        try:
            recommendations = engine.recommend(paper_id=paper_id, category=category, top_k=k)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper not found.") from exc
        return RecommendationResponse(paper_id=paper_id, recommendations=recommendations)

    @application.get("/session/recommendations", response_model=PersonalizedResponse)
    @application.get("/papers/recommendations/personalized", response_model=PersonalizedResponse)
    def get_personalized_recommendations(
        request: Request,
        category: Annotated[str | None, Query(max_length=64)] = None,
        k: Annotated[int, Query(ge=1, le=50)] = 10,
        session_id: SessionId = "local-anonymous",
    ) -> PersonalizedResponse:
        engine = engine_for(request)
        store = request.app.state.mongo
        bookmarked_ids: list[str] = []
        interest_terms: list[str] = []
        _, identity_id = identity_for(request, session_id)
        if store.available:
            try:
                bookmarks = store.list_bookmarks(identity_id, limit=50)
                bookmarked_ids = [b["paper_id"] for b in bookmarks]
                interests = store.get_interests(identity_id)
                if interests and "terms" in interests:
                    interest_terms = interests["terms"]
            except MongoUnavailable:
                logger.warning("MongoDB unavailable for personalized recommendations")

        results = engine.recommend_for_profile(
            paper_ids=bookmarked_ids,
            interest_terms=interest_terms,
            category=category,
            top_k=k,
        )
        return PersonalizedResponse(
            recommendations=results,
            based_on={
                "bookmarks_count": len(bookmarked_ids),
                "interests_count": len(interest_terms),
            },
        )

    @application.post("/session/bookmarks", response_model=BookmarkEntry, status_code=201)
    def add_bookmark(
        payload: BookmarkRequest, request: Request, session_id: SessionId = "local-anonymous"
    ) -> BookmarkEntry:
        engine = engine_for(request)
        index = engine.id_to_index.get(payload.paper_id)
        if index is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            saved = store.add_bookmark(identity_id, payload.paper_id)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return BookmarkEntry(
            paper_id=payload.paper_id,
            title=engine.papers[index].title,
            created_at=saved["created_at"],
        )

    @application.get("/session/bookmarks", response_model=BookmarkList)
    def list_bookmarks(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        session_id: SessionId = "local-anonymous",
    ) -> BookmarkList:
        engine = engine_for(request)
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            saved = store.list_bookmarks(identity_id, limit)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        items = []
        for entry in saved:
            index = engine.id_to_index.get(entry["paper_id"])
            if index is not None:
                items.append(
                    BookmarkEntry(
                        paper_id=entry["paper_id"],
                        title=engine.papers[index].title,
                        created_at=entry["created_at"],
                    )
                )
        return BookmarkList(bookmarks=items)

    @application.delete("/session/bookmarks/{paper_id}")
    def delete_bookmark(
        paper_id: Annotated[str, ApiPath(min_length=1, max_length=80)],
        request: Request,
        session_id: SessionId = "local-anonymous",
    ) -> dict:
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            deleted = store.remove_bookmark(identity_id, paper_id)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"deleted": deleted}

    @application.get("/session/search-history", response_model=SearchHistoryList)
    def list_search_history(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        session_id: SessionId = "local-anonymous",
    ) -> SearchHistoryList:
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            history = store.list_searches(identity_id, limit)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SearchHistoryList(history=history)

    @application.get("/session/interests", response_model=InterestResponse)
    def get_interests(request: Request, session_id: SessionId = "local-anonymous") -> InterestResponse:
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            saved = store.get_interests(identity_id)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(
            terms=saved["terms"] if saved else [],
            updated_at=saved.get("updated_at") if saved else None,
        )

    @application.put("/session/interests", response_model=InterestResponse)
    def set_interests(
        payload: InterestRequest, request: Request, session_id: SessionId = "local-anonymous"
    ) -> InterestResponse:
        store = mongo_for(request)
        _, identity_id = identity_for(request, session_id)
        try:
            saved = store.set_interests(identity_id, payload.terms)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(terms=saved["terms"], updated_at=saved["updated_at"])
        try:
            saved = store.set_interests(session_id, payload.terms)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(terms=saved["terms"], updated_at=saved["updated_at"])

    return application


app = create_app()
