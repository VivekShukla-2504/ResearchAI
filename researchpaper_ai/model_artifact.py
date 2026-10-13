"""Build and load the fitted Phase 2 engine artifact."""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from scipy import sparse

from .data import load_clean_csv
from .engine import ResearchPaperRecommender


def build_model_artifact(cleaned_path: str | Path, artifact_path: str | Path) -> Path:
    """Fit the existing recommender once and persist it for API startup loading."""
    cleaned_path = Path(cleaned_path)
    artifact_path = Path(artifact_path)
    if not cleaned_path.is_file():
        raise FileNotFoundError(f"Cleaned dataset not found: {cleaned_path}")
    papers = load_clean_csv(cleaned_path)
    engine = ResearchPaperRecommender(papers)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(engine, artifact_path, compress=3)
    return artifact_path


def load_model_artifact(artifact_path: str | Path) -> ResearchPaperRecommender:
    """Load a trusted locally-built engine artifact without fitting any model."""
    artifact_path = Path(artifact_path)
    if not artifact_path.is_file():
        raise FileNotFoundError(
            f"Fitted model artifact not found: {artifact_path}. "
            "Build it once with `python scripts/build_model_artifact.py`."
        )
    engine = joblib.load(artifact_path)
    if not isinstance(engine, ResearchPaperRecommender):
        raise TypeError(f"Unexpected model artifact type: {type(engine).__name__}")
    papers = getattr(engine, "papers", None)
    matrix = getattr(engine, "matrix", None)
    vectorizer = getattr(engine, "vectorizer", None)
    id_to_index = getattr(engine, "id_to_index", None)
    if not isinstance(papers, list) or not sparse.issparse(matrix) or vectorizer is None:
        raise ValueError("Model artifact is missing fitted papers, sparse features, or vectorizer")
    if matrix.ndim != 2 or matrix.shape[0] != len(papers):
        raise ValueError("Model artifact paper rows do not match its feature matrix")
    expected_mapping = {paper.paper_id: index for index, paper in enumerate(papers)}
    if len(expected_mapping) != len(papers) or id_to_index != expected_mapping:
        raise ValueError("Model artifact paper-ID index does not match its paper rows")
    vocabulary = getattr(vectorizer, "vocabulary_", None)
    if not isinstance(vocabulary, dict) or len(vocabulary) != matrix.shape[1]:
        raise ValueError("Model artifact vectorizer vocabulary does not match its feature matrix")
    if not np.isfinite(matrix.data).all():
        raise ValueError("Model artifact feature matrix contains non-finite values")
    return engine
