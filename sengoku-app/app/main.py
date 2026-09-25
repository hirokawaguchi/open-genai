"""戦国国取りマイクロサービス（Open GENAI exApp / 専用ページ向け）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /game 等へプロキシする。
- プレイヤーの命令は決定的ルールで解決し、敵対 3 家の命令だけ LLM が決める
  （失敗時は簡易 AI にフォールバック）。
- セーブは利用者につき 1 局（SQLite）。「新規」で捨ててやり直す。

Compose では profiles: ["sengoku"] でオプション起動する。
"""

from __future__ import annotations

import os
import random
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import ai, events, intauth, llm, rules, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

app = FastAPI(title="Open GENAI Sengoku App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str]:
    err = _check_key(x_api_key)
    if err:
        return err, ""
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), ""
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _static_meta() -> dict[str, Any]:
    """盤面の静的定義（表示名・地図座標）。UI が地図描画に使う。"""
    return {
        "provinces": {
            pid: {"name": p["name"], "x": p["x"], "y": p["y"]}
            for pid, p in rules.PROVINCES.items()
        },
        "adjacency": rules.ADJACENCY,
        "houses": {
            hid: {
                "name": h["name"],
                "trait": h["trait"],
                "persona": h["persona"],
                "attack": h["attack"],
                "defense": h["defense"],
                "economy": h["economy"],
                "aggression": h["aggression"],
                "loyalty": h["loyalty"],
            }
            for hid, h in rules.HOUSES.items()
        },
        "params": {
            "develop_cost": rules.DEVELOP_COST,
            "develop_gain": rules.DEVELOP_GAIN,
            "kokudaka_max": rules.KOKUDAKA_MAX,
            "recruit_cost": rules.RECRUIT_COST,
            "recruit_gain": rules.RECRUIT_GAIN,
            "min_garrison": rules.MIN_GARRISON,
            "troops_per_koku": rules.TROOPS_PER_KOKU,
            "upkeep_per_troop": rules.UPKEEP_PER_TROOP,
            "alliance_term_seasons": rules.ALLIANCE_TERM_SEASONS,
            "seasons": rules.SEASONS,
        },
    }


@app.get("/config")
def get_config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        content={
            "enabled": True,
            "meta": _static_meta(),
            "llm": {
                "model": llm.SENGOKU_MODEL,
                "base_url": llm.OPENAI_BASE_URL,
            },
        }
    )


@app.get("/game")
def get_game(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    state = store.load_game(uid)
    if state:
        state = rules.mask_state_for(state, state.get("player_house"))
    return JSONResponse(content={"game": state})


@app.post("/game")
async def new_game(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    # mode="observer" もしくは house 未指定/None で観戦（AI のみ）モード。
    mode = (body.get("mode") or "").strip()
    house_raw = body.get("house")
    house = (house_raw or "").strip()
    observer = mode == "observer" or not house
    if not observer and house not in rules.HOUSES:
        return JSONResponse(
            status_code=400,
            content={"error": "大名家を正しく選択してください", "houses": list(rules.HOUSES)},
        )
    if observer:
        state = rules.new_game(None)
        rules._log(state, "", "乱世、群雄割拠す。八家の争覇を天の視点より見守る。")
    else:
        state = rules.new_game(house)
        rules._log(
            state,
            house,
            f"乱世、群雄割拠す。{rules.HOUSES[house]['name']}家、旗を掲げて天下統一の途につく。",
        )
    store.save_game(uid, state)
    print(f"[sengoku] new game by={uid} house={house or '(observer)'}")
    masked = rules.mask_state_for(state, state.get("player_house"))
    return JSONResponse(status_code=201, content={"game": masked})


@app.delete("/game")
def delete_game(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    store.delete_game(uid)
    return JSONResponse(content={"message": "局を破棄しました", "game": None})


@app.post("/game/turn")
async def play_turn(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    state = store.load_game(uid)
    if not state:
        return JSONResponse(status_code=404, content={"error": "進行中の局がありません"})
    if state.get("status") != "playing":
        return JSONResponse(
            status_code=409,
            content={"error": "この局は既に決着しています。新規で始めてください。", "game": state},
        )

    body = await request.json()
    command = body.get("command")
    player = state.get("player_house")
    observer = state.get("observer") or player is None

    rng = random.Random()
    turn_ai: list[dict[str, Any]] = []

    # ターン開始時に、期限切れの同盟を中立へ戻す（この季から攻められるようになる）。
    state = rules.expire_alliances(state)

    if not observer:
        # プレイヤーの命令はまず検証（不正なら 400 で理由を返し、ターンは進めない）
        verr = rules.validate_command(state, player, command)
        if verr:
            masked = rules.mask_state_for(state, player)
            return JSONResponse(status_code=400, content={"error": verr, "game": masked})
        # 1) プレイヤーの手を解決
        state = rules.apply_command(state, player, command, rng)
        state = rules.check_status(state)

    # 2) AI 各家の手を LLM に決めさせ、検証／簡易 AI で解決
    #    通常は敵対家のみ。観戦モードは全家を AI が動かす。
    if state["status"] == "playing":
        ai_houses = [
            h
            for h in rules.HOUSES
            if state["houses"][h]["alive"] and (observer or h != player)
        ]
        orders = await ai.decide_opponent_orders(state, ai_houses, rng)
        for o in orders:
            hid = o["house"]
            if not state["houses"][hid]["alive"]:
                continue
            command = o["command"]
            source = o.get("source")
            # 手はターン開始時の盤面で一括決定される。先に動いた家が盤面を変え、
            # この手が無効になっていたら、その場の簡易 AI で選び直す（空振り防止）。
            if rules.validate_command(state, hid, command) is not None:
                command = rules.heuristic_command(state, hid, rng)
                source = "heuristic"
            # 一言は実際に LLM が決めた手のときだけ記す（簡易 AI のダミーは出さない）。
            comment = o.get("comment") if source == "llm" else ""
            if comment:
                hname = state["houses"][hid]["name"]
                rules._log(state, hid, f"{hname}家の軍師は言う――「{comment}」")
            state = rules.apply_command(state, hid, command, rng)
            state = rules.check_status(state)
            turn_ai.append(
                {
                    "house": hid,
                    "house_name": state["houses"][hid]["name"],
                    "command": command,
                    "comment": comment,
                    "source": source,
                }
            )
            if state["status"] != "playing":
                break

    # 3) 季節のイベント → 収入 → 季節送り → 勝敗確定
    if state["status"] == "playing":
        state = events.apply_seasonal_event(state, rng)
        state = rules.check_status(state)
    if state["status"] == "playing":
        state = rules.collect_income(state)
        state = rules.advance_season(state)
        state = rules.check_status(state)

    store.save_game(uid, state)
    masked = rules.mask_state_for(state, state.get("player_house"))
    return JSONResponse(content={"game": masked, "ai_orders": turn_ai})
