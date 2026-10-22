"""Offline validation Precision@10/Recall@10 from the sealed course split.

Fit artifacts are read only; validation labels are opened only after predictions
have been generated and checked against each user's train-only candidate set.
"""

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from recommender.contracts import Algorithm, RecommendationItem, RecommendationResult
from recommender.data import DATASET, SCHEMA, SPLIT, FrozenData, sha256
from recommender.evaluation import (check_evaluation_result, check_predictions,
                                    eligible_users, task)
from recommender.validation import check_model

ROOT = Path(__file__).resolve().parents[2]
MODELS = {
    "content": "content-genres-eval-v1",
    "itemcf": "itemcf-cobehavior-eval-v1",
    "als": "als-spark-explicit-v1",
}


def _dto(algorithm: str, version: str, ranked: list[tuple[str, float]]) -> dict:
    items = [RecommendationItem(movie_id=mid, rank=index, algorithm=Algorithm(algorithm),
                                model_version=version, score=score,
                                recall_sources=["offline_train_only"])
             for index, (mid, score) in enumerate(ranked, 1)]
    return RecommendationResult(algorithm=Algorithm(algorithm), model_version=version,
                                dataset_version=DATASET, split_version=SPLIT,
                                runtime_mode="evaluation", generated_at=datetime.now(timezone.utc),
                                items=items).model_dump(mode="json")


def _top(scores: np.ndarray, movie_ids: list[str], excluded: set[str]) -> list[tuple[str, float]]:
    # Round before sorting, matching the recommendation DTO's visible scores.
    choices = [(mid, round(float(value), 8)) for mid, value in zip(movie_ids, scores)
               if mid not in excluded and math.isfinite(value) and value > 0]
    choices.sort(key=lambda pair: (-pair[1], int(pair[0])))
    return choices[:10]


def evaluate() -> dict:
    data = FrozenData()
    users = sorted(eligible_users(data, "validation"), key=int)
    users_set = set(users)
    catalog = sorted(data.catalog(), key=int)
    histories: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in data.training():
        if row["userId"] in users_set:
            histories[row["userId"]].append((row["movieId"], float(row["rating"])))
    exclusions = {uid: {mid for mid, _ in histories[uid]} for uid in users}
    job = task(data, "validation")
    manifests = {name: ROOT / "models" / "evaluation" / version / "manifest.json"
                 for name, version in MODELS.items()}
    for name, path in manifests.items():
        check_model(path, "evaluation", name, data)

    content = json.loads((manifests["content"].parent / "features.json").read_text(encoding="utf-8"))
    idf = content["idf"]
    genres = sorted(idf)
    genre_index = {name: index for index, name in enumerate(genres)}
    movie_index = {mid: index for index, mid in enumerate(catalog)}
    vectors = np.zeros((len(catalog), len(genres)), dtype=np.float32)
    qualities = np.zeros(len(catalog), dtype=np.float32)
    for mid, (names, quality) in content["movies"].items():
        values = [idf[name] for name in names]
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            for name, value in zip(names, values):
                vectors[movie_index[mid], genre_index[name]] = value / norm
        qualities[movie_index[mid]] = quality

    neighbors = json.loads((manifests["itemcf"].parent / "model.json").read_text(encoding="utf-8"))["neighbors"]
    factors = json.loads((manifests["als"].parent / "factors.json").read_text(encoding="utf-8"))
    als_movies = sorted(factors["items"], key=int)
    als_matrix = np.asarray([factors["items"][mid] for mid in als_movies], dtype=np.float32)
    outputs = {name: ROOT / "models" / "evaluation" / f"{name}-validation-predictions.jsonl"
               for name in MODELS}
    streams = {name: path.open("w", encoding="utf-8", newline="\n") for name, path in outputs.items()}
    try:
        for uid in users:
            history = histories[uid]
            seen = exclusions[uid]
            profile = np.zeros(len(genres), dtype=np.float32)
            positive_count = 0
            for mid, rating in history:
                weight = max(0, rating - 3.0) - 0.5 * max(0, 3.0 - rating)
                if weight > 0:
                    positive_count += 1
                if weight:
                    profile += weight * vectors[movie_index[mid]]
            norm = np.linalg.norm(profile)
            content_top = []
            if positive_count and norm:
                similarity = vectors @ (profile / norm)
                scores = np.where(similarity > 0, similarity + 0.08 * (qualities - 3.0) / 2.0, -1.0)
                content_top = _top(scores, catalog, seen)

            cf_scores: dict[str, float] = defaultdict(float)
            for mid, rating in history:
                weight = max(0, rating - 3.0)
                if weight:
                    for candidate, similarity in neighbors.get(mid, ()):
                        key = str(candidate)
                        if key not in seen:
                            cf_scores[key] += weight * float(similarity)
            cf_top = sorted(((mid, round(score, 8)) for mid, score in cf_scores.items() if score > 0),
                            key=lambda pair: (-pair[1], int(pair[0])))[:10]

            user_factor = factors["users"].get(uid)
            als_top = _top(als_matrix @ np.asarray(user_factor, dtype=np.float32), als_movies, seen) if user_factor else []
            for name, ranked in (("content", content_top), ("itemcf", cf_top), ("als", als_top)):
                dto = _dto(name, MODELS[name], ranked)
                streams[name].write(json.dumps({"ml_user_id": uid, "result": dto}, separators=(",", ":")) + "\n")
    finally:
        for stream in streams.values():
            stream.close()

    # Validate all recommendations before reading relevance labels.
    for name, path in outputs.items():
        check_predictions(path, manifests[name], "validation", data)
    positives: dict[str, set[str]] = {uid: set() for uid in users}
    for row in data.rows("evaluation/validation.csv", evaluation=True):
        if row["userId"] in positives and float(row["rating"]) >= 4.0:
            positives[row["userId"]].add(row["movieId"])
    summary = {"status": "completed", "partition": "validation", "task_sha256": job["task_sha256"],
               "dataset_version": DATASET, "split_version": SPLIT, "schema_version": SCHEMA,
               "user_count": len(users), "positive_threshold": 4.0, "top_k": 10,
               "computed_at": datetime.now(timezone.utc).isoformat(), "metrics": []}
    for name, path in outputs.items():
        precision = recall = 0.0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                relevant = positives[row["ml_user_id"]]
                recommended = [item["movie_id"] for item in row["result"]["items"]]
                hits = len(relevant.intersection(recommended))
                precision += hits / 10
                recall += hits / len(relevant) if relevant else 0.0
        metric = {"status": "completed", "runtime_mode": "evaluation", "algorithm": name,
                  "model_version": MODELS[name], "task_sha256": job["task_sha256"],
                  "model_manifest_sha256": sha256(manifests[name]), "dataset_version": DATASET,
                  "split_version": SPLIT, "schema_version": SCHEMA, "partition": "validation",
                  "user_count": len(users), "precision_at_10": precision / len(users),
                  "recall_at_10": recall / len(users)}
        result_path = ROOT / "models" / "evaluation" / f"{name}-validation-result.json"
        result_path.write_text(json.dumps(metric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        check_evaluation_result(result_path, manifests[name], data)
        summary["metrics"].append({"algorithm": name, "model_version": MODELS[name],
                                   "precision_at_10": metric["precision_at_10"],
                                   "recall_at_10": metric["recall_at_10"]})
    summary_path = ROOT / "models" / "business" / "evaluation-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    evaluate()
