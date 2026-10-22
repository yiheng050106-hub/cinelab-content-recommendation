import json
import math
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import Field
from sqlalchemy import text

from recommender.contracts import Algorithm, AlgorithmNotImplemented, RecommendationRequest, RecommendationResult, PROVIDERS, recommend
from recommender.data import ContractError
from .config import DATASET, SPLIT
from .errors import APIError
from .schemas import IdPath, Input, identifier
from .security import ActorDependency

router = APIRouter(tags=["学生算法预留边界"])


class RecommendationQuery(Input):
    limit: int = Field(default=10, ge=1, le=50)
    genre: str | None = Field(default=None, min_length=2, max_length=32, pattern=r"^[A-Za-z-]+$")


def invoke(algorithm: Algorithm, kind: str, uid: int, limit: int, genre: str | None = None):
    if genre and algorithm != Algorithm.cold_start:
        raise APIError(400, "INTEREST_ONLY_FOR_COLD_START", "兴趣类型仅用于冷启动推荐")
    request = RecommendationRequest(kind, uid, limit, "business", DATASET, SPLIT,
                                    (genre,) if genre else ())
    try:
        return recommend(algorithm, request)
    except AlgorithmNotImplemented:
        raise APIError(501, "ALGORITHM_NOT_IMPLEMENTED", "此推荐算法留给学生实现", {
            "status": "not_implemented", "algorithm": algorithm.value, "subject_key": kind + ":" + str(uid),
            "dataset_version": DATASET, "split_version": SPLIT, "runtime_mode": "business",
            "model_version": None, "batch_id": None, "items": []}) from None
    except ContractError as exc:
        status = (400 if exc.code in {"COLD_START_REQUIRES_APP", "COLD_START_REQUIRES_ZERO_BEHAVIOR",
                                    "COLD_START_INTEREST_INVALID", "REQUEST_CONTEXT_INVALID"}
                  else 503 if exc.code in {"MODEL_BINDING_INVALID", "DATA_IDENTITY_INVALID", "DATA_MODE_INVALID"} else 500)
        raise APIError(status,
            exc.code, str(exc)) from None


@router.get("/experiments/algorithms")
def algorithms():
    return {"items": [{"algorithm": algorithm.value, "status": "registered" if algorithm in PROVIDERS else "not_implemented"} for algorithm in Algorithm]}


@router.get("/experiments/evaluations")
def evaluations():
    # Only the offline aggregate is mounted in the business API. The API never
    # opens evaluation ratings or computes metrics from business history.
    path = Path("models/business/evaluation-summary.json")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["status"] == "completed" and report["partition"] == "validation"
        assert report["dataset_version"] == DATASET and report["split_version"] == SPLIT
        assert report["user_count"] == 4209 and report["positive_threshold"] == 4.0
        assert report["top_k"] == 10 and len(report["task_sha256"]) == 64
        assert {row["algorithm"] for row in report["metrics"]} == {"content", "itemcf", "als", "popular"}
        assert len(report["metrics"]) == 4
        assert all(0 <= row[key] <= 1 and math.isfinite(row[key])
                   for row in report["metrics"] for key in ("precision_at_10", "recall_at_10"))
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise APIError(503, "EVALUATION_REPORT_UNAVAILABLE", "离线评价报告缺失或不符合固定验证任务") from None
    return report


@router.get("/me/recommendations/{algorithm}", response_model=RecommendationResult)
def my_recommendations(algorithm: Algorithm, actor: ActorDependency, query: Annotated[RecommendationQuery, Query()]):
    return invoke(algorithm, "app", actor.account_id, query.limit, query.genre)


@router.get("/demo/history-users/{ml_user_id}/recommendations/{algorithm}", response_model=RecommendationResult)
def history_recommendations(ml_user_id: IdPath, algorithm: Algorithm, request: Request,
                            query: Annotated[RecommendationQuery, Query()]):
    uid = identifier(ml_user_id)
    with request.app.state.db.connection() as conn:
        if conn.execute(text("SELECT ml_user_id FROM history_users WHERE ml_user_id=:id"), {"id": uid}).first() is None:
            raise APIError(404, "HISTORY_USER_NOT_FOUND", "历史匿名用户不存在")
    return invoke(algorithm, "ml", uid, query.limit, query.genre)
