"""FastAPI layer for the Phase 2 fitted recommendation engine."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .data import Paper
from .engine import ResearchPaperRecommender
from .model_artifact import load_model_artifact
from .mongo_store import DuplicateUserError, MongoStore, MongoUnavailable
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
JWT_SECRET_MIN_LENGTH = 32
JWT_SECRET_PLACEHOLDERS = (
    "your_secret_key_here",
    "change_me",
    "change-me",
    "changeme",
    "replace_me",
    "replace-me",
    "placeholder",
)


def _configured_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if (
        not secret
        or len(secret) < JWT_SECRET_MIN_LENGTH
        or secret != secret.strip()
        or any(placeholder in secret.casefold() for placeholder in JWT_SECRET_PLACEHOLDERS)
    ):
        raise RuntimeError(
            "JWT_SECRET must be configured with a unique random value of at least 32 characters."
        )
    return secret


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
    jwt_secret: str | None = None,
) -> FastAPI:
    configured_jwt_secret = jwt_secret if jwt_secret is not None else _configured_jwt_secret()
    artifact = _resolve_path(
        artifact_path or os.getenv("MODEL_ARTIFACT_PATH", "artifacts/recommender.joblib")
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.jwt_secret = configured_jwt_secret
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
            "Authenticated research-paper search and recommendations using the fitted Phase 2 model. "
            "Account activity is scoped to the signed-in user."
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

    def identity_for(request: Request) -> tuple[dict, str]:
        auth_header = request.headers.get("Authorization")
        token = auth_header[7:].strip() if auth_header and auth_header.startswith("Bearer ") else ""
        payload = decode_jwt(token, request.app.state.jwt_secret) if token else None
        if not payload or not payload.get("user_id"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = str(payload["user_id"])
        store = request.app.state.mongo
        if store.available:
            database_unavailable = False
            try:
                user = store.get_user_by_id(user_id)
            except MongoUnavailable:
                user = None
                database_unavailable = True
            if user is None and not database_unavailable:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token.")
            if user is not None:
                try:
                    token_version = int(payload.get("token_version", 0) or 0)
                    current_version = int(user.get("token_version", 0) or 0)
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.") from exc
                if token_version != current_version:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token.")
        return payload, user_id

    def issue_token(request: Request, user: dict) -> str:
        days = int(os.getenv("JWT_EXPIRES_DAYS", "7"))
        return create_jwt(
            {
                "user_id": user["user_id"],
                "email": user["email"],
                "name": user["name"],
                "token_version": user.get("token_version", 0),
            },
            request.app.state.jwt_secret,
            expires_in_seconds=days * 86400,
        )

    @application.post("/auth/send-otp")
    def send_otp(payload: SendOtpRequest, request: Request) -> dict:
        store = mongo_for(request)
        clean_email = payload.email.strip().lower()
        if payload.purpose == "signup":
            existing = store.get_user_by_email(clean_email)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="An account with this email already exists. Please sign in instead.",
                )
        elif payload.purpose == "reset_password":
            existing = store.get_user_by_email(clean_email)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No account found with this email. Please check your email or create an account.",
                )
        otp = generate_otp(6)
        ttl = int(os.getenv("OTP_TTL_MINUTES", "10"))
        store.save_otp(clean_email, otp, payload.purpose, ttl_minutes=ttl)
        sent = send_otp_email(clean_email, otp, payload.purpose)
        return {
            "message": f"Verification code sent to {clean_email}",
            "email": clean_email,
            "purpose": payload.purpose,
            "dispatched": sent,
        }

    @application.post("/auth/signup", response_model=AuthResponse)
    def signup(payload: SignupRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        clean_email = payload.email.strip().lower()
        existing = store.get_user_by_email(clean_email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please sign in instead.",
            )
        verified = store.verify_and_consume_otp(clean_email, payload.otp, "signup")
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code.",
            )
        pwd_hash = hash_password(payload.password)
        try:
            user = store.create_user(
                email=clean_email,
                name=payload.name,
                password_hash=pwd_hash,
                auth_provider="local",
                is_verified=True,
            )
        except DuplicateUserError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please sign in instead.",
            ) from exc
        token = issue_token(request, user)
        return AuthResponse(token=token, user=UserProfile(**user), message="Account created successfully.")

    @application.post("/auth/login", response_model=AuthResponse)
    def login(payload: LoginRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        clean_email = payload.email.strip().lower()
        user = store.get_user_by_email(clean_email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not user.get("password_hash") and user.get("auth_provider") == "google":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This account was created with Google. Please use Google Sign-In or reset your password.",
            )
        if not verify_password(payload.password, user.get("password_hash")):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        token = issue_token(request, user)
        clean_user = dict(user)
        clean_user.pop("password_hash", None)
        return AuthResponse(token=token, user=UserProfile(**clean_user), message="Welcome back!")

    @application.post("/auth/login-otp", response_model=AuthResponse)
    def login_with_otp(payload: LoginOtpRequest, request: Request) -> AuthResponse:
        store = mongo_for(request)
        clean_email = payload.email.strip().lower()
        verified = store.verify_and_consume_otp(clean_email, payload.otp, "login")
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code.",
            )
        user = store.get_user_by_email(clean_email)
        if not user:
            name = clean_email.split("@")[0].capitalize()
            try:
                user = store.create_user(
                    email=clean_email,
                    name=name,
                    auth_provider="local",
                    is_verified=True,
                )
            except DuplicateUserError:
                user = store.get_user_by_email(clean_email)
        token = issue_token(request, user)
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
        token = issue_token(request, user)
        clean_user = dict(user)
        clean_user.pop("password_hash", None)
        return AuthResponse(token=token, user=UserProfile(**clean_user), message="Logged in with Google.")

    @application.get("/auth/me", response_model=UserProfile)
    def get_current_user_profile(request: Request) -> UserProfile:
        user_payload, _ = identity_for(request)
        store = request.app.state.mongo
        if store.available:
            try:
                db_user = store.get_user_by_id(user_payload["user_id"])
            except MongoUnavailable:
                db_user = None
            if db_user:
                db_user.pop("password_hash", None)
                return UserProfile(**db_user)
        return UserProfile(
            user_id=user_payload["user_id"],
            email=user_payload["email"],
            name=user_payload.get("name", "Researcher"),
            auth_provider="jwt",
        )

    @application.post("/auth/logout")
    def logout(request: Request) -> dict:
        _, user_id = identity_for(request)
        store = mongo_for(request)
        try:
            if not store.revoke_user_tokens(user_id):
                raise HTTPException(status_code=401, detail="Invalid or revoked token.")
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"message": "Signed out successfully."}

    @application.post("/auth/reset-password")
    def reset_password(payload: ResetPasswordRequest, request: Request) -> dict:
        store = mongo_for(request)
        clean_email = payload.email.strip().lower()
        user = store.get_user_by_email(clean_email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email. Please check your email or create an account.",
            )
        verified = store.verify_and_consume_otp(clean_email, payload.otp, "reset_password")
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification code.",
            )
        new_hash = hash_password(payload.new_password)
        if not store.update_password_and_revoke_tokens(user["user_id"], new_hash):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email.",
            )
        return {"message": "Password reset successfully. You can now log in with your new password."}

    @application.api_route("/", methods=["GET", "HEAD"])
    def root() -> dict:
        return {
            "name": "ResearchPaper AI API",
            "version": "0.3.0",
            "status": "online",
            "health_check": "/health",
            "docs": "/docs",
        }

    @application.api_route("/health", methods=["GET", "HEAD"])
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
        identity_for(request)
        engine = engine_for(request)
        suggestions = engine.suggest(prefix=q, limit=limit)
        return SuggestResponse(query=q, suggestions=suggestions)

    @application.get("/papers/search", response_model=SearchResponse)
    def search_papers(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=512)],
        category: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> SearchResponse:
        _, identity_id = identity_for(request)
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="Query must contain non-whitespace text.")
        engine = engine_for(request)
        results = engine.recommend(query=query, category=category, top_k=limit)
        history_saved = False
        store = request.app.state.mongo
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
        identity_for(request)
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
        identity_for(request)
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
    ) -> PersonalizedResponse:
        _, identity_id = identity_for(request)
        engine = engine_for(request)
        store = request.app.state.mongo
        bookmarked_ids: list[str] = []
        interest_terms: list[str] = []
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
    def add_bookmark(payload: BookmarkRequest, request: Request) -> BookmarkEntry:
        _, identity_id = identity_for(request)
        engine = engine_for(request)
        index = engine.id_to_index.get(payload.paper_id)
        if index is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        store = mongo_for(request)
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
    ) -> BookmarkList:
        _, identity_id = identity_for(request)
        engine = engine_for(request)
        store = mongo_for(request)
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
    ) -> dict:
        _, identity_id = identity_for(request)
        store = mongo_for(request)
        try:
            deleted = store.remove_bookmark(identity_id, paper_id)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"deleted": deleted}

    @application.get("/session/search-history", response_model=SearchHistoryList)
    def list_search_history(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> SearchHistoryList:
        _, identity_id = identity_for(request)
        store = mongo_for(request)
        try:
            history = store.list_searches(identity_id, limit)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SearchHistoryList(history=history)

    @application.get("/session/interests", response_model=InterestResponse)
    def get_interests(request: Request) -> InterestResponse:
        _, identity_id = identity_for(request)
        store = mongo_for(request)
        try:
            saved = store.get_interests(identity_id)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(
            terms=saved["terms"] if saved else [],
            updated_at=saved.get("updated_at") if saved else None,
        )

    @application.put("/session/interests", response_model=InterestResponse)
    def set_interests(payload: InterestRequest, request: Request) -> InterestResponse:
        _, identity_id = identity_for(request)
        store = mongo_for(request)
        try:
            saved = store.set_interests(identity_id, payload.terms)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(terms=saved["terms"], updated_at=saved["updated_at"])

    return application


app = create_app()
