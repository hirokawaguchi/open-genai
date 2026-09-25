"""季節に応じた出来事（天災・豊凶・一揆）。

- 春: 豊作の兆し / 一揆
- 夏: 野分（台風・進路あり） / 干ばつ
- 秋: 豊作 / 一揆
- 冬: 飢饉 / 大雪（北国）

合戦の解決と同様、効果は決定的（rng 依存）。何が起きるかは season で分岐し、
一定確率で「平穏（何も起きない）」。イベントのログは勢力に属さない天災として記す。
"""

from __future__ import annotations

import random
from typing import Any

from . import rules

KOKUDAKA_MIN = 5  # 干ばつ等で下がっても、この石高は残す


def _season_name(state: dict[str, Any]) -> str:
    return rules.SEASONS[state["season_index"] % len(rules.SEASONS)]


def _log_event(state: dict[str, Any], text: str) -> None:
    """勢力に属さない出来事（天災・民）としてログに記す。"""
    state["log"].append(
        {
            "turn": state["turn"],
            "season": _season_name(state),
            "house": "",  # 空 = 天災/民（UI は中立の印で表示）
            "house_name": "",
            "text": text,
            "event": True,
        }
    )


def _clamp_kokudaka(v: int) -> int:
    return max(KOKUDAKA_MIN, min(rules.KOKUDAKA_MAX, v))


def _reduce_troops(province: dict[str, Any], ratio: float) -> int:
    """守備兵を ratio ぶん減らし、失った数を返す。"""
    troops = province.get("troops") or 0
    lost = int(round(troops * ratio))
    lost = min(lost, troops)
    province["troops"] = troops - lost
    return lost


def _random_province(rng: random.Random, provinces: dict[str, Any]) -> str:
    return rng.choice(list(provinces.keys()))


def _bumper_sprout(state: dict[str, Any], rng: random.Random) -> bool:
    pid = _random_province(rng, state["provinces"])
    p = state["provinces"][pid]
    before = p["kokudaka"]
    p["kokudaka"] = _clamp_kokudaka(before + 3)
    if p["kokudaka"] == before:
        return False
    _log_event(state, f"{p['name']}に豊かな実りの兆し。田畑が肥え、石高が{p['kokudaka']}に増した。")
    return True


