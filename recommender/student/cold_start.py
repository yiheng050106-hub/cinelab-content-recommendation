"""Zero-behavior account fallback to the learned popularity ranking."""

import json
from functools import lru_cache
from pathlib import Path

from recommender.contracts import Algorithm, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require
from .popular import ranked_result

MODEL_VERSION = "cold-popular-v1"


@lru_cache(maxsize=1)
def _model(path: str) -> tuple[list[list], dict[str, list[str]]]:
    try:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        require(artifact["model_version"] == MODEL_VERSION, "冷启动模型版本不符", "MODEL_BINDING_INVALID")
        return artifact["ranked"], artifact["genres"]
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ContractError("MODEL_BINDING_INVALID", "冷启动模型工件无法读取") from exc


class ColdStartProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        from recommender.business import read_history

        require(request.runtime_mode == "business", "冷启动模型仅用于业务模式", "DATA_MODE_INVALID")
        require(request.subject_kind == "app", "请选择新注册账号进行冷启动实验", "COLD_START_REQUIRES_APP")
        history = read_history(request)
        require(not history.ratings and not history.favorite_movie_ids,
                "冷启动实验要求零评分、零收藏账号", "COLD_START_REQUIRES_ZERO_BEHAVIOR")
        ranking, genres = _model(str(self.model_manifest_path.parent / "model.json"))
        if request.interest_genres:
            known = {genre for values in genres.values() for genre in values}
            require(set(request.interest_genres) <= known,
                    "电影目录中没有选定的兴趣类型", "COLD_START_INTEREST_INVALID")
            ranking = [row for row in ranking
                       if set(request.interest_genres) & set(genres[row[0]])]
        return ranked_result(request, Algorithm.cold_start, MODEL_VERSION, ranking,
                             "genre_filtered_popular" if request.interest_genres
                             else "zero_behavior_popular_fallback")
