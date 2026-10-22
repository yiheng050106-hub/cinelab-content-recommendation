"""Fit Content and ItemCF evaluation models solely on the frozen evaluation train split."""

import heapq
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from recommender.data import DATASET, MANIFEST_SHA, SCHEMA, SPLIT, FrozenData, require, sha256

ROOT = Path(__file__).resolve().parents[2]
TRAIN = "evaluation/train.csv"
CONTENT_VERSION = "content-genres-eval-v1"
ITEMCF_VERSION = "itemcf-cobehavior-eval-v1"
POPULAR_VERSION = "popular-bayes-eval-v2"


def _save(data: FrozenData, algorithm: str, version: str, filename: str,
          artifact: dict, features: tuple[str, ...], parameters: dict) -> Path:
    folder = ROOT / "models" / "evaluation" / version
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / filename
    output.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    manifest = {"algorithm": algorithm, "model_version": version, "runtime_mode": "evaluation",
                "dataset_version": DATASET, "split_version": SPLIT, "schema_version": SCHEMA,
                "manifest_sha256": MANIFEST_SHA,
                "training_files": {TRAIN: data.manifest["files"][TRAIN]["sha256"]},
                "feature_files": {name: data.manifest["files"][name]["sha256"] for name in features},
                "artifacts": {filename: sha256(output)}, "parameters": parameters,
                "tool_versions": {"python": ".".join(map(str, sys.version_info[:3])),
                                  "implementation": "cinelab-evaluation-v1"}}
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def fit() -> tuple[Path, Path, Path]:
    data = FrozenData()
    catalog = data.catalog()
    genres = {row["movie_id"]: sorted(set(row["genres"].split("|")) - {"(no genres listed)", ""})
              for row in data.rows("movies.csv") if row["movie_id"] in catalog}
    require(set(genres) == catalog, "评价电影类型不完整", "DATA_IDENTITY_INVALID")
    df: Counter[str] = Counter()
    for values in genres.values():
        df.update(values)
    counts: Counter[str] = Counter()
    totals: dict[str, float] = defaultdict(float)
    likes: dict[str, list[tuple[float, int, int]]] = defaultdict(list)
    for row in data.training():
        mid, uid, rating = row["movieId"], row["userId"], float(row["rating"])
        require(mid in catalog, "评价训练含目录外电影", "DATA_IDENTITY_INVALID")
        counts[mid] += 1
        totals[mid] += rating
        if rating >= 4.0:
            bucket = likes[uid]
            entry = (rating, int(row["timestamp"]), int(mid))
            if len(bucket) < 30:
                heapq.heappush(bucket, entry)
            elif entry > bucket[0]:
                heapq.heapreplace(bucket, entry)

    n = len(catalog)
    idf = {name: round(math.log((n + 1) / (count + 1)) + 1, 8) for name, count in sorted(df.items())}
    movies = {mid: [values, round((totals[mid] + 25 * 3.5) / (counts[mid] + 25), 6)]
              for mid, values in sorted(genres.items(), key=lambda pair: int(pair[0]))}
    content = _save(data, "content", CONTENT_VERSION, "features.json",
                    {"model_version": CONTENT_VERSION, "idf": idf, "movies": movies},
                    ("movies.csv", "training-catalog.csv"),
                    {"features": "genres", "weighting": "TF-IDF cosine", "positive_center": 3.0,
                     "negative_weight": 0.5, "quality_prior_weight": 0.08,
                     "quality_prior_pseudocount": 25})

    popular_rows = []
    for mid in catalog:
        count = counts[mid]
        bayes = (totals[mid] + 100 * 3.5) / (count + 100)
        score = bayes * math.log1p(count)
        popular_rows.append([mid, round(score, 8), count,
                             round(totals[mid] / count, 4) if count else None])
    popular_rows.sort(key=lambda row: (-row[1], int(row[0])))
    popular = _save(data, "popular", POPULAR_VERSION, "model.json",
                    {"model_version": POPULAR_VERSION, "ranked": popular_rows},
                    ("training-catalog.csv",),
                    {"score": "Bayesian mean multiplied by log(1 + rating count)",
                     "prior_mean": 3.5, "prior_count": 100})

    positive_users: Counter[int] = Counter()
    pairs: dict[int, list[float | int]] = {}
    for bucket in likes.values():
        selected = sorted(bucket, key=lambda entry: entry[2])
        if len(selected) < 2:
            continue
        for _, _, mid in selected:
            positive_users[mid] += 1
        user_weight = 1 / math.sqrt(len(selected))
        for left, right in combinations(selected, 2):
            left_id, right_id = left[2], right[2]
            require(left_id < 2**20 and right_id < 2**20,
                    "电影ID超出共现键范围", "DATA_IDENTITY_INVALID")
            key = (left_id << 20) | right_id
            strength = user_weight * ((left[0] - 3) / 2) * ((right[0] - 3) / 2)
            if key not in pairs:
                pairs[key] = [strength, 1]
            else:
                pairs[key][0] += strength
                pairs[key][1] += 1
    neighbors: dict[int, list[list[float | int]]] = defaultdict(list)
    for key, (strength, support) in pairs.items():
        if support < 2:
            continue
        left_id, right_id = key >> 20, key & ((1 << 20) - 1)
        similarity = strength / math.sqrt(positive_users[left_id] * positive_users[right_id])
        similarity *= support / (support + 3)
        if similarity <= 0:
            continue
        value = round(similarity, 8)
        neighbors[left_id].append([right_id, value])
        neighbors[right_id].append([left_id, value])
    compact = {str(mid): sorted(entries, key=lambda entry: (-entry[1], entry[0]))[:80]
               for mid, entries in neighbors.items()}
    itemcf = _save(data, "itemcf", ITEMCF_VERSION, "model.json",
                   {"model_version": ITEMCF_VERSION, "neighbors": compact},
                   ("training-catalog.csv",),
                   {"positive_rating_at_least": 4.0, "max_likes_per_user": 30,
                    "minimum_pair_support": 2, "support_shrink": 3,
                    "max_neighbors_per_item": 80})
    print(f"Built evaluation Popular, Content and ItemCF from {sum(counts.values())} train ratings")
    return popular, content, itemcf


if __name__ == "__main__":
    fit()
