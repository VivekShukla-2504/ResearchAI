"""Sparse TF-IDF paper recommendations with optional MiniBatchKMeans groups."""

from __future__ import annotations

from typing import Iterable

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from .data import Paper, read_source


class ResearchPaperRecommender:
    """Fit once, then retrieve top-k similar papers by ID or free-text query."""

    def __init__(
        self,
        papers: Iterable[Paper],
        *,
        max_features: int = 150_000,
        min_df: int | float = 2,
        ngram_range: tuple[int, int] = (1, 2),
        random_state: int = 42,
    ) -> None:
        self.papers = list(papers)
        if not self.papers:
            raise ValueError("At least one usable paper is required")
        self.random_state = random_state
        self.id_to_index = {paper.paper_id: i for i, paper in enumerate(self.papers)}
        if len(self.id_to_index) != len(self.papers):
            raise ValueError("Paper IDs must be unique")
        self.vectorizer = self._new_vectorizer(min_df, max_features, ngram_range)
        try:
            self.matrix = normalize(
                self.vectorizer.fit_transform(paper.text for paper in self.papers), norm="l2"
            )
        except ValueError as exc:
            message = str(exc).casefold()
            has_no_vocabulary = "empty vocabulary" in message or "no terms remain" in message
            min_df_exceeds_corpus = (
                "max_df corresponds to < documents than min_df" in message
                and isinstance(min_df, int)
                and min_df > len(self.papers)
            )
            if not has_no_vocabulary and not min_df_exceeds_corpus:
                raise
            # `min_df=2` is sensible for the full corpus but removes every term
            # from tiny catalogs. Retry once with one-document support; the
            # resulting feature space is still bounded by max_features.
            if min_df != 1:
                self.vectorizer = self._new_vectorizer(1, max_features, ngram_range)
                try:
                    self.matrix = normalize(
                        self.vectorizer.fit_transform(paper.text for paper in self.papers), norm="l2"
                    )
                except ValueError as retry_error:
                    if "empty vocabulary" not in str(retry_error).casefold():
                        raise
                    raise ValueError(
                        "No usable text features found; papers need at least one non-stopword token."
                    ) from retry_error
            else:
                raise ValueError(
                    "No usable text features found; papers need at least one non-stopword token."
                ) from exc
        self.cluster_model: MiniBatchKMeans | None = None
        self.cluster_labels: np.ndarray | None = None

    @staticmethod
    def _new_vectorizer(min_df, max_features, ngram_range) -> TfidfVectorizer:
        return TfidfVectorizer(
            stop_words="english",
            ngram_range=ngram_range,
            min_df=min_df,
            max_features=max_features,
            sublinear_tf=True,
            dtype=np.float32,
        )

    @classmethod
    def from_source(cls, path: str, **kwargs) -> "ResearchPaperRecommender":
        papers, _ = read_source(path)
        return cls(papers, **kwargs)

    def recommend(
        self,
        *,
        paper_id: str | None = None,
        query: str | None = None,
        top_k: int = 10,
        cluster_aware: bool = False,
        candidate_pool: int = 100,
        diversity_penalty: float = 0.15,
    ) -> list[dict]:
        if top_k < 1:
            return []
        if (paper_id is None) == (query is None):
            raise ValueError("Provide exactly one of paper_id or query")

        excluded_index: int | None = None
        if paper_id is not None:
            if paper_id not in self.id_to_index:
                raise KeyError(f"Unknown paper ID: {paper_id}")
            excluded_index = self.id_to_index[paper_id]
            query_vector = self.matrix[excluded_index]
            if query_vector.nnz == 0:
                return []
        else:
            cleaned_query = " ".join((query or "").split())
            if not cleaned_query:
                return []
            query_vector = self.vectorizer.transform([cleaned_query])
            if query_vector.nnz == 0:
                return []

        available = len(self.papers) - (excluded_index is not None)
        if available <= 0:
            return []

        # A single query produces one dense score vector, never an all-pairs matrix.
        scores = np.asarray(
            cosine_similarity(query_vector, self.matrix, dense_output=True), dtype=np.float32
        ).ravel()
        if excluded_index is not None:
            scores[excluded_index] = -np.inf
        # An incompatible/corrupt in-memory artifact must not emit NaN/Inf
        # scores. Valid TF-IDF vectors are finite and nonnegative by design.
        valid_indices = np.flatnonzero(np.isfinite(scores))
        if valid_indices.size == 0:
            return []
        scores[valid_indices] = np.clip(scores[valid_indices], 0.0, 1.0)
        count = min(max(top_k, candidate_pool if cluster_aware else top_k), valid_indices.size)
        # A stable score/index tie-break makes results repeatable, including at
        # the top-k boundary where argpartition could select arbitrary ties.
        order = np.lexsort((valid_indices, -scores[valid_indices]))
        candidate_indices = valid_indices[order[:count]]

        if cluster_aware:
            if self.cluster_labels is None:
                raise RuntimeError("Fit clusters before requesting cluster-aware recommendations")
            selected: list[int] = []
            remaining = list(candidate_indices)
            while remaining and len(selected) < top_k:
                best_position = 0
                best_value = -float("inf")
                for position, index in enumerate(remaining):
                    same_cluster = sum(
                        self.cluster_labels[index] == self.cluster_labels[chosen]
                        for chosen in selected
                    )
                    value = float(scores[index]) - diversity_penalty * same_cluster
                    if value > best_value:
                        best_value, best_position = value, position
                selected.append(int(remaining.pop(best_position)))
            candidate_indices = np.asarray(selected, dtype=int)
        else:
            candidate_indices = candidate_indices[:top_k]

        return [
            {
                "paper_id": self.papers[int(index)].paper_id,
                "title": self.papers[int(index)].title,
                "abstract": self.papers[int(index)].abstract,
                "terms": list(self.papers[int(index)].terms),
                "similarity": float(scores[int(index)]),
            }
            for index in candidate_indices
        ]

    def fit_clusters(
        self,
        *,
        n_clusters: int = 30,
        batch_size: int = 1024,
        max_iter: int = 100,
        n_init: int = 3,
    ) -> np.ndarray:
        if n_clusters < 2 or n_clusters >= len(self.papers):
            raise ValueError("n_clusters must be between 2 and number of papers - 1")
        self.cluster_model = MiniBatchKMeans(
            n_clusters=n_clusters,
            batch_size=batch_size,
            max_iter=max_iter,
            n_init=n_init,
            random_state=self.random_state,
            reassignment_ratio=0.01,
            init_size=min(max(3 * batch_size, n_clusters), len(self.papers)),
        )
        self.cluster_labels = self.cluster_model.fit_predict(self.matrix)
        return self.cluster_labels

    def cluster_report(self, *, top_terms: int = 10) -> list[dict]:
        if self.cluster_model is None or self.cluster_labels is None:
            raise RuntimeError("Fit clusters before requesting a cluster report")
        features = self.vectorizer.get_feature_names_out()
        centers = self.cluster_model.cluster_centers_
        report = []
        for cluster_id in range(self.cluster_model.n_clusters):
            member_indices = np.flatnonzero(self.cluster_labels == cluster_id)
            center = centers[cluster_id]
            term_indices = np.argsort(center)[-top_terms:][::-1]
            representative_index = None
            if len(member_indices):
                similarities = self.matrix[member_indices] @ center
                representative_index = int(member_indices[int(np.asarray(similarities).ravel().argmax())])
            representative = self.papers[representative_index] if representative_index is not None else None
            report.append(
                {
                    "cluster": cluster_id,
                    "size": int(len(member_indices)),
                    "top_terms": [str(features[i]) for i in term_indices if center[i] > 0],
                    "representative_title": representative.title if representative else None,
                    "representative_terms": list(representative.terms) if representative else [],
                }
            )
        return report
