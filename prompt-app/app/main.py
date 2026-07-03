"""プロンプトテンプレート「AI アプリ」マイクロサービス。

本サービス仕様書 6-(20)(21)(22):
- (20) プロンプトテンプレート機能
- (21) 標準で利用可能なテンプレートが存在
- (22) 利用者が作成し、組織/グループで共有できる

源内(genai-web)無改修。テンプレートを選ぶと、本文（変数置換後）を **チャットへ
流し込むディープリンク**（`/chat?content=...`）を返す。全ユーザーが利用可能。

exApp 同期プロトコル:
    リクエスト: { "inputs": { "operation": "use|list|create|delete", ... } }
    レスポンス: { "outputs": "<Markdown>" }
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import catalog, intauth

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
ADMIN_GROUP = os.environ.get("AUDIT_ADMIN_GROUP", "SystemAdminGroup")

app = FastAPI(title="Open GENAI Prompt Template App", version="0.1.0")

# 標準テンプレート（6-(21)）。汎用の行政実務向け（特定自治体に依存しない）。
STANDARD_TEMPLATES = [
    {
        "id": "std-minutes",
        "title": "議事録の要約",
        "target": "content",
        "body": (
            "以下の会議メモを、次の観点で日本語で整理・要約してください。\n"
            "- 決定事項\n- ToDo（担当・期限つき）\n- 主要な論点\n\n"
            "【会議メモ】\n{{メモ}}"
        ),
    },
    {
        "id": "std-proofread",
        "title": "文章の校正",
        "target": "content",
        "body": "次の文章を、意味を変えずに誤字脱字・表現を整えて校正してください。\n\n{{本文}}",
    },
    {
        "id": "std-mail",
        "title": "ビジネスメールの作成",
        "target": "content",
        "body": (
            "次の要点で、丁寧なビジネスメールの文面を作成してください。\n\n"
            "宛先: {{宛先}}\n件名の方向性: {{件名}}\n伝えたい要点: {{要点}}"
        ),
    },
    {
        "id": "std-explain",
        "title": "わかりやすい説明",
        "target": "content",
        "body": "次の内容を、専門知識のない人にも分かるように、平易な言葉で説明してください。\n\n{{内容}}",
    },
    {
        "id": "std-summarize",
        "title": "長文の要約",
        "target": "content",
        "body": "次の文章を、重要点を落とさずに3〜5個の箇条書きで要約してください。\n\n{{本文}}",
    },
]


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _groups(x_user_groups: str | None) -> list[str]:
    return [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]


def _team_ids(x_user_tags: str | None) -> list[str]:
    """所属チームID（backend が署名付与、x-user-tags スロット）。チーム共有の可視判定に使う。"""
    return [t.strip() for t in (x_user_tags or "").split(",") if t.strip()]


def _team_name_map(x_user_teams: str | None) -> dict[str, str]:
    """所属チームの id→name（表示専用・非署名の x-user-teams、Base64化JSON）。"""
    if not x_user_teams:
        return {}
    try:
        raw = base64.b64decode(x_user_teams).decode("utf-8")
        data = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return {}
    result: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = str(item.get("name") or item["id"])
    return result


def _is_admin(x_user_groups: str | None) -> bool:
    return ADMIN_GROUP in set(_groups(x_user_groups))


# /invoke で「変数」として解釈しない予約キー（それ以外の入力キーは {{キー}} の値とみなす）
RESERVED_INPUT_KEYS = {
    "operation",
    "template_id",
    "variables",
    "title",
    "body",
    "target",
    "share",
    "share_team",
    "share_tag",
    "share_group",
    "conversation_histories",
    "files",
}


def _kind(t: dict[str, Any]) -> str:
    return "標準" if t["isStandard"] else ("共有" if t["sharedGroups"] else "個人")


def _template_items(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"title": f"{t['title']}（{_kind(t)}）", "value": t["id"]} for t in items]


def _build_form_schema(
    user_id: str,
    team_ids: list[str],
    is_admin: bool,
    *,
    team_names: dict[str, str] | None = None,
    variables: list[str] | None = None,
    selected_body: str = "",
) -> dict[str, Any]:
    """OpenGENAI exApp Form Spec v1 のフォーム定義を生成する。

    `variables`/`selected_body` は /resolve で選択テンプレに応じて注入される。
    項目の並び順（フロントは Object.keys 順で描画）:
    操作 → テンプレ選択 → 変数入力欄 → プレビュー → 作成系。
    """
    variables = variables or []
    team_names = team_names or {}
    visible = catalog.list_visible(user_id, team_ids, is_admin)

    share_items = [
        {"title": "個人（自分のみ）", "value": "personal"},
        {"title": "チームで共有", "value": "team"},
        {"title": "全体公開", "value": "public"},
    ]
    if is_admin:
        share_items.append({"title": "標準（管理者のみ）", "value": "standard"})
    team_items = [{"title": team_names.get(tid, tid), "value": tid} for tid in team_ids]

    ui: dict[str, Any] = {}
    ui["$version"] = "opengenai-form/1"
    ui["operation"] = {
        "type": "select",
        "title": "操作",
        "items": [
            {"title": "使う（チャットへ）", "value": "use"},
            {"title": "一覧", "value": "list"},
            {"title": "作成", "value": "create"},
            {
                "title": "削除",
                "value": "delete",
                "confirm": "選択したテンプレートを削除します。元に戻せません。よろしいですか？",
            },
        ],
        "default_value": "use",
        "reactive": True,
    }
    ui["template_id"] = {
        "type": "select",
        "title": "テンプレートを選択",
        "desc": "使う／削除するテンプレートを選びます。",
        "items": _template_items(visible),
        "reactive": True,
        "visibleWhen": {"field": "operation", "in": ["use", "delete"]},
    }
    for name in variables:
        ui[name] = {
            "type": "textarea",
            "title": f"変数: {name}",
            "desc": "本文の {{" + name + "}} に入る値を入力します。",
            "visibleWhen": {"field": "operation", "in": ["use"]},
        }
    ui["__preview__"] = {
        "type": "preview",
        "title": "組み上がるプロンプト（プレビュー）",
        "template": selected_body,
        "desc": "上の変数を入力すると、チャットへ送られる文面がここに反映されます。",
        "visibleWhen": {"field": "operation", "in": ["use"]},
    }
    ui["title"] = {
        "type": "text",
        "title": "タイトル（作成）",
        "visibleWhen": {"field": "operation", "in": ["create"]},
    }
    ui["body"] = {
        "type": "textarea",
        "title": "本文（作成）",
        "desc": "{{メモ}} のように {{ }} で変数を埋め込めます。",
        "visibleWhen": {"field": "operation", "in": ["create"]},
    }
    ui["target"] = {
        "type": "select",
        "title": "挿入先（作成）",
        "items": [
            {"title": "入力欄（チャット本文）", "value": "content"},
            {"title": "システムプロンプト", "value": "system"},
        ],
        "default_value": "content",
        "visibleWhen": {"field": "operation", "in": ["create"]},
    }
    ui["share"] = {
        "type": "select",
        "title": "共有範囲（作成）",
        "items": share_items,
        "default_value": "personal",
        "desc": "「チームで共有」は自分の所属チームに共有します。全体公開は全利用者に見えます。",
        "visibleWhen": {"field": "operation", "in": ["create"]},
    }
    ui["share_team"] = {
        "type": "select",
        "title": "共有先チーム（チーム共有時）",
        "items": team_items,
        "desc": "自分が所属するチームから選択します。所属していないチームへは共有できません。",
        "visibleWhen": [
            {"field": "operation", "in": ["create"]},
            {"field": "share", "in": ["team"]},
        ],
    }
    return ui


@app.on_event("startup")
def _startup() -> None:
    try:
        catalog.init_db()
        # 標準テンプレートが未登録なら投入（冪等）
        for t in STANDARD_TEMPLATES:
            if catalog.get_template(t["id"]) is None:
                catalog.create_template(
                    title=t["title"],
                    body=t["body"],
                    owner_user="system",
                    target=t.get("target", "content"),
                    is_standard=True,
                    template_id=t["id"],
                )
    except Exception as e:  # noqa: BLE001
        print(f"[prompt-app] 初期化に失敗: {e}")


@app.get("/health")
async def health() -> dict[str, Any]:
    try:
        n = catalog.count()
    except Exception:  # noqa: BLE001
        n = -1
    return {"status": "ok", "templates": n}


@app.get("/schema")
async def schema(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_user_teams: str | None = Header(default=None),
) -> Any:
    """OpenGENAI exApp Form Spec v1: 初期フォーム定義を返す。"""
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    user_id = (x_user_id or "").strip()
    team_ids = _team_ids(x_user_tags)
    team_names = _team_name_map(x_user_teams)
    is_admin = _is_admin(x_user_groups)
    return {"placeholder": _build_form_schema(user_id, team_ids, is_admin, team_names=team_names)}


@app.post("/resolve")
async def resolve(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_user_teams: str | None = Header(default=None),
) -> Any:
    """OpenGENAI exApp Form Spec v1: 現在入力に応じてフォームを再計算する。

    「使う」でテンプレートが選択されたら、その本文の {{変数}} に対応する入力欄を
    追加し、プレビューの本文を選択テンプレートに更新する。
    """
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    user_id = (x_user_id or "").strip()
    team_ids = _team_ids(x_user_tags)
    team_names = _team_name_map(x_user_teams)
    is_admin = _is_admin(x_user_groups)

    body = await request.json()
    inputs = body.get("inputs", body)
    operation = (inputs.get("operation") or "use").strip().lower()
    tid = (inputs.get("template_id") or "").strip()

    variables: list[str] = []
    selected_body = ""
    if operation == "use" and tid:
        t = catalog.get_template(tid)
        if t:
            visible_ids = {x["id"] for x in catalog.list_visible(user_id, team_ids, is_admin)}
            if tid in visible_ids:
                selected_body = t["body"]
                variables = catalog.template_variables(selected_body)

    ui = _build_form_schema(
        user_id,
        team_ids,
        is_admin,
        team_names=team_names,
        variables=variables,
        selected_body=selected_body,
    )
    return {"placeholder": ui}


def _render_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "利用可能なテンプレートはありません。"
    lines = ["## 利用可能なテンプレート", "", "| ID | タイトル | 区分 |", "| --- | --- | --- |"]
    for t in items:
        kind = "標準" if t["isStandard"] else ("共有" if t["sharedGroups"] else "個人")
        lines.append(f"| `{t['id']}` | {t['title']} | {kind} |")
    lines.append("")
    lines.append("> 「使う」で ID を指定すると、チャットへ流し込むリンクを表示します。")
    return "\n".join(lines)


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_user_teams: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    # backend 署名の検証（x-user-* の偽装対策。チーム共有の信頼性にも寄与）
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})

    user_id = (x_user_id or "").strip()
    team_ids = _team_ids(x_user_tags)
    team_names = _team_name_map(x_user_teams)
    is_admin = _is_admin(x_user_groups)

    body = await request.json()
    inputs = body.get("inputs", body)
    operation = (inputs.get("operation") or "use").strip().lower()

    if operation == "list":
        return {"outputs": _render_list(catalog.list_visible(user_id, team_ids, is_admin))}

    if operation == "create":
        title = (inputs.get("title") or "").strip()
        tbody = (inputs.get("body") or "").strip()
        if not title or not tbody:
            return {"outputs": "タイトルと本文を入力してください。"}
        share = (inputs.get("share") or "personal").strip().lower()
        target = (inputs.get("target") or "content").strip().lower()
        is_standard = False
        shared_teams: list[str] = []
        if share == "standard":
            if not is_admin:
                return {"outputs": "標準テンプレートの作成はシステム管理者のみ可能です。"}
            is_standard = True
        elif share == "public":
            shared_teams = ["public"]
        elif share == "team":
            # 旧 share_tag/share_group も後方互換で受理
            team = (
                inputs.get("share_team")
                or inputs.get("share_tag")
                or inputs.get("share_group")
                or ""
            ).strip()
            if not team:
                return {"outputs": "共有先チーム（share_team）を指定してください。"}
            # 自分が所属していないチームへは共有できない（管理者は例外）。
            # これがないと、非所属チーム向けにプロンプト/ディープリンクを仕込める。
            if not is_admin and team not in set(team_ids):
                label = team_names.get(team, team)
                return {
                    "outputs": (
                        f"チーム「{label}」に所属していないため共有できません"
                        "（所属チーム、または個人／全体公開を選択してください）。"
                    )
                }
            shared_teams = [team]
        tid = catalog.create_template(
            title=title,
            body=tbody,
            owner_user=user_id,
            target=target,
            shared_groups=shared_teams,
            is_standard=is_standard,
        )
        return {"outputs": f"テンプレートを作成しました（ID: `{tid}`）。「一覧」で確認できます。"}

    if operation == "delete":
        tid = (inputs.get("template_id") or "").strip()
        t = catalog.get_template(tid) if tid else None
        if not t:
            return {"outputs": "指定 ID のテンプレートが見つかりません。"}
        if not catalog.can_delete(t, user_id, is_admin):
            return {"outputs": "このテンプレートを削除する権限がありません。"}
        catalog.delete_template(tid)
        return {"outputs": f"テンプレート `{tid}` を削除しました。"}

    # use（既定）
    tid = (inputs.get("template_id") or "").strip()
    if not tid:
        listing = _render_list(catalog.list_visible(user_id, team_ids, is_admin))
        return {"outputs": "使用するテンプレートの ID を指定してください。\n\n" + listing}
    t = catalog.get_template(tid)
    if not t:
        return {"outputs": "指定 ID のテンプレートが見つかりません。"}
    # 可視性チェック（他人の個人テンプレは使えない）
    visible_ids = {x["id"] for x in catalog.list_visible(user_id, team_ids, is_admin)}
    if tid not in visible_ids:
        return {"outputs": "このテンプレートを利用する権限がありません。"}

    # 変数は (1) 従来の「変数」テキスト（キー: 値）と、(2) OpenGENAI Form Spec v1 で
    # 自動生成される個別入力欄（キー=変数名）の両対応。(2) は予約キー以外の入力から拾う。
    variables = catalog.parse_vars(inputs.get("variables"))
    for k, v in inputs.items():
        if k in RESERVED_INPUT_KEYS or k.startswith("$"):
            continue
        if isinstance(v, bool):
            sv = "true" if v else "false"
        elif isinstance(v, (str, int, float)):
            sv = str(v)
        else:
            continue
        if sv != "" and k not in variables:
            variables[k] = sv
    filled, missing = catalog.substitute(t["body"], variables)
    target = t.get("target", "content")
    link = catalog.deeplink_if_fits(filled, target=target, auto_submit=False)

    out = [f"## {t['title']}", "", "```text", filled, "```", ""]
    if missing:
        out.append(f"> 未入力の変数: {', '.join('{{' + m + '}}' for m in missing)}"
                   "（「変数」に `キー: 値` の形式で指定できます）")
        out.append("")
    if link:
        out.append(f"👉 [このプロンプトでチャットを開く]({link})")
    else:
        # 長文は URL(GET) 長制限を超えるため、リンク流し込みは無効化しコピー運用に誘導。
        out.append(
            "> このプロンプトは長いため、チャットへの直接リンクは無効です。"
            "上の本文の「コピー」ボタンでコピーし、チャットに貼り付けてご利用ください。"
        )
    return {"outputs": "\n".join(out)}
