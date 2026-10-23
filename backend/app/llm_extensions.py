"""S2/S4: model-assisted discovery and evidence-grounded explanations.

The model only interprets a request or explains verified evidence. Movie IDs,
ratings and recommendation positions always come from CineLab data and providers.
"""

import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request as HTTPRequest, build_opener

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import text

from recommender.contracts import Algorithm
from .catalog import get_genres, public_row
from .errors import APIError
from .experiments import invoke
from .schemas import Input

router = APIRouter(prefix="/experiments/llm", tags=["大模型扩展"])


class SearchInput(Input):
    prompt: str = Field(min_length=4, max_length=300)


class ExplainInput(Input):
    ml_user_id: int = Field(ge=1, le=5000)
    algorithm: Algorithm
    movie_id: int | None = Field(default=None, ge=1)


def _complete(request: Request, system: str, user: str) -> tuple[str, str]:
    settings = request.app.state.settings
    path = Path(settings.llm_key_file) if settings.llm_key_file else None
    if not path or not path.is_file():
        raise APIError(503, "LLM_KEY_UNAVAILABLE", "大模型密钥未在本机配置")
    key = path.read_text(encoding="utf-8").strip()
    if not key.startswith("sk-or-"):
        raise APIError(503, "LLM_KEY_INVALID", "大模型密钥配置无效")
    data = json.dumps({"model": settings.llm_model, "temperature": 0.2,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}, ensure_ascii=False).encode("utf-8")
    outgoing = HTTPRequest(settings.llm_endpoint, data=data,
                           headers={"Authorization": "Bearer " + key,
                                    "Content-Type": "application/json"}, method="POST")
    try:
        # The course runtime may inherit an invalid host proxy. Use the direct
        # HTTPS route that was verified for this deployment.
        with build_opener(ProxyHandler({})).open(outgoing, timeout=45) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 429:
            raise APIError(429, "LLM_RATE_LIMIT", "免费模型额度或速率已达到上限，请稍后再试") from None
        raise APIError(503, "LLM_PROVIDER_ERROR", f"大模型服务返回 HTTP {exc.code}") from None
    except (URLError, TimeoutError, ValueError):
        raise APIError(503, "LLM_PROVIDER_UNAVAILABLE", "暂时无法连接大模型服务") from None
    try:
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty model response")
        return content.strip(), str(result.get("model", settings.llm_model))
    except (KeyError, IndexError, TypeError, ValueError):
        raise APIError(502, "LLM_EMPTY_RESPONSE", "大模型没有返回可用文本") from None


@router.post("/search")
def natural_search(body: SearchInput, request: Request):
    with request.app.state.db.connection() as conn:
        valid_genres = get_genres(conn)
    genre = keyword = None
    for attempt in range(2):
        raw, model = _complete(request,
            "你是电影目录检索意图解析器。只输出一个 JSON 对象，字段 genre 和 keyword。"
            "genre 必须是提供的英文类型之一，无法确定则 null。keyword 仅当用户明确提到电影片名时填写片名关键词，否则 null。"
            "不得编造电影或返回电影列表。",
            json.dumps({"user_request": body.prompt, "allowed_genres": valid_genres,
                        "format_example": {"genre": "Comedy", "keyword": None},
                        "attempt": attempt + 1}, ensure_ascii=False))
        match = re.search(r"\{.*?\}", raw, re.S)
        try:
            intent = json.loads(match.group(0)) if match else {}
            genre = intent.get("genre")
            keyword = intent.get("keyword")
        except (ValueError, TypeError, AttributeError):
            genre = keyword = None
        if genre not in valid_genres:
            genre = next((g for g in valid_genres if re.search(r"(?<![A-Za-z])" + re.escape(g) + r"(?![A-Za-z])", raw, re.I)), None)
        if not isinstance(keyword, str) or len(keyword) > 64:
            keyword = None
        if genre or keyword:
            break
    if not genre and not keyword:
        raise APIError(502, "LLM_INTENT_INVALID", "大模型未能识别可检索的电影条件，请具体说明类型或片名") from None

    clauses, values = [], {}
    if genre:
        clauses.append("CONCAT('|',m.genres,'|') LIKE :genre")
        values["genre"] = "%|" + genre + "|%"
    if keyword:
        clauses.append("(LOWER(m.movielens_title) LIKE LOWER(:keyword) OR LOWER(COALESCE(m.title_zh,'')) LIKE LOWER(:keyword))")
        values["keyword"] = "%" + keyword.replace("%", "").replace("_", "") + "%"
    query = ("SELECT m.movie_id,m.movielens_title,m.title_zh,m.genres,m.release_year,m.poster_path,"
             "COUNT(r.movie_id) AS rating_count FROM movies m "
             "LEFT JOIN history_ratings r ON r.movie_id=m.movie_id WHERE " + " AND ".join(clauses) +
             " GROUP BY m.movie_id,m.movielens_title,m.title_zh,m.genres,m.release_year,m.poster_path "
             "ORDER BY rating_count DESC,m.movie_id LIMIT 10")
    with request.app.state.db.connection() as conn:
        movies = [public_row(row) for row in conn.execute(text(query), values).mappings()]
    return {"status": "ready", "model": model, "input": body.prompt,
            "intent": {"genre": genre, "keyword": keyword}, "source": "course_movies_and_history_ratings",
            "items": movies}


