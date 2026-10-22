"""Kafka feedback producer and replaying consumer for account genre interests."""

import json
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from uuid import uuid4

from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

log = logging.getLogger("course_api.feedback")
TOPIC = "cinelab-account-feedback-v1"


class FeedbackStream:
    def __init__(self, bootstrap_servers: str):
        self.bootstrap_servers = bootstrap_servers
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.consumer_online = False
        self.producer_online = False
        self.error: str | None = None
        self.processed = 0
        self.seen_offsets: set[tuple[int, int]] = set()
        self.states: dict[int, dict[str, dict]] = defaultdict(dict)
        self.recent: dict[int, deque] = defaultdict(lambda: deque(maxlen=5))
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.bootstrap_servers:
            return
        self.thread = threading.Thread(target=self._consume, name="kafka-feedback-consumer", daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)

    def publish(self, account_id: int, movie_id: int, genres: str, rating: float | None,
                favorited: bool, action: str) -> dict:
        if not self.bootstrap_servers:
            return {"status": "disabled"}
        event = {"event_id": uuid4().hex, "account_id": account_id, "movie_id": str(movie_id),
                 "genres": [genre for genre in genres.split("|") if genre != "(no genres listed)"],
                 "rating": rating, "favorited": favorited, "action": action,
                 "occurred_at": datetime.now(timezone.utc).isoformat()}
        producer = None
        try:
            producer = KafkaProducer(bootstrap_servers=self.bootstrap_servers,
                value_serializer=lambda value: json.dumps(value, ensure_ascii=False).encode("utf-8"),
                acks="all", retries=1, request_timeout_ms=5000, api_version_auto_timeout_ms=3000)
            metadata = producer.send(TOPIC, key=str(account_id).encode(), value=event).get(timeout=8)
            with self.lock:
                self.producer_online = True
                self.error = None
            return {"status": "delivered", "event_id": event["event_id"], "topic": TOPIC,
                    "partition": metadata.partition, "offset": metadata.offset}
        except (KafkaError, OSError, TimeoutError) as exc:
            log.warning("Kafka feedback publish failed: %s", type(exc).__name__)
            with self.lock:
                self.producer_online = False
                self.error = type(exc).__name__
            return {"status": "unavailable"}
        finally:
            if producer is not None:
                producer.close(timeout=1)

    def _consume(self) -> None:
        while not self.stop.is_set():
            consumer = None
            try:
                # No committed offset: replay retained events after every API restart.
                consumer = KafkaConsumer(TOPIC, bootstrap_servers=self.bootstrap_servers,
                    group_id=None, auto_offset_reset="earliest", enable_auto_commit=False,
                    value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
                    api_version_auto_timeout_ms=3000, consumer_timeout_ms=1000)
                with self.lock:
                    self.consumer_online = True
                    self.error = None
                while not self.stop.is_set():
                    batches = consumer.poll(timeout_ms=1000, max_records=100)
                    for records in batches.values():
                        for record in records:
                            self._apply(record.value, record.partition, record.offset)
            except (KafkaError, OSError, ValueError, TypeError) as exc:
                log.warning("Kafka feedback consumer unavailable: %s", type(exc).__name__)
                with self.lock:
                    self.consumer_online = False
                    self.error = type(exc).__name__
                self.stop.wait(3)
            finally:
                if consumer is not None:
                    consumer.close()

    def _apply(self, event: dict, partition: int, offset: int) -> None:
        try:
            uid = int(event["account_id"])
            movie_id = str(int(event["movie_id"]))
            genres = tuple(genre for genre in event["genres"] if isinstance(genre, str))
            rating = event["rating"]
            if rating is not None:
                rating = float(rating)
            favorited = bool(event["favorited"])
        except (KeyError, ValueError, TypeError):
            return
        with self.lock:
            if (partition, offset) in self.seen_offsets:
                return
            self.seen_offsets.add((partition, offset))
            self.states[uid][movie_id] = {"genres": genres, "rating": rating, "favorited": favorited}
            self.recent[uid].appendleft({"event_id": event.get("event_id"), "movie_id": movie_id,
                "action": event.get("action"), "rating": rating, "favorited": favorited,
                "genres": genres, "partition": partition, "offset": offset,
                "occurred_at": event.get("occurred_at")})
            self.processed += 1

    def snapshot(self, account_id: int) -> dict:
        with self.lock:
            states = list(self.states.get(account_id, {}).values())
            weights: dict[str, float] = defaultdict(float)
            for state in states:
                rating = state["rating"]
                weight = (max(0.0, rating - 3.0) if rating is not None else 0.0)
                if state["favorited"] and (rating is None or rating <= 3.0):
                    weight += 0.8
                for genre in state["genres"]:
                    weights[genre] += weight
            return {"status": "connected" if self.consumer_online else "unavailable",
                "topic": TOPIC, "account_id": str(account_id),
                "processed_events": self.processed,
                "account_events": len(self.recent.get(account_id, ())),
                "rated_movies": sum(state["rating"] is not None for state in states),
                "favorite_movies": sum(state["favorited"] for state in states),
                "interests": [{"genre": genre, "weight": round(weight, 2)}
                    for genre, weight in sorted(weights.items(), key=lambda pair: (-pair[1], pair[0]))],
                "recent_events": list(self.recent.get(account_id, ())), "error": self.error}
