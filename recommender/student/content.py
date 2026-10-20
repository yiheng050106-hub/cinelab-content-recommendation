"""Personalized genre Content recommendation for business users."""

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from recommender.contracts import Algorithm, RecommendationItem, RecommendationRequest, RecommendationResult
from recommender.data import ContractError, require


MODEL_VERSION = "content-genres-v1"


def _unit_vector(genres: list[str], idf: dict[str, float]) -> dict[str, float]:
    magnitude = math.sqrt(sum(idf[genre] ** 2 for genre in genres))
    return {genre: idf[genre] / magnitude for genre in genres} if magnitude else {}


@lru_cache(maxsize=1)
def _model(path: str) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    try:
        artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        require(artifact["model_version"] == MODEL_VERSION, "内容模型版本不符", "MODEL_BINDING_INVALID")
        idf = artifact["idf"]
        vectors = {movie_id: _unit_vector(genres, idf)
                   for movie_id, (genres, _) in artifact["movies"].items()}
        quality = {movie_id: float(record[1]) for movie_id, record in artifact["movies"].items()}
        return vectors, quality
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ContractError("MODEL_BINDING_INVALID", "内容模型工件无法读取") from exc


class ContentProvider:
    def __init__(self, model_manifest_path: str | Path):
        self.model_manifest_path = Path(model_manifest_path)

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        require(request.runtime_mode == "business", "业务内容模型不用于离线评价", "DATA_MODE_INVALID")
        from recommender.business import read_history

        vectors, quality = _model(str(self.model_manifest_path.parent / "features.json"))
        history = read_history(request)
        seen = {entry.movie_id for entry in history.ratings}
        favorites = set(history.favorite_movie_ids)
        profile: dict[str, float] = {}

        def add_movie(movie_id: str, weight: float) -> None:
            for genre, value in vectors.get(movie_id, {}).items():
                profile[genre] = profile.get(genre, 0.0) + weight * value

        positive_count = 0
        for entry in history.ratings:
            rating = float(entry.rating)
            weight = max(0.0, rating - 3.0) - 0.5 * max(0.0, 3.0 - rating)
            if weight > 0:
                positive_count += 1
            if weight:
                add_movie(entry.movie_id, weight)
        # A favorite is a weak implicit signal, not a fabricated high rating.
        for movie_id in favorites - seen:
            add_movie(movie_id, 0.8)
        if positive_count == 0 and not favorites:
            return self._result(request, [])
        norm = math.sqrt(sum(value * value for value in profile.values()))
        if norm == 0:
            return self._result(request, [])
        profile = {genre: value / norm for genre, value in profile.items()}

        scored = []
        for movie_id, vector in vectors.items():
            if movie_id in seen or movie_id in favorites or not vector:
                continue
            similarity = sum(profile.get(genre, 0.0) * weight for genre, weight in vector.items())
            if similarity <= 0:
                continue
            score = similarity + 0.08 * (quality[movie_id] - 3.0) / 2.0
            scored.append((movie_id, round(score, 8)))
        scored.sort(key=lambda pair: (-pair[1], int(pair[0])))
        items = [RecommendationItem(movie_id=movie_id, rank=rank,
                                    algorithm=Algorithm.content, model_version=MODEL_VERSION,
                                    score=score, recall_sources=["genre_cosine"])
                 for rank, (movie_id, score) in enumerate(scored[:request.limit], 1)]
        return self._result(request, items)

    @staticmethod
    def _result(request: RecommendationRequest, items: list[RecommendationItem]) -> RecommendationResult:
        return RecommendationResult(algorithm=Algorithm.content, model_version=MODEL_VERSION,
                                    dataset_version=request.dataset_version, split_version=request.split_version,
                                    runtime_mode=request.runtime_mode,
                                    generated_at=datetime.now(timezone.utc), items=items)
