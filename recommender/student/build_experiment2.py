"""Fit business Popular, Cold Start and ItemCF models from sealed history.

Run on the host before rebuilding the API image:
    python -m recommender.student.build_experiment2
The generated artifacts stay under the ignored models/business directory.
"""

import csv
import heapq
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from recommender.data import DATASET, MANIFEST_SHA, SCHEMA, SPLIT, FrozenData, require, sha256


ROOT = Path(__file__).resolve().parents[2]
TRAINING = "business/history_ratings.csv"
POPULAR_VERSION = "popular-bayes-v2"
COLD_VERSION = "cold-popular-v2"
ITEMCF_VERSION = "itemcf-cobehavior-v1"
MAX_LIKES_PER_USER = 30
MAX_NEIGHBORS = 80
MOVIE_BITS = 20


def _write_model(data: FrozenData, algorithm: str, version: str, artifact: dict,
                 parameters: dict, extra_features: tuple[str, ...] = ()) -> Path:
    directory = ROOT / "models" / "business" / version
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / "model.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {
        "algorithm": algorithm, "model_version": version, "runtime_mode": "business",
        "dataset_version": DATASET, "split_version": SPLIT, "schema_version": SCHEMA,
        "manifest_sha256": MANIFEST_SHA,
        "training_files": {TRAINING: data.manifest["files"][TRAINING]["sha256"]},
        "feature_files": {name: data.manifest["files"][name]["sha256"]
                          for name in ("training-catalog.csv", *extra_features)},
        "artifacts": {"model.json": sha256(artifact_path)},
        "parameters": parameters,
        "tool_versions": {"python": "3.12", "implementation": "cinelab-experiment2-v1"},
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def fit() -> tuple[Path, Path, Path]:
    data = FrozenData()
    catalog = data.catalog()
    data.checked("training-catalog.csv")
    source = data.package / TRAINING
    expected = data.manifest["files"][TRAINING]
    require(source.is_file() and source.stat().st_size == expected["bytes"] and
            sha256(source) == expected["sha256"], "业务历史评分摘要不符", "DATA_IDENTITY_INVALID")

    counts: Counter[int] = Counter()
    totals: dict[int, float] = defaultdict(float)
    # A bounded set of strongest positive ratings per historical user keeps the
    # item-pair fit deterministic and avoids prolific users dominating memory.
    user_likes: dict[int, list[tuple[float, int, int]]] = defaultdict(list)
    row_count = 0
    with source.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == expected["columns"], "业务评分列不符", "DATA_IDENTITY_INVALID")
        for row in reader:
            movie_id = int(row["movieId"])
            require(str(movie_id) in catalog, "业务评分含目录外电影", "DATA_IDENTITY_INVALID")
            rating = float(row["rating"])
            counts[movie_id] += 1
            totals[movie_id] += rating
            if rating >= 4.0:
                likes = user_likes[int(row["userId"])]
                entry = (rating, int(row["timestamp"]), movie_id)
                if len(likes) < MAX_LIKES_PER_USER:
                    heapq.heappush(likes, entry)
                elif entry > likes[0]:
                    heapq.heapreplace(likes, entry)
            row_count += 1
    require(row_count == expected["records"], "业务评分行数不符", "DATA_IDENTITY_INVALID")

    ranked = []
    for movie_id in map(int, catalog):
        count = counts[movie_id]
        bayes = (totals[movie_id] + 100 * 3.5) / (count + 100)
        score = bayes * math.log1p(count)
        ranked.append([str(movie_id), round(score, 8), count, round(totals[movie_id] / count, 4) if count else None])
    ranked.sort(key=lambda row: (-row[1], int(row[0])))

    popular_artifact = {"model_version": POPULAR_VERSION, "ranked": ranked}
    popular = _write_model(data, "popular", POPULAR_VERSION, popular_artifact,
                           {"score": "Bayesian mean multiplied by log(1 + rating count)",
                            "prior_mean": 3.5, "prior_count": 100})
    movie_genres = {row["movie_id"]: sorted(set(row["genres"].split("|")) - {"(no genres listed)", ""})
                    for row in data.rows("movies.csv") if row["movie_id"] in catalog}
    require(set(movie_genres) == catalog, "冷启动电影类型与目录不一致", "DATA_IDENTITY_INVALID")
    cold = _write_model(data, "cold_start", COLD_VERSION,
                        {"model_version": COLD_VERSION, "ranked": ranked, "genres": movie_genres},
                        {"strategy": "zero-behavior popular fallback; optional genre-filtered popular",
                         "popular_model": POPULAR_VERSION}, extra_features=("movies.csv",))

    positive_users: Counter[int] = Counter()
    pairs: dict[int, list[float | int]] = {}
    for likes in user_likes.values():
        selected = sorted(likes, key=lambda entry: entry[2])
        if len(selected) < 2:
            continue
        for _, _, movie_id in selected:
            positive_users[movie_id] += 1
        user_weight = 1 / math.sqrt(len(selected))
        for left, right in combinations(selected, 2):
            left_id, right_id = left[2], right[2]
            require(left_id < 2**MOVIE_BITS and right_id < 2**MOVIE_BITS,
                    "电影ID超出共现键范围", "DATA_IDENTITY_INVALID")
            key = (left_id << MOVIE_BITS) | right_id
            pair = pairs.get(key)
            strength = user_weight * ((left[0] - 3) / 2) * ((right[0] - 3) / 2)
            if pair is None:
                pairs[key] = [strength, 1]
            else:
                pair[0] += strength
                pair[1] += 1
    neighbors: dict[int, list[list[float | int]]] = defaultdict(list)
    mask = (1 << MOVIE_BITS) - 1
    for key, (strength, support) in pairs.items():
        if support < 2:
            continue
        left_id, right_id = key >> MOVIE_BITS, key & mask
        similarity = strength / math.sqrt(positive_users[left_id] * positive_users[right_id])
        similarity *= support / (support + 3)
        if similarity <= 0:
            continue
        value = round(similarity, 8)
        neighbors[left_id].append([right_id, value])
        neighbors[right_id].append([left_id, value])
    compact = {str(movie_id): sorted(items, key=lambda item: (-item[1], item[0]))[:MAX_NEIGHBORS]
               for movie_id, items in neighbors.items()}
    itemcf = _write_model(data, "itemcf", ITEMCF_VERSION,
                          {"model_version": ITEMCF_VERSION, "neighbors": compact},
                          {"positive_rating_at_least": 4.0, "max_likes_per_user": MAX_LIKES_PER_USER,
                           "cooccurrence_weight": "rating strength / sqrt(user likes)",
                           "similarity": "cosine-like normalized cooccurrence with support shrinkage",
                           "minimum_pair_support": 2, "support_shrink": 3,
                           "max_neighbors_per_item": MAX_NEIGHBORS})
    print(f"Built Popular, Cold Start and ItemCF from {row_count} business ratings; "
          f"{len(catalog)} catalog films, {len(pairs)} observed item pairs")
    return popular, cold, itemcf


if __name__ == "__main__":
    fit()
