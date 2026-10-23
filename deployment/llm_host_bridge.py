"""Minimal authenticated host bridge for Docker Desktop networks without HTTPS egress.

The key is read from a local ignored file. No credentials or model output are logged.
Only the fixed OpenRouter chat endpoint is reachable through this bridge.
"""

import argparse
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

TARGET = "https://openrouter.ai/api/v1/chat/completions"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18765)
    args = parser.parse_args()
    key = args.key_file.read_text(encoding="utf-8").strip()
    if not key.startswith("sk-or-"):
        raise SystemExit("OpenRouter key file is missing or invalid")
    expected = ("Bearer " + key).encode("ascii")
    opener = build_opener(ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args) -> None:
            pass

        def respond(self, status: int, payload: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/health":
                self.respond(200, b'{"service":"cinelab-llm-bridge-v1"}')
            else:
                self.respond(404, b'{"error":"not found"}')

        def do_POST(self) -> None:
            supplied = self.headers.get("Authorization", "").encode("ascii", "ignore")
            if self.path != "/api/v1/chat/completions" or not hmac.compare_digest(supplied, expected):
                self.respond(403, b'{"error":"forbidden"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 32768:
                self.respond(413, b'{"error":"invalid request size"}')
                return
            body = self.rfile.read(length)
            try:
                outgoing = Request(TARGET, body,
                                   {"Authorization": "Bearer " + key,
                                    "Content-Type": "application/json"}, method="POST")
                with opener.open(outgoing, timeout=45) as response:
                    result = response.read(1048576)
                    self.respond(response.status, result)
            except HTTPError as exc:
                self.respond(exc.code, exc.read(8192))
            except (URLError, TimeoutError):
                self.respond(503, b'{"error":"OpenRouter unavailable"}')

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