def _harvest(state: dict[str, Any], rng: random.Random) -> bool:
    pid = _random_province(rng, state["provinces"])
    p = state["provinces"][pid]
    owner = p["owner"]
    bonus = max(5, p["kokudaka"] // 2)
    state["houses"][owner]["gold"] += bonus
    oname = state["houses"][owner]["name"]
    _log_event(state, f"{p['name']}は豊作に恵まれ、{oname}家の蔵に金 {bonus} が納まった。")
    return True


def _drought(state: dict[str, Any], rng: random.Random) -> bool:
    pid = _random_province(rng, state["provinces"])
    p = state["provinces"][pid]
    before = p["kokudaka"]
    p["kokudaka"] = _clamp_kokudaka(before - 3)
    if p["kokudaka"] == before:
        return False
    _log_event(state, f"{p['name']}が干ばつに見舞われ、田が枯れて石高が{p['kokudaka']}に落ちた。")
    return True


def _ikki(state: dict[str, Any], rng: random.Random) -> bool:
    # 兵のいる国から選ぶ（重い年貢への反発として兵が損なわれる）
    candidates = [pid for pid, p in state["provinces"].items() if (p.get("troops") or 0) > 0]
    if not candidates:
        return False
    pid = rng.choice(candidates)
    p = state["provinces"][pid]
    lost = _reduce_troops(p, rng.uniform(0.15, 0.30))
    p["kokudaka"] = _clamp_kokudaka(p["kokudaka"] - 1)
    oname = state["houses"][p["owner"]]["name"]
    _log_event(
        state,
        f"{p['name']}で一揆が蜂起し、{oname}家は鎮圧に追われた。兵 {lost} が失われた。",
    )
    rules._refresh_alive(state)
    return True


def _famine(state: dict[str, Any], rng: random.Random) -> bool:
    candidates = [pid for pid, p in state["provinces"].items() if (p.get("troops") or 0) > 0]
    if not candidates:
        return False
    pid = rng.choice(candidates)
    p = state["provinces"][pid]
    lost = _reduce_troops(p, rng.uniform(0.15, 0.25))
    owner = p["owner"]
    state["houses"][owner]["gold"] = max(0, state["houses"][owner]["gold"] - 10)
    oname = state["houses"][owner]["name"]
    _log_event(state, f"{p['name']}を飢饉が襲い、{oname}家では兵 {lost} が飢えて失われた。")
    rules._refresh_alive(state)
    return True


def _heavy_snow(state: dict[str, Any], rng: random.Random) -> bool:
    # 北国（y が小さい）を大雪が襲う
    northern = [
        pid
        for pid, p in state["provinces"].items()
        if p["y"] < 34 and (p.get("troops") or 0) > 0
    ]
    if not northern:
        return False
    total = 0
    names: list[str] = []
    for pid in northern:
        p = state["provinces"][pid]
        lost = _reduce_troops(p, rng.uniform(0.06, 0.12))
        total += lost
        if lost > 0:
            names.append(p["name"])
    if total == 0:
        return False
    _log_event(
        state,
        f"北国（{'・'.join(names)}）を大雪が襲い、凍えて兵 {total} が損なわれた。",
    )
    rules._refresh_alive(state)
    return True


def _typhoon(state: dict[str, Any], rng: random.Random) -> bool:
    """野分（台風）。海沿い・南方から上陸し、隣接をたどって内陸へ抜ける進路を持つ。"""
    provinces = state["provinces"]
    # 上陸地は南（y 大）ほど選ばれやすい
    pids = list(provinces.keys())
    weights = [max(1.0, provinces[pid]["y"]) for pid in pids]
    start = rng.choices(pids, weights=weights, k=1)[0]
    path = [start]
    cur = start
    for _ in range(rng.randint(1, 3)):
        nbs = [n for n in state["adjacency"].get(cur, []) if n not in path]
        if not nbs:
            break
        # 進路は内陸（y が小さい方）へ向かいやすい
        nb_w = [max(1.0, 100 - provinces[n]["y"]) for n in nbs]
        cur = rng.choices(nbs, weights=nb_w, k=1)[0]
        path.append(cur)

    total_troops_lost = 0
    for pid in path:
        p = provinces[pid]
        total_troops_lost += _reduce_troops(p, rng.uniform(0.08, 0.16))
        p["kokudaka"] = _clamp_kokudaka(p["kokudaka"] - 2)
    names = [provinces[pid]["name"] for pid in path]
    if len(names) == 1:
        route = f"{names[0]}を"
    else:
        route = f"{names[0]}に上陸し、{'・'.join(names[1:])}を"
    _log_event(
        state,
        f"野分（台風）が{route}通って抜けた。田畑は荒れ、兵 {total_troops_lost} が損なわれた。",
    )
    rules._refresh_alive(state)
    return True


# season_index -> [(重み, 関数 or None)]。None は「平穏」。
_SEASON_TABLE: dict[int, list[tuple[float, Any]]] = {
    0: [(0.40, None), (0.35, _bumper_sprout), (0.25, _ikki)],  # 春
    1: [(0.40, None), (0.35, _typhoon), (0.25, _drought)],  # 夏
    2: [(0.40, None), (0.40, _harvest), (0.20, _ikki)],  # 秋
    3: [(0.40, None), (0.35, _famine), (0.25, _heavy_snow)],  # 冬
}


def apply_seasonal_event(state: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """現在の季節に応じた出来事を最大 1 つ適用した新しい state を返す。"""
    import copy

    state = copy.deepcopy(state)
    table = _SEASON_TABLE.get(state["season_index"] % len(rules.SEASONS), [(1.0, None)])
    weights = [w for w, _ in table]
    funcs = [f for _, f in table]
    chosen = rng.choices(funcs, weights=weights, k=1)[0]
    if chosen is None:
        return state
    # 効果が無効（対象なし等）なら黙って平穏にする
    chosen(state, rng)
    return state
