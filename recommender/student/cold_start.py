"""Zero-behavior account fallback to the learned popularity ranking."""

from pathlib import Path

from recommender.contracts import Algorithm, RecommendationRequest, RecommendationResult
from recommender.data import require
from .popular import load_ranking, ranked_result

MODEL_VERSION = "cold-popular-v1"


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
        ranking = load_ranking(str(self.model_manifest_path.parent / "model.json"), MODEL_VERSION)
        return ranked_result(request, Algorithm.cold_start, MODEL_VERSION, ranking,
                             "zero_behavior_popular_fallback")