@router.post("/explain")
def explain_recommendation(body: ExplainInput, request: Request):
    if body.algorithm not in {Algorithm.content, Algorithm.itemcf, Algorithm.als, Algorithm.rrf}:
        raise APIError(422, "EXPLANATION_ALGORITHM_INVALID", "请选择 Content、ItemCF、ALS 或 RRF")
    with request.app.state.db.connection() as conn:
        found = conn.execute(text("SELECT 1 FROM history_users WHERE ml_user_id=:uid"),
                             {"uid": body.ml_user_id}).first()
    if not found:
        raise APIError(404, "HISTORY_USER_NOT_FOUND", "历史用户不存在")
    result = invoke(body.algorithm, "ml", body.ml_user_id, 10)
    item = next((i for i in result.items if body.movie_id is None or int(i.movie_id) == body.movie_id), None)
    if item is None:
        raise APIError(422, "MOVIE_NOT_RECOMMENDED", "该电影不在当前用户的这份 Top-10 推荐中")
    with request.app.state.db.connection() as conn:
        target = conn.execute(text("SELECT movie_id,movielens_title,title_zh,genres,release_year "
                                   "FROM movies WHERE movie_id=:mid"), {"mid": int(item.movie_id)}).mappings().one()
        liked = conn.execute(text("SELECT r.movie_id,r.rating,m.movielens_title,m.genres "
                                  "FROM history_ratings r JOIN movies m ON m.movie_id=r.movie_id "
                                  "WHERE r.ml_user_id=:uid AND r.rating>=4 "
                                  "ORDER BY r.rating DESC,r.timestamp_utc DESC,r.movie_id LIMIT 6"),
                             {"uid": body.ml_user_id}).mappings().all()
    evidence = {"user_id": "ml" + str(body.ml_user_id), "algorithm": body.algorithm.value,
                "recommendation": {"rank": item.rank, "score": item.score,
                    "recall_sources": item.recall_sources, "recall_ranks": item.recall_ranks,
                    "movie": public_row(target)},
                "liked_history": [public_row(row) for row in liked]}
    if not evidence["liked_history"]:
        raise APIError(422, "HISTORY_TOO_SPARSE", "该用户没有可用于解释的高分历史")
    # Ask the model to choose evidence, then render only verified database facts.
    # Free models can otherwise invent a translated film title or plot detail.
    candidate_ids = {int(movie["movie_id"]): movie for movie in evidence["liked_history"]}
    choice = None
    model = request.app.state.settings.llm_model
    for attempt in range(2):
        raw, model = _complete(request,
            "你是电影推荐证据选择器。只输出一个 JSON 对象："
            '{"history_movie_id":整数}。必须从 liked_history 选一部最能解释推荐电影的高分历史电影。'
            "优先选与推荐电影共享类型的电影。不得输出电影名、解释文字或其他字段。",
            json.dumps({"evidence": evidence, "attempt": attempt + 1}, ensure_ascii=False))
        match = re.search(r"\{.*?\}", raw, re.S)
        try:
            selected_id = int(json.loads(match.group(0))["history_movie_id"]) if match else None
        except (ValueError, TypeError, KeyError):
            selected_id = None
        if selected_id in candidate_ids:
            choice = candidate_ids[selected_id]
            break
    if choice is None:
        raise APIError(502, "LLM_EVIDENCE_INVALID", "模型未能选择有效历史证据，请重新生成")
    target_genres = set(evidence["recommendation"]["movie"]["genres"])
    shared = sorted(target_genres.intersection(choice["genres"]))
    title = evidence["recommendation"]["movie"]["movielens_title"]
    explanation = (f'你曾给《{choice["movielens_title"]}》打 {choice["rating"]} 分。'
                   + (f'它与《{title}》同属 {"、".join(shared)} 类型。' if shared else
                      f'《{title}》与你的历史评分共同参与个性化排序。')
                   + f'{body.algorithm.value.upper()} 根据你的历史评分生成候选，将这部电影排在第 {item.rank} 名。')
    return {"status": "ready", "model": model, "explanation": explanation,
            "evidence": evidence}
