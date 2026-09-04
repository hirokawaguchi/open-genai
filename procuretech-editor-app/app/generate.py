"""外部「文書生成」API 連携（ヒアリングシート → 章別 Markdown）。

生成ロジック（テンプレート・LLM/Dify 呼び出し等）はソース非公開の別サービスに閉じ込め、
本アプリはその API を「差し替え可能（pluggable）」に呼び出すだけとする。さらに、生成する
文書の「テーマ」ごとに、必要なヒアリングシート（入力 Excel）と呼び出す API を切り替えられる
ようにする。テーマ定義は環境変数 `EDITOR_GENERATE_THEMES`(JSON) で与える（管理者が設定）。

テーマ定義（JSON 配列）の例:

  [
    {
      "id": "procurement_spec",
      "label": "調達仕様書",
      "description": "情報化企画書と全般的事項から調達仕様書の章別 Markdown を生成します。",
      "doc_type": "specification",
      "api_url": "http://procuretech-generate-mock:8016",   // 省略時は EDITOR_GENERATE_URL
      "api_key": "...",                                       // 省略時は EDITOR_GENERATE_API_KEY
      "inputs": [
        {"key": "systemplan", "label": "情報化企画書（systemplan.xlsx）",
         "marker": "systemplan", "accept": ".xlsx"},
        {"key": "global", "label": "全般的事項（global.xlsx）",
         "marker": "global", "accept": ".xlsx"}
      ]
    }
  ]

未設定時は、従来どおり `EDITOR_GENERATE_URL` を用いる単一テーマ（調達仕様書）を既定で用いる。

契約（Nextcloud 非依存・結果は zip で受け取る）:

- POST `{base_url}/generate`   multipart: 各入力(key=ファイル) / form: username, doc_type, options
- GET  `{base_url}/status/{request_id}`   -> {status, progress, error?}
- GET  `{base_url}/result/{request_id}`   -> application/zip
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

EDITOR_GENERATE_URL = os.environ.get("EDITOR_GENERATE_URL", "").rstrip("/")
EDITOR_GENERATE_API_KEY = os.environ.get("EDITOR_GENERATE_API_KEY", "")
TIMEOUT = float(os.environ.get("EDITOR_GENERATE_TIMEOUT", "180"))
DEFAULT_DOC_TYPE = os.environ.get("EDITOR_GENERATE_DOC_TYPE", "specification")

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class GenerateError(RuntimeError):
    """利用者に提示してよい生成エラー。"""


# --- テーマ定義 ---------------------------------------------------------------


def _default_theme() -> dict[str, Any]:
    return {
        "id": "procurement_spec",
        "label": "調達仕様書",
        "description": (
            "情報化企画書（systemplan.xlsx）と全般的事項（global.xlsx）から"
            "調達仕様書の章別 Markdown を生成します。"
        ),
        "doc_type": DEFAULT_DOC_TYPE,
        # api_url / api_key は未指定 → EDITOR_GENERATE_URL / EDITOR_GENERATE_API_KEY を使う
        "inputs": [
            {
                "key": "systemplan",
                "label": "情報化企画書（systemplan.xlsx）",
                "marker": "systemplan",
                "accept": ".xlsx",
            },
            {
                "key": "global",
                "label": "全般的事項（global.xlsx）",
                "marker": "global",
                "accept": ".xlsx",
            },
        ],
        # 生成される章（section key ↔ 表示名）。合成定義（outputs）はこの key を並べて参照する。
        # 生成サービス（spec-app）の SECTIONS と対応させる。
        "sections": [
            {"key": "background", "label": "背景"},
            {"key": "businessPurpose", "label": "事業の目的・業務・システム化の目標"},
            {"key": "outline", "label": "調達の概要"},
            {"key": "system", "label": "システム要件・機能要件"},
            {"key": "consignmentOperation", "label": "委託業務・運用"},
            {"key": "project", "label": "プロジェクト管理"},
            {"key": "proposal", "label": "提案・見積に関する事項"},
            {"key": "other", "label": "その他"},
            {"key": "rfi", "label": "情報提供依頼（RFI）"},
            {"key": "quotation", "label": "見積費用総括表（Excel）"},
            {"key": "primaryexam", "label": "プロポーザル一次審査表（Excel）"},
        ],
        # 合成（Word/Excel 出力）の既定定義。
        # - kind=markdown: section key を順序付きで並べ、Word(.docx) に合成する。
        # - kind=excel: 生成時に作られる単一 Excel ファイル（section key で参照）をそのまま出力する。
        # プロジェクト側で並べ替え・ON/OFF・出力追加の上書きが可能。
        "outputs": [
            {
                "id": "specification",
                "name": "調達仕様書",
                "kind": "markdown",
                "sections": [
                    "background",
                    "businessPurpose",
                    "outline",
                    "system",
                    "consignmentOperation",
                    "project",
                    "proposal",
                    "other",
                ],
            },
            {"id": "rfi", "name": "RFI", "kind": "markdown", "sections": ["rfi"]},
            {
                "id": "quotation",
                "name": "見積費用総括表",
                "kind": "excel",
                "sections": ["quotation"],
            },
            {
                "id": "primaryexam",
                "name": "プロポーザル一次審査表",
                "kind": "excel",
                "sections": ["primaryexam"],
            },
        ],
    }


def _load_themes() -> list[dict[str, Any]]:
    raw = os.environ.get("EDITOR_GENERATE_THEMES", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list) and data:
            return [t for t in data if isinstance(t, dict) and t.get("id")]
    return [_default_theme()]


THEMES: list[dict[str, Any]] = _load_themes()


def get_theme(theme_id: str | None) -> dict[str, Any] | None:
    """テーマ id からテーマ定義を返す。未指定なら先頭テーマ。見つからなければ None。"""
    if not theme_id:
        return THEMES[0] if THEMES else None
    for t in THEMES:
        if t.get("id") == theme_id:
            return t
    return None


def theme_base_url(theme: dict[str, Any]) -> str:
    """テーマの生成 API ベース URL（未指定なら共通 EDITOR_GENERATE_URL）。"""
    return str(theme.get("api_url") or EDITOR_GENERATE_URL or "").rstrip("/")


def theme_api_key(theme: dict[str, Any]) -> str:
    return str(theme.get("api_key") or EDITOR_GENERATE_API_KEY or "")


def theme_sections(theme: dict[str, Any]) -> list[dict[str, Any]]:
    """テーマの section カタログ（key ↔ label）。"""
    out: list[dict[str, Any]] = []
    for s in theme.get("sections", []) or []:
        if isinstance(s, dict) and s.get("key"):
            out.append({"key": s.get("key"), "label": s.get("label", s.get("key"))})
    return out


def theme_outputs(theme: dict[str, Any]) -> list[dict[str, Any]]:
    """テーマの既定合成定義（出力ファイル毎の順序付き section key リスト）。"""
    out: list[dict[str, Any]] = []
    for o in theme.get("outputs", []) or []:
        if not isinstance(o, dict) or not o.get("id"):
            continue
        out.append(
            {
                "id": o.get("id"),
                "name": o.get("name", o.get("id")),
                "kind": o.get("kind", "markdown"),
                "sections": [str(k) for k in (o.get("sections") or [])],
            }
        )
    return out


def public_themes() -> list[dict[str, Any]]:
    """フロントへ返すテーマ一覧（api_url / api_key 等の秘匿情報は含めない）。"""
    out: list[dict[str, Any]] = []
    for t in THEMES:
        out.append(
            {
                "id": t.get("id"),
                "label": t.get("label", t.get("id")),
                "description": t.get("description", ""),
                "doc_type": t.get("doc_type", DEFAULT_DOC_TYPE),
                "configured": bool(theme_base_url(t)),
                "inputs": [
                    {
                        "key": i.get("key"),
                        "label": i.get("label", i.get("key")),
                        "marker": i.get("marker"),
                        "accept": i.get("accept", ".xlsx"),
                    }
                    for i in t.get("inputs", [])
                    if i.get("key")
                ],
                "sections": theme_sections(t),
                "outputs": theme_outputs(t),
            }
        )
    return out


def is_configured() -> bool:
    """少なくとも 1 つのテーマで生成 API が解決できるか。"""
    return any(theme_base_url(t) for t in THEMES)


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key} if api_key else {}


# --- API 呼び出し -------------------------------------------------------------


async def start_generation(
    files: dict[str, bytes],
    *,
    base_url: str,
    api_key: str = "",
    username: str,
    doc_type: str | None = None,
    options: dict | None = None,
) -> dict:
    """入力ファイル群を送信して生成を開始し、応答 JSON（request_id 等）を返す。"""
    if not base_url:
        raise GenerateError("文書生成 API が未設定です（EDITOR_GENERATE_URL / テーマ api_url）。")
    if not files:
        raise GenerateError("入力ファイルがありません。")
    data = {"username": username or "user", "doc_type": doc_type or DEFAULT_DOC_TYPE}
    if options:
        data["options"] = json.dumps(options, ensure_ascii=False)
    multipart = {k: (f"{k}.xlsx", v, XLSX_MIME) for k, v in files.items()}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.post(
                f"{base_url}/generate",
                files=multipart,
                data=data,
                headers=_headers(api_key),
            )
        except httpx.HTTPError as e:
            raise GenerateError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code not in (200, 201, 202):
        try:
            msg = res.json().get("error") or "生成 API へのリクエストに失敗しました"
        except Exception:  # noqa: BLE001
            msg = "生成 API へのリクエストに失敗しました"
        raise GenerateError(msg)
    return res.json()


async def get_status(request_id: str, *, base_url: str, api_key: str = "") -> dict:
    """生成ステータスを取得して JSON を返す。"""
    if not base_url:
        raise GenerateError("文書生成 API が未設定です。")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.get(
                f"{base_url}/status/{request_id}", headers=_headers(api_key)
            )
        except httpx.HTTPError as e:
            raise GenerateError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code != 200:
        raise GenerateError("生成状況の確認に失敗しました。")
    return res.json()


async def fetch_result(request_id: str, *, base_url: str, api_key: str = "") -> bytes:
    """完了後の生成結果（zip）をバイト列で取得する。"""
    if not base_url:
        raise GenerateError("文書生成 API が未設定です。")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.get(
                f"{base_url}/result/{request_id}", headers=_headers(api_key)
            )
        except httpx.HTTPError as e:
            raise GenerateError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code != 200:
        raise GenerateError("生成結果の取得に失敗しました。")
    return res.content


async def compose(
    outputs: list[dict[str, Any]],
    *,
    base_url: str,
    api_key: str = "",
    reference: str | None = None,
) -> bytes:
    """順序付き Markdown（出力ファイル毎）を生成サービスへ送り Word(.docx) zip を得る。

    outputs = [{"name": str, "sections": [{"filename": str, "content": str}, ...]}, ...]
    """
    if not base_url:
        raise GenerateError("文書生成 API が未設定です（このテーマの合成先が未設定）。")
    if not outputs:
        raise GenerateError("合成対象の出力ファイルがありません。")
    body: dict[str, Any] = {"outputs": outputs}
    if reference:
        body["reference"] = reference
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.post(
                f"{base_url}/compose", json=body, headers=_headers(api_key)
            )
        except httpx.HTTPError as e:
            raise GenerateError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code != 200:
        try:
            msg = res.json().get("error") or "Word 合成に失敗しました。"
        except Exception:  # noqa: BLE001
            msg = "Word 合成に失敗しました。"
        raise GenerateError(msg)
    return res.content
