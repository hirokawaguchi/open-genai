#!/usr/bin/env python3
"""SD API の開発用モックサーバ（A1111 互換 / FastSD 互換の両対応）。

ホストに実 SD が無い場合の動作検証用。SD_BACKEND=a1111 / fastsd どちらの
バックエンドでも疎通確認できるよう、両方のエンドポイントを実装する。

A1111 互換:
  GET  /sdapi/v1/sd-models
  POST /sdapi/v1/txt2img, /sdapi/v1/img2img   -> {"images": [b64], ...}
FastSD 互換:
  GET  /api/models, /api/info
  POST /api/generate                          -> {"images": [b64], "latency": .., "error": ""}

使い方:
  python3 scripts/mock-sd-server.py            # a1111 検証（:7860）
  python3 scripts/mock-sd-server.py --port 8000  # fastsd 検証（:8000）
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
        # FastSD 互換
        if self.path == "/api/models":
            self._send_json(200, {"lcm_models": ["mock-lcm"], "openvino_models": [], "stable_diffusion": [], "lcm_lora_models": []})
            return
        if self.path == "/api/info":
            self._send_json(200, {"device_type": "cpu", "device_name": "mock", "os": "mock"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        a1111 = self.path in ("/sdapi/v1/txt2img", "/sdapi/v1/img2img")
        fastsd = self.path == "/api/generate"
        if not (a1111 or fastsd):
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
        print(f"[mock-sd] generate ({self.path}): prompt={prompt!r}")
        if fastsd:
            # FastSD の StableDiffusionResponse 形
            self._send_json(200, {"images": [_MOCK_PNG_B64], "latency": 0.01, "error": ""})
        else:
            self._send_json(200, {"images": [_MOCK_PNG_B64], "info": json.dumps({"seed": 1})})


def main() -> None:
    parser = argparse.ArgumentParser(description="A1111 compatible mock SD server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[mock-sd] listening on http://{args.host}:{args.port}")
    print("[mock-sd] a1111: GET /sdapi/v1/sd-models  POST /sdapi/v1/txt2img|img2img")
    print("[mock-sd] fastsd: GET /api/models|/api/info  POST /api/generate")
    server.serve_forever()


if __name__ == "__main__":
    main()
