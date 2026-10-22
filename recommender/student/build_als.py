"""Fit explicit-feedback Spark MLlib ALS; business and evaluation never share ratings."""

import argparse
import json
import sys
from pathlib import Path

from recommender.data import DATASET, MANIFEST_SHA, SCHEMA, SPLIT, FrozenData, require, sha256

ROOT = Path(__file__).resolve().parents[2]
MODEL_VERSION = "als-spark-explicit-v1"
RANK, REG_PARAM, MAX_ITER, SEED = 16, 0.12, 8, 42


def fit(mode: str) -> Path:
    from pyspark.ml.recommendation import ALS
    from pyspark.sql import SparkSession
    from pyspark.sql.types import FloatType, IntegerType, LongType, StructField, StructType

    require(mode in {"business", "evaluation"}, "未知ALS训练模式", "DATA_MODE_INVALID")
    data = FrozenData()
    catalog = data.catalog()
    source_name = "business/history_ratings.csv" if mode == "business" else "evaluation/train.csv"
    if mode == "evaluation":
        source = data.checked(source_name, evaluation=True)
    else:
        source = data.package / source_name
        expected = data.manifest["files"][source_name]
        require(source.is_file() and source.stat().st_size == expected["bytes"] and
                sha256(source) == expected["sha256"], "业务训练评分摘要不符", "DATA_IDENTITY_INVALID")

    spark = (SparkSession.builder.master("local[4]").appName("CineLab-ALS-" + mode)
             .config("spark.ui.enabled", "false").config("spark.sql.shuffle.partitions", "8")
             .config("spark.driver.memory", "3g").getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")
    try:
        schema = StructType([StructField("userId", IntegerType(), False),
                             StructField("movieId", IntegerType(), False),
                             StructField("rating", FloatType(), False),
                             StructField("timestamp", LongType(), False)])
        # On Windows Spark/Hadoop cannot resolve a file URI containing a space.
        # This workstation exposes the same verified workspace through SUBST S:.
        spark_source = source.as_uri()
        if " " in str(source):
            alias = Path("S:/") / source.relative_to(ROOT.parent.parent)
            require(alias.is_file() and sha256(alias) == sha256(source),
                    "含空格的工作目录需用 SUBST S: 映射到相同工作区", "DATA_IDENTITY_INVALID")
            spark_source = alias.as_uri()
        ratings = (spark.read.option("header", "true").option("mode", "FAILFAST")
                   .schema(schema).csv(spark_source).select("userId", "movieId", "rating").cache())
        count = ratings.count()
        require(count == data.manifest["files"][source_name]["records"],
                "ALS训练行数不符", "DATA_IDENTITY_INVALID")
        estimator = ALS(userCol="userId", itemCol="movieId", ratingCol="rating",
                        rank=RANK, regParam=REG_PARAM, maxIter=MAX_ITER,
                        implicitPrefs=False, coldStartStrategy="drop", seed=SEED,
                        numUserBlocks=4, numItemBlocks=4, checkpointInterval=-1)
        model = estimator.fit(ratings)
        users = {str(row.id): [float(value) for value in row.features]
                 for row in model.userFactors.collect()}
        items = {str(row.id): [float(value) for value in row.features]
                 for row in model.itemFactors.collect()}
        require(bool(users) and bool(items) and set(items) <= catalog,
                "ALS因子不在批准目录", "MODEL_BINDING_INVALID")
        spark_version = spark.version
    finally:
        spark.stop()

    directory = ROOT / "models" / mode / MODEL_VERSION
    directory.mkdir(parents=True, exist_ok=True)
    artifact_path = directory / "factors.json"
    artifact_path.write_text(json.dumps({"model_version": MODEL_VERSION, "rank": RANK,
                                         "users": users, "items": items}, separators=(",", ":")), encoding="utf-8")
    manifest = {"algorithm": "als", "model_version": MODEL_VERSION, "runtime_mode": mode,
                "dataset_version": DATASET, "split_version": SPLIT, "schema_version": SCHEMA,
                "manifest_sha256": MANIFEST_SHA,
                "training_files": {source_name: data.manifest["files"][source_name]["sha256"]},
                "feature_files": {"training-catalog.csv": data.manifest["files"]["training-catalog.csv"]["sha256"]},
                "artifacts": {"factors.json": sha256(artifact_path)},
                "parameters": {"rank": RANK, "regParam": REG_PARAM, "maxIter": MAX_ITER,
                               "seed": SEED, "implicitPrefs": False, "coldStartStrategy": "drop"},
                "tool_versions": {"python": ".".join(map(str, sys.version_info[:3])),
                                  "pyspark": spark_version, "implementation": "Spark MLlib ALS"}}
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Built {mode} {MODEL_VERSION} from {count} real ratings: {len(users)} users, {len(items)} films")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["business", "evaluation"], required=True)
    args = parser.parse_args()
    fit(args.mode)
