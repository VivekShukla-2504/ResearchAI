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

load_dotenv()
logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PaperResult(BaseModel):
    paper_id: str
    title: str
    abstract: str
    terms: list[str]
    similarity: float | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[PaperResult]
    history_saved: bool


class PaperDetails(PaperResult):
    source_rows: list[int]


class RecommendationResponse(BaseModel):
    paper_id: str
    recommendations: list[PaperResult]


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
        allow_headers=["Content-Type", "X-Session-ID"],
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

    @application.get("/papers/search", response_model=SearchResponse)
    def search_papers(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=512)],
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
        session_id: SessionId = "local-anonymous",
    ) -> SearchResponse:
        query = q.strip()
        if not query:
            raise HTTPException(status_code=422, detail="Query must contain non-whitespace text.")
        engine = engine_for(request)
        results = engine.recommend(query=query, top_k=limit)
        history_saved = False
        store = request.app.state.mongo
        if store.available:
            try:
                store.add_search(session_id, query, len(results))
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
        k: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> RecommendationResponse:
        engine = engine_for(request)
        try:
            recommendations = engine.recommend(paper_id=paper_id, top_k=k)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Paper not found.") from exc
        return RecommendationResponse(paper_id=paper_id, recommendations=recommendations)

    @application.post("/session/bookmarks", response_model=BookmarkEntry, status_code=201)
    def add_bookmark(
        payload: BookmarkRequest, request: Request, session_id: SessionId = "local-anonymous"
    ) -> BookmarkEntry:
        engine = engine_for(request)
        index = engine.id_to_index.get(payload.paper_id)
        if index is None:
            raise HTTPException(status_code=404, detail="Paper not found.")
        store = mongo_for(request)
        try:
            saved = store.add_bookmark(session_id, payload.paper_id)
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
        try:
            saved = store.list_bookmarks(session_id, limit)
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
        try:
            deleted = store.remove_bookmark(session_id, paper_id)
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
        try:
            history = store.list_searches(session_id, limit)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return SearchHistoryList(history=history)

    @application.get("/session/interests", response_model=InterestResponse)
    def get_interests(request: Request, session_id: SessionId = "local-anonymous") -> InterestResponse:
        store = mongo_for(request)
        try:
            saved = store.get_interests(session_id)
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
        try:
            saved = store.set_interests(session_id, payload.terms)
        except MongoUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return InterestResponse(terms=saved["terms"], updated_at=saved["updated_at"])

    return application


app = create_app()
