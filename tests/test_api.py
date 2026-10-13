from datetime import datetime, timezone

import joblib
from fastapi.testclient import TestClient

from researchpaper_ai.api import create_app
from researchpaper_ai.data import clean_records
from researchpaper_ai.engine import ResearchPaperRecommender
from researchpaper_ai.mongo_store import MongoUnavailable


class MemoryActivityStore:
    def __init__(self, available=True):
        self.available = available
        self.bookmarks = {}
        self.searches = []
        self.interests = {}

    def connect(self):
        return self.available

    def close(self):
        self.available = False

    def add_search(self, session_id, query, result_count):
        if not self.available:
            raise RuntimeError("unavailable")
        self.searches.append({
            "session_id": session_id,
            "query": query,
            "result_count": result_count,
            "created_at": datetime.now(timezone.utc),
        })

    def add_bookmark(self, session_id, paper_id):
        if not self.available:
            raise RuntimeError("unavailable")
        entry = self.bookmarks.setdefault(
            (session_id, paper_id),
            {"session_id": session_id, "paper_id": paper_id, "created_at": datetime.now(timezone.utc)},
        )
        return entry

    def remove_bookmark(self, session_id, paper_id):
        return self.bookmarks.pop((session_id, paper_id), None) is not None

    def list_bookmarks(self, session_id, limit):
        return [item for item in self.bookmarks.values() if item["session_id"] == session_id][:limit]

    def list_searches(self, session_id, limit):
        return [item for item in self.searches if item["session_id"] == session_id][-limit:][::-1]

    def get_interests(self, session_id):
        return self.interests.get(session_id)

    def set_interests(self, session_id, terms):
        item = {"session_id": session_id, "terms": terms, "updated_at": datetime.now(timezone.utc)}
        self.interests[session_id] = item
        return item


def build_engine():
    rows = [
        {"terms": "['cs.AI']", "titles": "Graph neural networks", "abstracts": "Neural graph models learn node representations."},
        {"terms": "['cs.AI', 'cs.LG']", "titles": "Graph attention networks", "abstracts": "Attention models process graph nodes and edges."},
        {"terms": "['cs.CV']", "titles": "Image segmentation", "abstracts": "Vision models identify image regions."},
        {"terms": "['cs.LG']", "titles": "Graph representation learning", "abstracts": "Learning useful representations from graph structures."},
    ]
    papers, _ = clean_records(rows)
    return ResearchPaperRecommender(papers, min_df=1, max_features=1000)


def client_for(engine=None, store=None, artifact_path=None):
    repository = store or MemoryActivityStore()
    app = create_app(
        model=engine,
        artifact_path=artifact_path,
        mongo_store_factory=lambda: repository,
        cors_origins=["http://localhost:5173"],
    )
    return TestClient(app), repository


def test_search_details_and_recommendations():
    engine = build_engine()
    client, store = client_for(engine=engine)
    with client:
        search = client.get("/papers/search", params={"q": "graph neural representations", "limit": 2})
        assert search.status_code == 200
        assert len(search.json()["results"]) == 2
        assert search.json()["history_saved"] is True
        assert store.searches[0]["query"] == "graph neural representations"

        paper = engine.papers[0]
        details = client.get(f"/papers/{paper.paper_id}")
        assert details.status_code == 200
        assert details.json()["paper_id"] == paper.paper_id
        assert details.json()["title"] == paper.title

        recs = client.get(f"/papers/{paper.paper_id}/recommendations", params={"k": 2})
        assert recs.status_code == 200
        result_ids = [item["paper_id"] for item in recs.json()["recommendations"]]
        assert len(result_ids) == 2
        assert paper.paper_id not in result_ids


def test_missing_paper_and_request_validation():
    client, _ = client_for(engine=build_engine())
    with client:
        assert client.get("/papers/no-such-paper").status_code == 404
        assert client.get("/papers/no-such-paper/recommendations").status_code == 404
        assert client.get("/papers/search", params={"q": "  "}).status_code == 422
        assert client.get("/papers/search", params={"q": "graph", "limit": 0}).status_code == 422
        assert client.get("/papers/search", params={"q": "graph"}, headers={"X-Session-ID": "bad id"}).status_code == 422
        assert client.get("/papers/search", params={"q": "graph" * 130}).status_code == 422
        assert client.post("/session/bookmarks", json={"paper_id": "   "}).status_code == 422
        assert client.get("/papers/search", params={"q": "graph"}, headers={"Origin": "http://localhost:5173"}).headers["access-control-allow-origin"] == "http://localhost:5173"


