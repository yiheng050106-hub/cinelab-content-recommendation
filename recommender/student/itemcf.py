"""Item-item collaborative filtering from historical positive co-ratings."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from recommender.contracts import Algorithm, RecommendationItem, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require

MODEL_VERSION = "itemcf-cobehavior-v1"


@lru_cache(maxsize=1)
def _neighbors(path: str) -> dict[str, list[list]]:
    try:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        require(artifact["model_version"] == MODEL_VERSION, "ItemCF模型版本不符", "MODEL_BINDING_INVALID")
        return artifact["neighbors"]
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ContractError("MODEL_BINDING_INVALID", "ItemCF模型工件无法读取") from exc


class ItemCFProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        from recommender.business import read_history

        require(request.runtime_mode == "business", "ItemCF模型仅用于业务模式", "DATA_MODE_INVALID")
        neighbors = _neighbors(str(self.model_manifest_path.parent / "model.json"))
        history = read_history(request)
        rated = {entry.movie_id for entry in history.ratings}
        seen = rated | set(history.favorite_movie_ids)
        scores: dict[str, float] = defaultdict(float)

        for entry in history.ratings:
            weight = max(0.0, float(entry.rating) - 3.0)
            if weight == 0:
                continue
            for candidate, similarity in neighbors.get(entry.movie_id, ()):
                candidate_id = str(candidate)
                if candidate_id not in seen:
                    scores[candidate_id] += weight * float(similarity)
        for movie_id in history.favorite_movie_ids:
            if movie_id in rated:
                continue
            for candidate, similarity in neighbors.get(movie_id, ()):
                candidate_id = str(candidate)
                if candidate_id not in seen:
                    scores[candidate_id] += 0.8 * float(similarity)

        ranked = sorted(((movie_id, score) for movie_id, score in scores.items() if score > 0),
                        key=lambda pair: (-pair[1], int(pair[0])))[:request.limit]
        items = [RecommendationItem(movie_id=movie_id, rank=rank, algorithm=Algorithm.itemcf,
                                    model_version=MODEL_VERSION, score=round(score, 8),
                                    recall_sources=["positive_rating_item_neighbors"])
                 for rank, (movie_id, score) in enumerate(ranked, 1)]
        return RecommendationResult(algorithm=Algorithm.itemcf, model_version=MODEL_VERSION,
                                    dataset_version=request.dataset_version,
                                    split_version=request.split_version, runtime_mode=request.runtime_mode,
                                    generated_at=datetime.now(timezone.utc), items=items)
