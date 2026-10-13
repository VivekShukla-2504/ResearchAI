import pytest
import numpy as np
import joblib

from researchpaper_ai.data import clean_records, parse_terms
from researchpaper_ai.engine import ResearchPaperRecommender
from researchpaper_ai.model_artifact import load_model_artifact


def tiny_papers():
    rows = [
        {"terms": "['cs.AI']", "titles": "Graph learning", "abstracts": "Neural graph networks learn representations."},
        {"terms": "['cs.AI']", "titles": "Graph learning", "abstracts": "Neural graph networks learn representations."},
        {"terms": "['cs.AI', 'cs.LG']", "titles": "Graph learning", "abstracts": "Neural graph networks learn representations."},
        {"terms": "['cs.LG']", "titles": "Graph attention", "abstracts": "Attention models process graph nodes."},
        {"terms": "['math.PR']", "titles": "Probability bounds", "abstracts": "Concentration inequalities and random variables."},
    ]
    return rows


def test_stable_ids_and_duplicate_policy():
    papers_a, stats = clean_records(tiny_papers())
    papers_b, _ = clean_records(list(reversed(tiny_papers())))
    assert {paper.paper_id for paper in papers_a} == {paper.paper_id for paper in papers_b}
    graph = next(paper for paper in papers_a if paper.title == "Graph learning")
    assert graph.terms == ("cs.AI", "cs.LG")
    assert len([paper for paper in papers_a if paper.title == "Graph learning"]) == 1
    assert stats["same_title_abstract_rows_merged"] == 1
    assert stats["exact_duplicate_rows_removed"] == 1


def test_repeated_title_with_distinct_abstracts_is_preserved():
    rows = tiny_papers() + [
        {"terms": "['cs.AI']", "titles": "Graph learning", "abstracts": "A different graph learning method."}
    ]
    papers, _ = clean_records(rows)
    assert len([paper for paper in papers if paper.title == "Graph learning"]) == 2


def test_missing_text_field_is_allowed_but_fully_empty_record_is_removed():
    rows = tiny_papers() + [
        {"terms": "[]", "titles": "", "abstracts": "A usable abstract remains."},
        {"terms": "[]", "titles": " ", "abstracts": ""},
    ]
    papers, stats = clean_records(rows)
    assert any(paper.abstract == "A usable abstract remains." for paper in papers)
    assert stats["unusable_text_rows_removed"] == 1


def test_terms_parser_is_safe_and_validates_shape():
    assert parse_terms("['cs.AI', 'cs.LG', 'cs.AI']") == ("cs.AI", "cs.LG")
    with pytest.raises((ValueError, SyntaxError)):
        parse_terms("__import__('os').system('echo unsafe')")


def test_recommendation_excludes_source_and_returns_ranked_outputs():
    papers, _ = clean_records(tiny_papers())
    engine = ResearchPaperRecommender(papers, min_df=1, max_features=1000, ngram_range=(1, 2))
    source = next(paper for paper in papers if paper.title == "Graph learning")
    results = engine.recommend(paper_id=source.paper_id, top_k=2)
    assert len(results) == 2
    assert source.paper_id not in {result["paper_id"] for result in results}
    assert len({result["paper_id"] for result in results}) == len(results)
    assert results[0]["similarity"] >= results[1]["similarity"]
    assert all({"paper_id", "title", "abstract", "terms", "similarity"} <= set(item) for item in results)


def test_single_paper_corpus_returns_no_self_recommendation():
    papers, _ = clean_records([tiny_papers()[0]])
    engine = ResearchPaperRecommender(papers, min_df=1)
    assert engine.recommend(paper_id=papers[0].paper_id, top_k=10) == []


def test_empty_unknown_query_and_unknown_id():
    rows = tiny_papers() + [
        {"terms": "[]", "titles": "the and", "abstracts": "or but"}
    ]
    papers, _ = clean_records(rows)
    engine = ResearchPaperRecommender(papers, min_df=1)
    assert engine.recommend(query="  ") == []
    assert engine.recommend(query="termsoov unseenword") == []
    unusable = next(paper for paper in papers if paper.title == "the and")
    assert engine.recommend(paper_id=unusable.paper_id) == []
    with pytest.raises(KeyError):
        engine.recommend(paper_id="unknown")


def test_default_min_df_falls_back_for_a_tiny_nonempty_catalog():
    papers, _ = clean_records([
        {"terms": "[]", "titles": "Graph retrieval", "abstracts": "Sparse vectors."},
    ])
    engine = ResearchPaperRecommender(papers)
    assert engine.matrix.nnz > 0
    assert engine.recommend(paper_id=papers[0].paper_id) == []


def test_catalog_without_usable_tokens_fails_with_clear_message():
    papers, _ = clean_records([
        {"terms": "[]", "titles": "the and", "abstracts": "or but"},
    ])
    with pytest.raises(ValueError, match="No usable text features"):
        ResearchPaperRecommender(papers)


def test_nonfinite_similarity_scores_are_never_returned(monkeypatch):
    papers, _ = clean_records(tiny_papers() + [
        {"terms": "[]", "titles": "Graph retrieval", "abstracts": "Sparse retrieval methods."},
    ])
    engine = ResearchPaperRecommender(papers, min_df=1, max_features=1000)
    scores = np.asarray([[np.nan, np.inf, 0.8, 1.00001]], dtype=np.float32)
    monkeypatch.setattr("researchpaper_ai.engine.cosine_similarity", lambda *args, **kwargs: scores)
    results = engine.recommend(query="graph", top_k=4)
    assert all(np.isfinite(result["similarity"]) for result in results)
    assert all(0 <= result["similarity"] <= 1 for result in results)
    assert [item["paper_id"] for item in results] == [papers[3].paper_id, papers[2].paper_id]


def test_tied_scores_use_stable_paper_order(monkeypatch):
    papers, _ = clean_records(tiny_papers())
    engine = ResearchPaperRecommender(papers, min_df=1, max_features=1000)
    monkeypatch.setattr(
        "researchpaper_ai.engine.cosine_similarity",
        lambda *args, **kwargs: np.full((1, len(papers)), 0.5, dtype=np.float32),
    )
    first = engine.recommend(query="graph", top_k=2)
    second = engine.recommend(query="graph", top_k=2)
    assert [item["paper_id"] for item in first] == [item["paper_id"] for item in second]
    assert [item["paper_id"] for item in first] == [paper.paper_id for paper in papers[:2]]


def test_artifact_loader_rejects_mismatched_paper_id_index(tmp_path):
    papers, _ = clean_records(tiny_papers())
    engine = ResearchPaperRecommender(papers, min_df=1, max_features=1000)
    engine.id_to_index = {papers[0].paper_id: 1}
    path = tmp_path / "mismatched.joblib"
    joblib.dump(engine, path)
    with pytest.raises(ValueError, match="paper-ID index"):
        load_model_artifact(path)


def test_artifact_loader_rejects_nonfinite_feature_values(tmp_path):
    papers, _ = clean_records(tiny_papers())
    engine = ResearchPaperRecommender(papers, min_df=1, max_features=1000)
    engine.matrix.data[0] = np.nan
    path = tmp_path / "nonfinite.joblib"
    joblib.dump(engine, path)
    with pytest.raises(ValueError, match="non-finite"):
        load_model_artifact(path)

