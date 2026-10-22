"""Serve real Spark MLlib ALS item/user factors in business mode."""

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from recommender.contracts import Algorithm, RecommendationItem, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require

MODEL_VERSION = "als-spark-explicit-v2"
SUPPORT_PRIOR = 25
GLOBAL_PRIOR = 3.5


@lru_cache(maxsize=1)
def load_factors(path: str) -> tuple[int, dict[str, list[float]], dict[str, list[float]], dict[str, int]]:
    try:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        require(artifact["model_version"] == MODEL_VERSION, "ALS模型版本不符", "MODEL_BINDING_INVALID")
        rank = artifact["rank"]
        users, items, support = artifact["users"], artifact["items"], artifact["support"]
        require(type(rank) is int and rank > 0 and bool(users) and bool(items) and
                set(support) == set(items) and all(type(n) is int and n > 0 for n in support.values()) and
                all(len(row) == rank and all(math.isfinite(x) for x in row)
                    for row in (*users.values(), *items.values())),
                "ALS因子不完整", "MODEL_BINDING_INVALID")
        return rank, users, items, support
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ContractError("MODEL_BINDING_INVALID", "ALS模型工件无法读取") from exc


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Small ridge system for a newly registered user, without fitting on evaluation labels."""
    size = len(vector)
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(matrix[row][col]))
        require(abs(matrix[pivot][col]) > 1e-12, "ALS新用户因子不可解", "MODEL_BINDING_INVALID")
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        vector[col], vector[pivot] = vector[pivot], vector[col]
        scale = matrix[col][col]
        for j in range(col, size):
            matrix[col][j] /= scale
        vector[col] /= scale
        for row in range(size):
            if row == col:
                continue
            weight = matrix[row][col]
            for j in range(col, size):
                matrix[row][j] -= weight * matrix[col][j]
            vector[row] -= weight * vector[col]
    return vector


def fold_in(rank: int, items: dict[str, list[float]], history) -> list[float] | None:
    rated = {entry.movie_id for entry in history.ratings}
    observations = [(items[entry.movie_id], float(entry.rating), 1.0)
                    for entry in history.ratings if entry.movie_id in items]
    observations += [(items[mid], 4.0, 0.5) for mid in history.favorite_movie_ids
                     if mid not in rated and mid in items]
    if not observations:
        return None
    ridge = 0.12 * len(observations)
    matrix = [[ridge if i == j else 0.0 for j in range(rank)] for i in range(rank)]
    vector = [0.0] * rank
    for factors, rating, strength in observations:
        for i in range(rank):
            vector[i] += strength * rating * factors[i]
            for j in range(rank):
                matrix[i][j] += strength * factors[i] * factors[j]
    return _solve(matrix, vector)


class ALSProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        from recommender.business import read_history

        require(request.runtime_mode == "business", "业务ALS不用于离线评价", "DATA_MODE_INVALID")
        rank, users, items, support = load_factors(str(self.model_manifest_path.parent / "factors.json"))
        history = read_history(request)
        seen = {entry.movie_id for entry in history.ratings} | set(history.favorite_movie_ids)
        factors = users.get(str(request.subject_id)) if request.subject_kind == "ml" else fold_in(rank, items, history)
        scored = [] if factors is None else [
            (mid, round(GLOBAL_PRIOR + support[mid] / (support[mid] + SUPPORT_PRIOR) *
                        (sum(left * right for left, right in zip(factors, values)) - GLOBAL_PRIOR), 8))
            for mid, values in items.items() if mid not in seen]
        scored.sort(key=lambda pair: (-pair[1], int(pair[0])))
        selected = scored[:request.limit]
        result_items = [RecommendationItem(movie_id=mid, rank=rank_pos, algorithm=Algorithm.als,
                                           model_version=MODEL_VERSION, score=round(score, 8),
                                           recall_sources=["spark_als_factors"])
                        for rank_pos, (mid, score) in enumerate(selected, 1)]
        return RecommendationResult(algorithm=Algorithm.als, model_version=MODEL_VERSION,
                                    dataset_version=request.dataset_version, split_version=request.split_version,
                                    runtime_mode=request.runtime_mode, generated_at=datetime.now(timezone.utc),
                                    items=result_items)
