"""Create the small RRF manifest bound to the existing sealed business data."""

import hashlib
import json
from pathlib import Path


def build(root: Path = Path("models/business")) -> Path:
    source = json.loads((root / "content-genres-v1/manifest.json").read_text(encoding="utf-8"))
    target = root / "rrf-v1"
    target.mkdir(parents=True, exist_ok=True)
    config = {"model_version": "rrf-v1", "k": 60,
              "sources": ["content", "itemcf", "als", "popular"], "candidate_limit": 50}
    artifact = target / "fusion.json"
    artifact.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source.update(algorithm="rrf", model_version="rrf-v1",
                  artifacts={"fusion.json": hashlib.sha256(artifact.read_bytes()).hexdigest()},
                  parameters={"fusion": "reciprocal_rank", "k": config["k"],
                              "sources": config["sources"], "candidate_limit": config["candidate_limit"]},
                  tool_versions={"python": "3.12", "implementation": "cinelab-rrf-v1"})
    manifest = target / "manifest.json"
    manifest.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(build())
