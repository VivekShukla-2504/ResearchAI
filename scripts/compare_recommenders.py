"""Compare lightweight retrieval candidates with a reproducible weak-label holdout.

The catalog is the retrieval corpus (all papers are searchable); only query
paper IDs are split into validation and test groups. Category overlap is a
weak relevance proxy, not ground truth or model accuracy.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import gc
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.preprocessing import normalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from researchpaper_ai.data import load_clean_csv
from researchpaper_ai.model_artifact import load_model_artifact


def _peak_working_set_bytes() -> int | None:
    """Read this process's high-water RSS on Windows without an extra package."""
    if sys.platform != "win32":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("PagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("NonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("Psapi.dll")
    kernel32 = ctypes.WinDLL("Kernel32.dll")
    ok = psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return int(counters.PeakWorkingSetSize) if ok else None


def _top(scores: np.ndarray, source: int, k: int) -> list[int]:
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    scores[source] = -np.inf
    take = min(k, len(scores) - 1)
    if take <= 0:
        return []
    indices = np.argpartition(scores, -take)[-take:]
    return indices[np.argsort(scores[indices])[::-1]].tolist()


def _labels(papers, query_indices: np.ndarray) -> tuple[dict[str, np.ndarray], dict[int, np.ndarray]]:
    inverse_lists: dict[str, list[int]] = defaultdict(list)
    for i, paper in enumerate(papers):
        for term in paper.terms:
            inverse_lists[term].append(i)
    inverse = {term: np.asarray(indices, dtype=np.int32) for term, indices in inverse_lists.items()}
    # Only query rows need relevance masks. A bool vector is 1 byte per catalog
    # record; constructing Python peer sets for every paper scales quadratically.
    relevant: dict[int, np.ndarray] = {}
    for raw_index in query_indices:
        index = int(raw_index)
        mask = np.zeros(len(papers), dtype=np.bool_)
        for term in papers[index].terms:
            mask[inverse[term]] = True
        mask[index] = False
        relevant[index] = mask
    return inverse, relevant


def _metrics(rankings: list[list[int]], indices: np.ndarray, relevant: list[set[int]],
             catalog_size: int, baseline_matrix) -> dict:
    p5, p10, r5, r10, ndcg10, mrr, diversity = [], [], [], [], [], [], []
    used: set[int] = set()
    for source, ranking in zip(indices, rankings):
        truth = relevant[int(source)]
        rel = truth[np.asarray(ranking, dtype=np.int32)].astype(np.float32, copy=False)
        p5.append(float(rel[:5].sum() / 5))
        p10.append(float(rel[:10].sum() / 10))
        r5.append(float(rel[:5].sum() / max(len(truth), 1)))
        r10.append(float(rel[:10].sum() / max(len(truth), 1)))
        discounts = 1 / np.log2(np.arange(2, len(rel) + 2))
        dcg = float((rel * discounts).sum())
        ideal_count = min(int(truth.sum()), len(rel))
        ideal = float((1 / np.log2(np.arange(2, ideal_count + 2))).sum())
        ndcg10.append(dcg / ideal if ideal else 0.0)
        found = np.flatnonzero(rel)
        mrr.append(1 / (int(found[0]) + 1) if len(found) else 0.0)
        used.update(ranking)
        if len(ranking) > 1:
            rows = baseline_matrix[ranking]
            sims = (rows @ rows.T).toarray()
            diversity.append(float(1 - sims[np.triu_indices(len(ranking), 1)].mean()))
        else:
            diversity.append(0.0)
    def avg(values):
        return round(float(np.mean(values)), 6) if values else 0.0
    return {
        "precision_at_5": avg(p5), "precision_at_10": avg(p10),
        "recall_at_5": avg(r5), "recall_at_10": avg(r10),
        "ndcg_at_10": avg(ndcg10), "mrr": avg(mrr),
        "catalog_coverage": round(len(used) / max(catalog_size, 1), 6),
        "diversity": avg(diversity),
    }


def _rrf(first: list[int], second: list[int], source: int, k: int, rrf_k: int = 60) -> list[int]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in (first, second):
        for rank, item in enumerate(ranking, start=1):
            if item != source:
                scores[item] += 1 / (rrf_k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:k]]


