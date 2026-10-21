"""Bayesian popularity learned from the sealed business rating history."""

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from recommender.contracts import Algorithm, RecommendationItem, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require

MODEL_VERSION = "popular-bayes-v1"


@lru_cache(maxsize=1)
def load_ranking(path: str, version: str) -> list[list]:
    try:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        require(artifact["model_version"] == version, "热门模型版本不符", "MODEL_BINDING_INVALID")
        return artifact["ranked"]
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ContractError("MODEL_BINDING_INVALID", "热门模型工件无法读取") from exc


def ranked_result(request: RecommendationRequest, algorithm: Algorithm, version: str,
                  ranking: list[list], recall_source: str) -> RecommendationResult:
    items = [RecommendationItem(movie_id=movie_id, rank=rank, algorithm=algorithm,
                                model_version=version, score=score,
                                recall_sources=[recall_source])
             for rank, (movie_id, score, _count, _mean) in enumerate(ranking[:request.limit], 1)]
    return RecommendationResult(algorithm=algorithm, model_version=version,
                                dataset_version=request.dataset_version,
                                split_version=request.split_version,
                                runtime_mode=request.runtime_mode,
                                generated_at=datetime.now(timezone.utc), items=items)


class PopularProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        require(request.runtime_mode == "business", "热门模型仅用于业务模式", "DATA_MODE_INVALID")
        ranking = load_ranking(str(self.model_manifest_path.parent / "model.json"), MODEL_VERSION)
        return ranked_result(request, Algorithm.popular, MODEL_VERSION, ranking, "rating_count_and_mean")
