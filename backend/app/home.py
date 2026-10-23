"""Current-account home recommendations with auditable behavior context."""

from collections import defaultdict
from hashlib import sha256
import json

from fastapi import APIRouter, Request
from sqlalchemy import bindparam, text

from recommender.contracts import Algorithm
from .catalog import public_row
from .experiments import invoke
from .security import ActorDependency, public_account

router = APIRouter(tags=["首页个性化推荐"])


def _behavior(request: Request, account_id: int) -> dict:
    with request.app.state.db.connection() as conn:
        ratings = conn.execute(text(
            "SELECT r.movie_id,r.rating,r.updated_at AS changed_at,m.movielens_title,m.genres "
            "FROM account_ratings r JOIN movies m ON m.movie_id=r.movie_id "
            "WHERE r.account_id=:uid ORDER BY r.movie_id"), {"uid": account_id}).mappings().all()
        favorites = conn.execute(text(
            "SELECT f.movie_id,f.created_at AS changed_at,m.movielens_title,m.genres "
            "FROM account_favorites f JOIN movies m ON m.movie_id=f.movie_id "
            "WHERE f.account_id=:uid ORDER BY f.movie_id"), {"uid": account_id}).mappings().all()

    rated_ids = {row["movie_id"] for row in ratings}
    weights: dict[str, float] = defaultdict(float)
    for row in ratings:
        weight = max(0.0, float(row["rating"]) - 3.0)
        for genre in row["genres"].split("|"):
            if genre != "(no genres listed)":
                weights[genre] += weight
    for row in favorites:
        if row["movie_id"] not in rated_ids:
            for genre in row["genres"].split("|"):
                if genre != "(no genres listed)":
                    weights[genre] += 0.8

    records = ([{"kind": "rating", "movie_id": str(row["movie_id"]),
                 "title": row["movielens_title"], "rating": f'{row["rating"]:.1f}',
                 "at": row["changed_at"].isoformat(timespec="microseconds") + "Z"}
                for row in ratings] +
               [{"kind": "favorite", "movie_id": str(row["movie_id"]),
                 "title": row["movielens_title"], "rating": None,
                 "at": row["changed_at"].isoformat(timespec="microseconds") + "Z"}
                for row in favorites])
    fingerprint = sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return {"ratings": len(ratings), "favorites": len(favorites),
            "positive_ratings": sum(float(row["rating"]) > 3 for row in ratings),
            "version": fingerprint,
            "latest": max(records, key=lambda record: record["at"]) if records else None,
            "top_genres": [{"genre": genre, "weight": round(weight, 2)} for genre, weight in
                           sorted(weights.items(), key=lambda entry: (-entry[1], entry[0]))[:4] if weight > 0]}


@router.get("/me/recommendations/home")
def home_recommendations(request: Request, actor: ActorDependency):
    behavior = _behavior(request, actor.account_id)
    if behavior["ratings"] == 0 and behavior["favorites"] == 0:
        algorithm = Algorithm.cold_start
        reason = "暂无评分和收藏，使用真实历史评分形成的冷启动热门榜。"
    elif behavior["positive_ratings"] or behavior["favorites"]:
        algorithm = Algorithm.content
        reason = "根据当前账号的评分和收藏实时计算电影类型偏好。"
    else:
        algorithm = Algorithm.popular
        reason = "已有评分但缺少正向偏好，使用热门榜并跳过已评电影。"

    result = invoke(algorithm, "app", actor.account_id, 10)
    if not result.items and algorithm == Algorithm.content:
        algorithm = Algorithm.itemcf
        result = invoke(algorithm, "app", actor.account_id, 10)
        reason = "类型候选不足，改用历史评分驱动的相似电影推荐。"
    if not result.items and algorithm == Algorithm.itemcf:
        algorithm = Algorithm.popular
        result = invoke(algorithm, "app", actor.account_id, 10)
        reason = "相似电影候选不足，使用热门榜并跳过已评分和收藏电影。"

    ids = [int(item.movie_id) for item in result.items]
    movies = []
    if ids:
        query = text("SELECT movie_id,movielens_title,title_zh,genres,release_year,poster_path "
                     "FROM movies WHERE movie_id IN :ids").bindparams(bindparam("ids", expanding=True))
        with request.app.state.db.connection() as conn:
            by_id = {int(row["movie_id"]): public_row(row)
                     for row in conn.execute(query, {"ids": ids}).mappings()}
        movies = [by_id[mid] for mid in ids]

    return {"account": public_account(actor), "behavior": behavior,
            "strategy": {"algorithm": algorithm.value, "reason": reason},
            "recommendation": result.model_dump(mode="json"), "movies": movies}
