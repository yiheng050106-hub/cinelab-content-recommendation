"""Reciprocal rank fusion of independently computed, validated recommendations."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from recommender.business import read_history
from recommender.contracts import Algorithm, RecommendationItem, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require

MODEL_VERSION = "rrf-v1"


class RRFProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        require(request.runtime_mode == "business", "RRF 仅用于业务模式", "DATA_MODE_INVALID")
        try:
            config = json.loads((self.model_manifest_path.parent / "fusion.json").read_text(encoding="utf-8"))
            require(config["model_version"] == MODEL_VERSION and config["k"] > 0,
                    "RRF 模型配置不合法", "MODEL_BINDING_INVALID")
            sources = [Algorithm(name) for name in config["sources"]]
            require(len(sources) == len(set(sources)) and Algorithm.rrf not in sources,
                    "RRF 算法来源不合法", "MODEL_BINDING_INVALID")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ContractError("MODEL_BINDING_INVALID", "RRF 模型配置无法读取") from exc

        # A source's numerical score is deliberately ignored; only its live rank counts.
        from recommender.contracts import recommend

        seen_history = read_history(request)
        seen = {item.movie_id for item in seen_history.ratings} | set(seen_history.favorite_movie_ids)
        source_request = RecommendationRequest(request.subject_kind, request.subject_id, 50,
            request.runtime_mode, request.dataset_version, request.split_version)
        scores: dict[str, float] = defaultdict(float)
        ranks: dict[str, dict[str, int]] = defaultdict(dict)
        for source in sources:
            result = recommend(source, source_request)
            for item in result.items:
                if item.movie_id in seen:
                    continue
                scores[item.movie_id] += 1.0 / (config["k"] + item.rank)
                ranks[item.movie_id][source.value] = item.rank

        ordered = sorted(scores, key=lambda movie_id: (-scores[movie_id], int(movie_id)))[:request.limit]
        items = [RecommendationItem(movie_id=movie_id, rank=index,
            algorithm=Algorithm.rrf, model_version=MODEL_VERSION,
            score=scores[movie_id], recall_sources=list(ranks[movie_id]),
            recall_ranks=ranks[movie_id]) for index, movie_id in enumerate(ordered, 1)]
        return RecommendationResult(algorithm=Algorithm.rrf, model_version=MODEL_VERSION,
            dataset_version=request.dataset_version, split_version=request.split_version,
            runtime_mode=request.runtime_mode, generated_at=datetime.now(timezone.utc), items=items)
