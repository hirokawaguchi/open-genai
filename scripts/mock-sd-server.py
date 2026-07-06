#!/usr/bin/env python3
"""A1111 互換 SD API の開発用モックサーバ。

ホストに Stable Diffusion WebUI が無い場合の動作検証用。
`/sdapi/v1/sd-models` と `/sdapi/v1/txt2img` のみ実装する。

使い方:
  python3 scripts/mock-sd-server.py
  python3 scripts/mock-sd-server.py --port 7860
"""

from __future__ import annotations

import argparse
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 64x64 の単色 PNG（赤）— 実 SD 不要でパイプライン検証可能
_MOCK_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAI0lEQVR4nO3BAQ0AAADCoPdPbQ43o"
    "AAAAAAAAAAAAPgzhAAE0qQAAAABJRU5ErkJggg=="
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[mock-sd] {self.address_string()} - {fmt % args}")

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/sdapi/v1/sd-models":
            self._send_json(200, [{"title": "mock-model", "model_name": "mock.safetensors"}])
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path not in ("/sdapi/v1/txt2img", "/sdapi/v1/img2img"):
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
            return

        prompt = payload.get("prompt", "")
        print(f"[mock-sd] generate: prompt={prompt!r}")
        self._send_json(200, {"images": [_MOCK_PNG_B64], "info": json.dumps({"seed": 1})})


def main() -> None:
    parser = argparse.ArgumentParser(description="A1111 compatible mock SD server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[mock-sd] listening on http://{args.host}:{args.port}")
    print("[mock-sd] GET  /sdapi/v1/sd-models")
    print("[mock-sd] POST /sdapi/v1/txt2img")
    server.serve_forever()


if __name__ == "__main__":
    main()
