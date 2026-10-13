"""Deterministic CSV ingestion and cleaning for the arXiv dataset."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Paper:
    paper_id: str
    title: str
    abstract: str
    terms: tuple[str, ...]
    source_rows: tuple[int, ...]

    @property
    def text(self) -> str:
        return f"{self.title} {self.title} {self.abstract}".strip()


def _normalise_text(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def _identity_text(value: str | None) -> str:
    return _normalise_text(value).casefold()


def parse_terms(value: str | list | tuple | None) -> tuple[str, ...]:
    """Safely parse the dataset's list-like category value; never evaluates code."""
    if value is None or not str(value).strip():
        return ()
    parsed = value if isinstance(value, (list, tuple)) else ast.literal_eval(str(value))
    if not isinstance(parsed, (list, tuple)):
        raise ValueError("terms must be a list or tuple")
    result = {str(item).strip() for item in parsed if isinstance(item, str) and item.strip()}
    return tuple(sorted(result, key=lambda item: (item.casefold(), item)))


def _paper_id(title: str, abstract: str) -> str:
    identity = json.dumps(
        [_identity_text(title), _identity_text(abstract)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "paper_" + hashlib.sha256(identity).hexdigest()


def clean_records(records: Iterable[dict[str, str]]) -> tuple[list[Paper], dict[str, int]]:
    """Remove exact repeats, merge metadata repeats, and preserve distinct abstracts.

    Exact source records are counted once. Records sharing normalized title and
    abstract are represented once with the union of their terms. A repeated
    title with a different normalized abstract remains a distinct paper.
    """
    exact_seen: set[tuple[str, str, str]] = set()
    grouped: dict[tuple[str, str], dict] = {}
    exact_duplicate_rows = 0
    unusable_text_rows = 0
    parsed_rows = 0

    for source_row, row in enumerate(records, start=2):  # CSV header is line 1
        title = _normalise_text(row.get("titles"))
        abstract = _normalise_text(row.get("abstracts"))
        raw_terms = row.get("terms", "")
        terms = parse_terms(raw_terms)
        parsed_rows += 1

        exact_key = (str(raw_terms), str(row.get("titles", "")), str(row.get("abstracts", "")))
        if exact_key in exact_seen:
            exact_duplicate_rows += 1
            continue
        exact_seen.add(exact_key)

        if not (title or abstract):
            unusable_text_rows += 1
            continue

        identity = (_identity_text(title), _identity_text(abstract))
        item = grouped.get(identity)
        if item is None:
            grouped[identity] = {
                "title": title,
                "abstract": abstract,
                "terms": set(terms),
                "source_rows": [source_row],
            }
        else:
            item["terms"].update(terms)
            item["source_rows"].append(source_row)

    papers = [
        Paper(
            paper_id=_paper_id(item["title"], item["abstract"]),
            title=item["title"],
            abstract=item["abstract"],
            terms=tuple(sorted(item["terms"], key=lambda value: (value.casefold(), value))),
            source_rows=tuple(item["source_rows"]),
        )
        for item in grouped.values()
    ]
    papers.sort(key=lambda paper: paper.paper_id)

    duplicate_title_groups: dict[str, set[str]] = {}
    for paper in papers:
        duplicate_title_groups.setdefault(_identity_text(paper.title), set()).add(
            _identity_text(paper.abstract)
        )
    repeated_title_groups = sum(len(abstracts) > 1 for abstracts in duplicate_title_groups.values())
    stats = {
        "source_rows": parsed_rows,
        "exact_duplicate_rows_removed": exact_duplicate_rows,
        "same_title_abstract_rows_merged": sum(len(p.source_rows) - 1 for p in papers),
        "repeated_title_groups_with_distinct_abstracts": repeated_title_groups,
        "unusable_text_rows_removed": unusable_text_rows,
        "clean_rows": len(papers),
    }
    return papers, stats


def read_source(path: str | Path) -> tuple[list[Paper], dict[str, int]]:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"terms", "titles", "abstracts"}
        if set(reader.fieldnames or ()) != expected:
            raise ValueError(f"Expected CSV columns {sorted(expected)}, got {reader.fieldnames}")
        return clean_records(reader)


def write_clean_csv(papers: Iterable[Paper], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["paper_id", "titles", "abstracts", "terms", "source_rows"],
            lineterminator="\n",
        )
        writer.writeheader()
        for paper in sorted(papers, key=lambda item: item.paper_id):
            writer.writerow(
                {
                    "paper_id": paper.paper_id,
                    "titles": paper.title,
                    "abstracts": paper.abstract,
                    "terms": json.dumps(paper.terms, ensure_ascii=False, separators=(",", ":")),
                    "source_rows": json.dumps(paper.source_rows, separators=(",", ":")),
                }
            )


def load_clean_csv(path: str | Path) -> list[Paper]:
    papers: list[Paper] = []
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            papers.append(
                Paper(
                    paper_id=row["paper_id"],
                    title=row["titles"],
                    abstract=row["abstracts"],
                    terms=parse_terms(row["terms"]),
                    source_rows=tuple(int(value) for value in ast.literal_eval(row["source_rows"])),
                )
            )
    return papers


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Create the reproducible cleaned paper CSV.")
    parser.add_argument("--source", default="data/arxiv_data_210930-054931.csv")
    parser.add_argument("--output", default="data/processed/papers_clean.csv")
    args = parser.parse_args()
    papers, stats = read_source(args.source)
    write_clean_csv(papers, args.output)
    print(json.dumps({**stats, "output": args.output}, indent=2))


if __name__ == "__main__":
    main()
