"""敵対大名の 1 ターンぶんの命令を LLM に決めさせる（失敗時は簡易 AI）。

- LLM には「盤面の要約」と「使える命令の形」だけを渡し、1 回の JSON 応答で
  全ての敵対家の命令と一言コメントを返させる。
- 合戦の解決・資源の増減は rules.py（決定的）。ここは意思決定の文章化のみ。
- タイムアウト・不正 JSON・検証に通らない命令は rules.heuristic_command に落とす。
"""

from __future__ import annotations

import random
from typing import Any

from . import llm, rules

SYSTEM_PROMPT = (
    "あなたは戦国時代の国取り合戦を戦う複数の大名家の軍師です。"
    "与えられた盤面をもとに、各家が取るべき最善の一手を決めます。"
    "必ず指定された JSON 形式だけを返し、余計な説明文やコードフェンス以外の文章は書かないでください。"
)

# LLM に提示する命令の形式（プロンプト用）
COMMAND_SPEC = """各家の command は次のいずれか:
- {"type":"develop","province":"<自国の国id>"}  # 開墾。石高を上げる（収入増）
- {"type":"recruit","province":"<自国の国id>"}  # 徴兵。兵を増やす（兵糧も増える）
- {"type":"invade","from":"<自国の国id>","to":"<隣接する他家の国id>","troops":<出撃兵数(整数)>}  # 侵攻
- {"type":"march","from":"<自国の国id>","to":"<隣接する自国の国id>","troops":<移動兵数(整数)>}  # 兵の移動
- {"type":"diplomacy","target":"<他家id>","action":"ally|declare|peace","gift":<貢金(整数,任意)>}  # 外交
- {"type":"rest"}  # 休養
制約: invade は隣接かつ非同盟の相手のみ。march は隣接する自国のみ。出撃元/移動元には守備兵を5以上残す。
外交: declare(宣戦)は無条件。ally(同盟)/peace(和睦)は相手の承諾が要り、断られることもある。
      gift(貢金)を付けると承諾されやすくなる（承諾時のみ相手に支払う）。同盟には有効期限がある。
兵糧: 毎ターン兵1につき0.5の金を消費する。金が尽きると兵が離散するので、収入(石高)と兵数の釣り合いを保つこと。"""


def _compact_state(state: dict[str, Any], houses: list[str]) -> dict[str, Any]:
    """LLM へ渡す最小限の盤面要約。"""
    provinces = {}
    for pid, p in state["provinces"].items():
        provinces[pid] = {
            "name": p["name"],
            "owner": p["owner"],
            "kokudaka": p["kokudaka"],
            "troops": p["troops"],
            "adjacent": state["adjacency"].get(pid, []),
        }
    house_info = {}
    for hid in houses:
        h = state["houses"][hid]
        house_info[hid] = {
            "name": h["name"],
            "gold": h["gold"],
            "provinces": rules.provinces_of(state, hid),
        }
    # 外交関係（生存家間のみ）
    diplomacy = {}
    living = rules.alive_houses(state)
    for i in range(len(living)):
        for j in range(i + 1, len(living)):
            a, b = living[i], living[j]
            diplomacy[f"{a}-{b}"] = rules.relation(state, a, b)
    return {
        "turn": state["turn"],
        "controllable_houses": house_info,
        "all_provinces": provinces,
        "diplomacy": diplomacy,
    }


def _persona_lines(state: dict[str, Any], houses: list[str]) -> str:
    """指揮する各家の人物像（史実に寄せた性格）を提示し、役になりきらせる。"""
    lines = []
    for h in houses:
        info = state["houses"][h]
        persona = info.get("persona") or info.get("name")
        trait = info.get("trait", "")
        aggr = info.get("aggression", 0.5)
        loy = info.get("loyalty", 0.5)
        lines.append(
            f"- {h}（{info['name']}家・{trait}）: {persona} "
            f"[好戦性 {aggr:.2f} / 盟約重視 {loy:.2f}]"
        )
    return "\n".join(lines)


def _build_prompt(state: dict[str, Any], houses: list[str]) -> str:
    import json

    compact = _compact_state(state, houses)
    names = "、".join(f"{h}（{state['houses'][h]['name']}）" for h in houses)
    return (
        f"あなたが指揮する家: {names}\n\n"
        "各家の人物像（性格になりきり、好戦性・盟約重視の度合いを行動に反映すること）:\n"
        f"{_persona_lines(state, houses)}\n\n"
        f"盤面:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        f"{COMMAND_SPEC}\n\n"
        "次の JSON 形式で、指揮する各家の一手を返してください:\n"
        '{"orders":[{"house":"<家id>","command":{...},"comment":"<20文字以内の一言>"}]}\n'
        "各家について必ず1件ずつ、その大名の性格にふさわしく、勝利（全国統一）を目指す手を選んでください。"
        "好戦的な家は侵攻を、守勢の家は内政・防備を、盟約重視の家は同盟を尊ぶ傾向にします。"
    )


async def decide_opponent_orders(
    state: dict[str, Any],
    opponent_houses: list[str],
    rng: random.Random,
) -> list[dict[str, Any]]:
    """敵対各家の (house, command, comment, source) を返す。

    LLM 応答を検証し、通らない家だけ簡易 AI に落とす。LLM 全体が失敗しても
    全家を簡易 AI で埋めるので、必ず opponent_houses と同数を返す。
    """
    living_opponents = [h for h in opponent_houses if state["houses"][h]["alive"]]
    llm_orders: dict[str, dict[str, Any]] = {}
    llm_error: str | None = None

    if living_opponents:
        try:
            raw = await llm.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_prompt(state, living_opponents)},
                ]
            )
            parsed = llm.extract_json(raw)
            orders = parsed.get("orders") if isinstance(parsed, dict) else None
            if isinstance(orders, list):
                for o in orders:
                    if not isinstance(o, dict):
                        continue
                    hid = o.get("house")
                    if hid in living_opponents:
                        llm_orders[hid] = {
                            "command": o.get("command"),
                            "comment": (o.get("comment") or "").strip()[:40],
                        }
        except Exception as e:  # noqa: BLE001
            llm_error = str(e)
            print(f"[sengoku] LLM 命令生成に失敗、簡易 AI に切替: {e}")

    results: list[dict[str, Any]] = []
    for hid in living_opponents:
        entry = llm_orders.get(hid)
        command = entry.get("command") if entry else None
        comment = entry.get("comment") if entry else ""
        # LLM 命令が検証に通れば採用、だめなら簡易 AI
        if command is not None and rules.validate_command(state, hid, command) is None:
            results.append(
                {
                    "house": hid,
                    "command": command,
                    "comment": comment,
                    "source": "llm",
                }
            )
        else:
            fallback = rules.heuristic_command(state, hid, rng)
            results.append(
                {
                    "house": hid,
                    "command": fallback,
                    "comment": "",  # 簡易 AI はダミーの一言を出さない
                    "source": "heuristic",
                    "llm_error": llm_error,
                }
            )
    return results