def test_session_bookmarks_interests_and_search_history():
    engine = build_engine()
    client, _ = client_for(engine=engine)
    paper = engine.papers[0]
    headers = {"X-Session-ID": "student-01"}
    with client:
        saved = client.post("/session/bookmarks", json={"paper_id": paper.paper_id}, headers=headers)
        assert saved.status_code == 201
        assert saved.json()["title"] == paper.title
        assert client.get("/session/bookmarks", headers=headers).json()["bookmarks"][0]["paper_id"] == paper.paper_id
        assert client.delete(f"/session/bookmarks/{paper.paper_id}", headers=headers).json() == {"deleted": True}
        assert client.get("/papers/search", params={"q": "graph"}, headers=headers).status_code == 200
        history = client.get("/session/search-history", headers=headers)
        assert history.status_code == 200
        assert history.json()["history"][0]["query"] == "graph"
        interests = client.put("/session/interests", json={"terms": [" cs.AI ", "cs.LG", "cs.AI"]}, headers=headers)
        assert interests.status_code == 200
        assert interests.json()["terms"] == ["cs.AI", "cs.LG"]
        assert client.get("/session/interests", headers=headers).json()["terms"] == ["cs.AI", "cs.LG"]
        assert client.put("/session/interests", json={"terms": ["x"] * 51}, headers=headers).status_code == 422
        assert client.put("/session/interests", json={"terms": "cs.AI"}, headers=headers).status_code == 422


def test_search_survives_mongo_failure_while_history_is_disabled():
    class FailingSearchStore(MemoryActivityStore):
        def add_search(self, session_id, query, result_count):
            self.available = False
            raise MongoUnavailable("MongoDB became unavailable")

    client, _ = client_for(engine=build_engine(), store=FailingSearchStore())
    with client:
        response = client.get("/papers/search", params={"q": "graph"})
        assert response.status_code == 200
        assert response.json()["results"]
        assert response.json()["history_saved"] is False
        assert client.get("/health").json()["mongodb"] == "unavailable"
        assert client.get("/session/search-history").status_code == 503


def test_empty_cors_allowlist_does_not_restore_default_origins():
    app = create_app(
        model=build_engine(), mongo_store_factory=MemoryActivityStore,
        cors_origins=[],
    )
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" not in response.headers


def test_mongo_startup_error_is_redacted_from_logs(caplog):
    def broken_factory():
        raise RuntimeError("private-connection-detail-marker")

    app = create_app(model=build_engine(), mongo_store_factory=broken_factory)
    with caplog.at_level("WARNING"), TestClient(app) as client:
        assert client.get("/health").json()["mongodb"] == "unavailable"
    assert "private-connection-detail-marker" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_database_unavailable_degrades_health_and_keeps_search_available():
    unavailable = MemoryActivityStore(available=False)
    client, _ = client_for(engine=build_engine(), store=unavailable)
    paper_id = build_engine().papers[0].paper_id
    with client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "degraded"
        assert health.json()["mongodb"] == "unavailable"
        search = client.get("/papers/search", params={"q": "graph"})
        assert search.status_code == 200
        assert search.json()["history_saved"] is False
        assert client.post("/session/bookmarks", json={"paper_id": paper_id}).status_code == 503
        assert client.get("/session/interests").status_code == 503


def test_startup_loads_serialized_artifact_once_without_refitting(tmp_path, monkeypatch):
    engine = build_engine()
    artifact = tmp_path / "model.joblib"
    joblib.dump(engine, artifact)
    import researchpaper_ai.api as api_module

    original_loader = api_module.load_model_artifact
    calls = []

    def counted_loader(path):
        calls.append(path)
        return original_loader(path)

    monkeypatch.setattr(api_module, "load_model_artifact", counted_loader)
    client, _ = client_for(artifact_path=artifact)
    with client:
        assert client.get("/health").json()["model_loaded"] is True
        assert client.get("/papers/search", params={"q": "graph"}).status_code == 200
        assert client.get("/health").status_code == 200
    assert calls == [artifact]
