"""Reproducible category-overlap proxy and clustering evaluation."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys

import numpy as np
from sklearn.metrics import silhouette_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from researchpaper_ai.data import load_clean_csv, read_source, write_clean_csv
from researchpaper_ai.engine import ResearchPaperRecommender


def _diversity(engine: ResearchPaperRecommender, result: list[dict]) -> float:
    if len(result) < 2:
        return 0.0
    indices = [engine.id_to_index[item["paper_id"]] for item in result]
    similarities = (engine.matrix[indices] @ engine.matrix[indices].T).toarray()
    upper = similarities[np.triu_indices(len(indices), k=1)]
    return float(1.0 - upper.mean())


def evaluate(
    engine: ResearchPaperRecommender,
    *,
    query_count: int = 500,
    top_k: int = 10,
    random_state: int = 42,
) -> dict:
    rng = np.random.default_rng(random_state)
    sample_size = min(query_count, len(engine.papers))
    query_indices = np.sort(rng.choice(len(engine.papers), size=sample_size, replace=False))
    inverted: dict[str, set[int]] = defaultdict(set)
    for index, paper in enumerate(engine.papers):
        for term in paper.terms:
            inverted[term].add(index)

    totals = {
        variant: {"precision": 0.0, "recall": 0.0, "diversity": 0.0}
        for variant in ("baseline", "cluster_aware")
    }
    eligible = 0
    queried = 0
    for query_index in query_indices:
        query = engine.papers[int(query_index)]
        relevant: set[int] = set()
        for term in query.terms:
            relevant.update(inverted[term])
        relevant.discard(int(query_index))
        if not relevant:
            continue
        eligible += 1
        for variant, cluster_aware in (("baseline", False), ("cluster_aware", True)):
            results = engine.recommend(
                paper_id=query.paper_id,
                top_k=top_k,
                cluster_aware=cluster_aware,
                candidate_pool=100,
                diversity_penalty=0.15,
            )
            rec_indices = {engine.id_to_index[item["paper_id"]] for item in results}
            hits = len(rec_indices & relevant)
            totals[variant]["precision"] += hits / max(len(results), 1)
            totals[variant]["recall"] += hits / len(relevant)
            totals[variant]["diversity"] += _diversity(engine, results)
        queried += 1

    denominator = max(queried, 1)
    metrics = {
        name: {key: round(value / denominator, 6) for key, value in values.items()}
        for name, values in totals.items()
    }
    return {
        "queries_sampled": int(sample_size),
        "queries_with_category_relevant_candidates": eligible,
        "queries_evaluated": queried,
        "k": top_k,
        "category_overlap_proxy": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/arxiv_data_210930-054931.csv")
    parser.add_argument("--cleaned", default="data/processed/papers_clean.csv")
    parser.add_argument("--report", default="reports/phase2_evaluation.json")
    parser.add_argument("--queries", type=int, default=500)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--clusters", type=int, default=30)
    args = parser.parse_args()

    cleaned_path = Path(args.cleaned)
    if cleaned_path.exists():
        papers = load_clean_csv(cleaned_path)
        _, cleaning_stats = read_source(args.source)
    else:
        papers, cleaning_stats = read_source(args.source)
        write_clean_csv(papers, cleaned_path)
    engine = ResearchPaperRecommender(papers, random_state=42)
    engine.fit_clusters(n_clusters=args.clusters, batch_size=1024, max_iter=100, n_init=3)
    silhouette = silhouette_score(
        engine.matrix,
        engine.cluster_labels,
        metric="cosine",
        sample_size=min(2000, len(papers)),
        random_state=42,
    )
    cluster_report = engine.cluster_report(top_terms=10)
    metrics = evaluate(engine, query_count=args.queries, top_k=args.k, random_state=42)
    report = {
        "dataset": str(args.source),
        "cleaned_dataset": str(cleaned_path),
        "cleaning": cleaning_stats,
        "vectorizer": {
            "type": "TfidfVectorizer",
            "stop_words": "english",
            "ngram_range": [1, 2],
            "min_df": 2,
            "max_features": 150000,
            "sublinear_tf": True,
            "dtype": "float32",
            "title_weighting": "title repeated twice; abstract once",
            "matrix_shape": list(engine.matrix.shape),
            "matrix_nnz": int(engine.matrix.nnz),
            "matrix_sparse": bool(hasattr(engine.matrix, "tocsr")),
        },
        "kmeans": {
            "implementation": "MiniBatchKMeans",
            "n_clusters": args.clusters,
            "batch_size": 1024,
            "max_iter": 100,
            "n_init": 3,
            "random_state": 42,
            "silhouette_cosine_sample": min(2000, len(papers)),
            "silhouette_cosine": round(float(silhouette), 6),
            "clusters": cluster_report,
        },
        "recommendation_evaluation": metrics,
        "limitations": [
            "Category overlap is only a proxy for relevance; shared broad tags do not establish that a reader finds a paper useful.",
            "The fixed random sample is a reproducible offline evaluation, not a user study or a temporal holdout.",
            "Cluster-aware recommendations are a diversification reranking experiment; a metric change does not prove user benefit.",
            "Silhouette is measured on a representative random sample because full cosine silhouette is quadratic.",
        ],
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "cleaning": cleaning_stats,
        "matrix": report["vectorizer"],
        "kmeans": {key: value for key, value in report["kmeans"].items() if key != "clusters"},
        "recommendation_evaluation": metrics,
        "cluster_report": str(report_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
