#!/usr/bin/env python3
"""Tiny deterministic OpenAI-compatible endpoint for infrastructure smoke tests.

This is deliberately not a model-quality benchmark. It removes API credentials
as a prerequisite while exercising the unmodified upstream provider interface,
prompt logging, program parsing, solver evaluation, database, and checkpointing.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROGRAM = """```python
import numpy as np

USED_FEATURES = [9, 43]
PARAMS = [0.5, 0.5]
BOUNDS = [[0.0, 1.0], [0.0, 1.0]]

def score_function(variable_features, params):
    fractionality = variable_features[:, 9]
    pseudocost_product = variable_features[:, 43]
    return params[0] * (4.0 * fractionality * (1.0 - fractionality)) + params[1] * pseudocost_product
```"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/").endswith("models"):
            self._send({"object": "list", "data": [{"id": "phase-minus1-mock", "object": "model"}]})
        else:
            self._send({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            json.loads(self.rfile.read(length))
        now = int(time.time())
        self._send(
            {
                "id": f"phase-minus1-{now}",
                "object": "chat.completion",
                "created": now,
                "model": "phase-minus1-mock",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": PROGRAM},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18080, type=int)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

