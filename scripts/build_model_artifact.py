"""Fit the Phase 2 TF-IDF engine once and serialize it for API startup."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from researchpaper_ai.model_artifact import build_model_artifact


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cleaned", default=os.getenv("CLEANED_DATA_PATH", "data/processed/papers_clean.csv")
    )
    parser.add_argument(
        "--output", default=os.getenv("MODEL_ARTIFACT_PATH", "artifacts/recommender.joblib")
    )
    args = parser.parse_args()
    artifact = build_model_artifact(args.cleaned, args.output)
    print(f"Fitted model artifact written to {artifact}")


if __name__ == "__main__":
    main()