def main() -> None:
    evaluation_started = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleaned", default="data/processed/papers_clean.csv")
    parser.add_argument("--artifact", default="artifacts/recommender.joblib")
    parser.add_argument("--report", default="reports/ml_improvement_comparison.json")
    parser.add_argument("--queries", type=int, default=600,
                        help="Even count; first half validation, second half test")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if args.queries < 20 or args.queries % 2:
        parser.error("--queries must be even and at least 20")

    papers = load_clean_csv(args.cleaned)
    baseline = load_model_artifact(args.artifact)
    if [p.paper_id for p in papers] != [p.paper_id for p in baseline.papers]:
        raise ValueError("Cleaned corpus does not match the preserved baseline artifact")
    rng = np.random.default_rng(args.seed)
    selected = rng.choice(len(papers), size=min(args.queries, len(papers)), replace=False)
    split = len(selected) // 2
    validation, test = selected[:split], selected[split:]
    _, relevant = _labels(papers, selected)
    output: dict = {
        "dataset": args.cleaned, "baseline_artifact": args.artifact,
        "catalog_size": len(papers), "seed": args.seed,
        "query_split": {"validation": len(validation), "test": len(test),
                        "disjoint": not bool(set(validation) & set(test))},
        "relevance": "binary overlap of source-paper terms; weak proxy, not human relevance",
        "diversity_reference": "mean pairwise cosine distance in preserved baseline TF-IDF space",
        "candidates": {},
    }

    baseline_rankings: dict[int, list[int]] = {}
    baseline_latencies = []
    for source in selected:
        started = time.perf_counter()
        baseline_rankings[int(source)] = [
            baseline.id_to_index[result["paper_id"]]
            for result in baseline.recommend(paper_id=papers[int(source)].paper_id, top_k=100)
        ]
        baseline_latencies.append((time.perf_counter() - started) * 1000)
    for name, group in (("validation", validation), ("test", test)):
        rows = [baseline_rankings[int(i)][:10] for i in group]
        output["candidates"].setdefault("tfidf_baseline", {})[name] = _metrics(
            rows, group, relevant, len(papers), baseline.matrix)
    output["candidates"]["tfidf_baseline"]["runtime"] = {
        "artifact_bytes": Path(args.artifact).stat().st_size,
        "matrix_bytes": int(baseline.matrix.data.nbytes + baseline.matrix.indices.nbytes + baseline.matrix.indptr.nbytes),
        "latency_ms_mean": round(float(np.mean(baseline_latencies)), 3),
        "latency_ms_p95": round(float(np.percentile(baseline_latencies, 95)), 3),
        "dense_score_vector_bytes": int(len(papers) * 4),
    }

    # Word unigram ablation against the original unigram+bigram configuration.
    unigram_vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 1), min_df=2,
                                         max_features=150_000, sublinear_tf=True, dtype=np.float32)
    unigram = unigram_vectorizer.fit_transform(paper.text for paper in papers)
    unigram_rankings, unigram_latency = [], []
    for source in selected:
        started = time.perf_counter()
        scores = (unigram.getrow(int(source)) @ unigram.T).toarray().ravel()
        unigram_rankings.append(_top(scores, int(source), 10))
        unigram_latency.append((time.perf_counter() - started) * 1000)
    output["candidates"]["tfidf_word_unigram"] = {
        "validation": _metrics(unigram_rankings[:split], validation, relevant, len(papers), baseline.matrix),
        "test": _metrics(unigram_rankings[split:], test, relevant, len(papers), baseline.matrix),
        "runtime": {"latency_ms_mean": round(float(np.mean(unigram_latency[split:])), 3),
                    "latency_ms_p95": round(float(np.percentile(unigram_latency[split:], 95)), 3),
                    "matrix_bytes": int(unigram.data.nbytes + unigram.indices.nbytes + unigram.indptr.nbytes),
                    "dense_score_vector_bytes": int(len(papers) * 4)},
    }
    del unigram_vectorizer, unigram, unigram_rankings
    gc.collect()

    # Candidate 1: compare word unigrams against word unigrams+bigrams; title
    # and abstract remain separate so weights are interpretable and tunable.
    title_vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2,
                                max_features=80_000, sublinear_tf=True, dtype=np.float32)
    abstract_vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2,
                                   max_features=120_000, sublinear_tf=True, dtype=np.float32)
    char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                               max_features=60_000, sublinear_tf=True, dtype=np.float32)
    title_matrix = title_vec.fit_transform(p.title for p in papers)
    abstract_matrix = abstract_vec.fit_transform(p.abstract for p in papers)
    char_matrix = char_vec.fit_transform(p.title for p in papers)
    for matrix in (title_matrix, abstract_matrix, char_matrix):
        normalize(matrix, norm="l2", copy=False)
    del title_vec, abstract_vec, char_vec

    # Tune only on validation: title weight and character channel contribution.
    configs = [(title_weight, char_weight) for title_weight in (0.25, 0.4, 0.55, 0.7)
               for char_weight in (0.0, 0.1, 0.2)]
    validation_rankings = {config: [] for config in configs}
    validation_latency: list[float] = []
    for source in validation:
        start = time.perf_counter()
        t = (title_matrix.getrow(int(source)) @ title_matrix.T).toarray().ravel()
        a = (abstract_matrix.getrow(int(source)) @ abstract_matrix.T).toarray().ravel()
        c = (char_matrix.getrow(int(source)) @ char_matrix.T).toarray().ravel()
        validation_latency.append((time.perf_counter() - start) * 1000)
        for title_weight, char_weight in configs:
            abstract_weight = 1.0 - title_weight - char_weight
            scores = title_weight * t + abstract_weight * a + char_weight * c
            validation_rankings[(title_weight, char_weight)].append(_top(scores, int(source), 100))
    # Store and select based on nDCG@10; ties resolve toward lower char weight,
    # then title weight closer to the existing 2:1 title:abstract mix.
    scored_configs = []
    for config in configs:
        metrics = _metrics(validation_rankings[config], validation, relevant, len(papers), baseline.matrix)
        scored_configs.append((metrics["ndcg_at_10"], -config[1], -abs(config[0] - 2/3), config, metrics))
    best = max(scored_configs)
    selected_config = best[3]
    output["tuning"] = {
        "split": "validation queries only; no test-set selection",
        "objective": "nDCG@10 under category-overlap proxy",
        "configs": {f"title={tw:.2f},char={cw:.2f},abstract={1-tw-cw:.2f}": metrics
                    for _, _, _, (tw, cw), metrics in scored_configs},
        "selected": {"title_weight": selected_config[0], "char_weight": selected_config[1],
                     "abstract_weight": 1-selected_config[0]-selected_config[1]},
    }

    test_rankings = []
    test_latency = []
    tw, cw = selected_config
    aw = 1 - tw - cw
    for source in test:
        start = time.perf_counter()
        t = (title_matrix.getrow(int(source)) @ title_matrix.T).toarray().ravel()
        a = (abstract_matrix.getrow(int(source)) @ abstract_matrix.T).toarray().ravel()
        c = (char_matrix.getrow(int(source)) @ char_matrix.T).toarray().ravel()
        scores = tw*t + aw*a + cw*c
        test_rankings.append(_top(scores, int(source), 100))
        test_latency.append((time.perf_counter() - start) * 1000)
    matrices_bytes = sum(m.data.nbytes + m.indices.nbytes + m.indptr.nbytes
                         for m in (title_matrix, abstract_matrix, char_matrix))
    output["candidates"]["field_tfidf_char"] = {
        "validation": best[4],
        "test": _metrics([r[:10] for r in test_rankings], test, relevant, len(papers), baseline.matrix),
        "runtime": {"latency_ms_mean": round(float(np.mean(test_latency)), 3),
                    "latency_ms_p95": round(float(np.percentile(test_latency, 95)), 3),
                    "matrix_bytes": int(matrices_bytes),
                    "dense_score_vectors_bytes": int(3 * len(papers) * 4)},
    }
    del title_matrix, abstract_matrix, char_matrix

    # Candidate 2: a compact in-project BM25 implementation over sparse counts;
    # avoids adding a dependency and supports the same normalized query tokens.
    bm25_vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=2,
                                      max_features=150_000, dtype=np.float32)
    counts = bm25_vectorizer.fit_transform(paper.text for paper in papers).tocsr()
    lengths = np.asarray(counts.sum(axis=1)).ravel()
    avg_length = float(lengths.mean())
    df = np.asarray((counts > 0).sum(axis=0)).ravel()
    idf = np.log1p((len(papers) - df + 0.5) / (df + 0.5)).astype(np.float32)
    row_ids = np.repeat(np.arange(counts.shape[0]), np.diff(counts.indptr))
    k1, b = 1.5, 0.75
    norm_len = k1 * (1 - b + b * lengths / max(avg_length, 1e-9))
    bm25 = counts.copy()
    bm25.data = ((bm25.data * (k1 + 1)) /
                 (bm25.data + norm_len[row_ids])) * idf[bm25.indices]
    bm25 = bm25.tocsr()

    def bm25_scores(source: int) -> np.ndarray:
        query_counts = counts.getrow(source)
        return np.asarray((bm25 @ query_counts.T).toarray()).ravel()

    bm25_val, bm25_test, bm25_val_time, bm25_test_time = [], [], [], []
    for group, target, times in ((validation, bm25_val, bm25_val_time), (test, bm25_test, bm25_test_time)):
        for source in group:
            start = time.perf_counter()
            target.append(_top(bm25_scores(int(source)), int(source), 100))
            times.append((time.perf_counter() - start) * 1000)
    output["candidates"]["bm25"] = {
        "validation": _metrics(bm25_val, validation, relevant, len(papers), baseline.matrix),
        "test": _metrics([r[:10] for r in bm25_test], test, relevant, len(papers), baseline.matrix),
        "runtime": {"k1": k1, "b": b, "latency_ms_mean": round(float(np.mean(bm25_test_time)), 3),
                    "latency_ms_p95": round(float(np.percentile(bm25_test_time), 95), 3),
                    "matrix_bytes": int(bm25.data.nbytes + bm25.indices.nbytes + bm25.indptr.nbytes),
                    "dense_score_vector_bytes": int(len(papers) * 4),
                    "dependency": "none; CountVectorizer plus sparse BM25 weighting"},
    }

    # Candidate 3: rank-level fusion of current TF-IDF and BM25. RRF scores are
    # ranking scores; the API must not present them as probabilities/accuracy.
    rrf_val = [_rrf(baseline_rankings[int(i)], row, int(i), 10) for i, row in zip(validation, bm25_val)]
    rrf_test = [_rrf(baseline_rankings[int(i)], row, int(i), 10) for i, row in zip(test, bm25_test)]
    output["candidates"]["tfidf_bm25_rrf"] = {
        "validation": _metrics(rrf_val, validation, relevant, len(papers), baseline.matrix),
        "test": _metrics(rrf_test, test, relevant, len(papers), baseline.matrix),
        "runtime": {"method": "RRF k=60; combines rank positions, not raw score scales",
                    "additional_matrix_bytes": int(bm25.data.nbytes + bm25.indices.nbytes + bm25.indptr.nbytes)},
    }
    output["limitations"] = [
        "Term overlap is a weak label proxy; these offline results do not establish user-perceived relevance.",
        "All corpus papers are searchable for each query split; only query IDs are disjoint (transductive retrieval evaluation).",
        "Validation selection and category-overlap ranking are proxy-driven; candidate category features are omitted to avoid target leakage.",
        "Diversity uses the same preserved baseline TF-IDF space for all ranked lists.",
        "Latency is a warm in-process retrieval measurement and excludes network, serialization, and database time.",
    ]
    output["evaluation_runtime_seconds"] = round(time.perf_counter() - evaluation_started, 3)
    peak_working_set = _peak_working_set_bytes()
    output["peak_process_working_set_bytes"] = peak_working_set
    output["peak_process_working_set_mb"] = round(peak_working_set / (1024 * 1024), 1) if peak_working_set else None
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
