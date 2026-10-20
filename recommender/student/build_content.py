"""Fit the business Content model from sealed MovieLens features and ratings.

Run once on the host before building the API image:
    python -m recommender.student.build_content
The generated business model stays local under models/business/.
"""

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from recommender.data import DATASET, MANIFEST_SHA, SCHEMA, SPLIT, FrozenData, require, sha256


MODEL_VERSION = "content-genres-v1"
MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "business" / MODEL_VERSION


def fit() -> Path:
    data = FrozenData()
    catalog = data.catalog()
    movies = {}
    document_frequency = Counter()
    for row in data.rows("movies.csv"):
        movie_id = row["movie_id"]
        if movie_id not in catalog:
            continue
        genres = sorted(set(row["genres"].split("|")) - {"(no genres listed)", ""})
        movies[movie_id] = genres
        document_frequency.update(genres)
    require(set(movies) == catalog, "电影特征与批准目录不一致", "DATA_IDENTITY_INVALID")

    name = "business/history_ratings.csv"
    source = data.package / name
    expected = data.manifest["files"][name]
    require(source.is_file() and source.stat().st_size == expected["bytes"] and
            sha256(source) == expected["sha256"], "业务历史评分摘要不符", "DATA_IDENTITY_INVALID")
    rating_count = Counter()
    rating_total = defaultdict(float)
    row_count = 0
    with source.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == expected["columns"], "业务评分列不符", "DATA_IDENTITY_INVALID")
        for row in reader:
            movie_id = row["movieId"]
            require(movie_id in catalog, "业务评分含目录外电影", "DATA_IDENTITY_INVALID")
            rating_count[movie_id] += 1
            rating_total[movie_id] += float(row["rating"])
            row_count += 1
    require(row_count == expected["records"], "业务评分行数不符", "DATA_IDENTITY_INVALID")

    n = len(movies)
    idf = {genre: round(math.log((n + 1) / (df + 1)) + 1, 8)
           for genre, df in sorted(document_frequency.items())}
    # The prior only resolves close content matches. It is fitted from business
    # history and shrunk toward 3.5 stars to avoid overvaluing tiny samples.
    records = {movie_id: [genres,
                          round((rating_total[movie_id] + 25 * 3.5) /
                                (rating_count[movie_id] + 25), 6)]
               for movie_id, genres in sorted(movies.items(), key=lambda pair: int(pair[0]))}
    artifact = {"model_version": MODEL_VERSION, "dataset_version": DATASET,
                "split_version": SPLIT, "idf": idf, "movies": records}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = MODEL_DIR / "features.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {
        "algorithm": "content", "model_version": MODEL_VERSION, "runtime_mode": "business",
        "dataset_version": DATASET, "split_version": SPLIT, "schema_version": SCHEMA,
        "manifest_sha256": MANIFEST_SHA,
        "training_files": {name: expected["sha256"]},
        "feature_files": {feature: data.manifest["files"][feature]["sha256"]
                          for feature in ("movies.csv", "training-catalog.csv")},
        "artifacts": {"features.json": sha256(artifact_path)},
        "parameters": {"features": "genres", "weighting": "TF-IDF cosine",
                       "positive_center": 3.0, "negative_weight": 0.5,
                       "quality_prior_weight": 0.08, "quality_prior_pseudocount": 25,
                       "favorite_implicit_weight": 0.8},
        "tool_versions": {"python": "3.12", "implementation": "cinelab-content-v1"},
    }
    manifest_path = MODEL_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {MODEL_VERSION}: {len(records)} films, {row_count} business ratings")
    return manifest_path


if __name__ == "__main__":
    fit()
