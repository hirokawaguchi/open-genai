"""戦国国取り（小さい専用ゲーム）の決定的ルールエンジン。

- すべて純関数。副作用・乱数生成器の内包を避け、乱数は `random.Random` を引数で受ける。
- 合戦の解決・資源の増減・勝敗判定はここに閉じ込める（LLM には触らせない）。
- 商標や特定商品のシステム・画面は複製しない。史実上の国名・大名名を使った独自ルール。
"""

from __future__ import annotations

import copy
import math
import random
from typing import Any

# --- 盤面定義（中央 8 国・4 家） --------------------------------------------

PROVINCES: dict[str, dict[str, Any]] = {
    # id: 表示名・初期所有・石高・守備兵・地図座標(0..100)。x は東ほど大・y は南ほど大。
    "echigo": {"name": "越後", "owner": "uesugi", "kokudaka": 24, "troops": 34, "x": 48, "y": 12},
    "kozuke": {"name": "上野", "owner": "uesugi", "kokudaka": 18, "troops": 22, "x": 66, "y": 16},
    "shinano": {"name": "信濃", "owner": "takeda", "kokudaka": 20, "troops": 26, "x": 50, "y": 30},
    "kai": {"name": "甲斐", "owner": "takeda", "kokudaka": 20, "troops": 30, "x": 68, "y": 40},
    "musashi": {"name": "武蔵", "owner": "hojo", "kokudaka": 22, "troops": 28, "x": 84, "y": 28},
    "sagami": {"name": "相模", "owner": "hojo", "kokudaka": 20, "troops": 30, "x": 88, "y": 42},
    "suruga": {"name": "駿河", "owner": "imagawa", "kokudaka": 19, "troops": 26, "x": 80, "y": 54},
    "totomi": {"name": "遠江", "owner": "imagawa", "kokudaka": 17, "troops": 22, "x": 68, "y": 64},
    "mikawa": {"name": "三河", "owner": "imagawa", "kokudaka": 18, "troops": 24, "x": 56, "y": 72},
    "owari": {"name": "尾張", "owner": "oda", "kokudaka": 22, "troops": 30, "x": 42, "y": 68},
    "mino": {"name": "美濃", "owner": "saito", "kokudaka": 24, "troops": 30, "x": 46, "y": 48},
    "hida": {"name": "飛騨", "owner": "saito", "kokudaka": 14, "troops": 16, "x": 32, "y": 38},
    "omi": {"name": "近江", "owner": "asai", "kokudaka": 20, "troops": 22, "x": 26, "y": 58},
    "echizen": {"name": "越前", "owner": "asakura", "kokudaka": 20, "troops": 24, "x": 14, "y": 48},
    "kaga": {"name": "加賀", "owner": "asakura", "kokudaka": 18, "troops": 20, "x": 20, "y": 24},
    "ise": {"name": "伊勢", "owner": "oda", "kokudaka": 16, "troops": 20, "x": 36, "y": 82},
}

# 隣接（無向グラフ。両方向を明示的に持つ）
ADJACENCY: dict[str, list[str]] = {
    "echigo": ["kozuke", "shinano", "kaga"],
    "kozuke": ["echigo", "shinano", "musashi"],
    "shinano": ["echigo", "kozuke", "kai", "hida", "mino"],
    "kai": ["shinano", "musashi", "suruga", "totomi"],
    "musashi": ["kozuke", "kai", "sagami"],
    "sagami": ["musashi", "suruga"],
    "suruga": ["kai", "sagami", "totomi"],
    "totomi": ["kai", "suruga", "mikawa"],
    "mikawa": ["totomi", "owari"],
    "owari": ["mikawa", "mino", "ise", "omi"],
    "mino": ["shinano", "owari", "hida", "omi"],
    "hida": ["shinano", "mino", "echizen"],
    "omi": ["owari", "mino", "echizen", "ise"],
    "echizen": ["hida", "omi", "kaga"],
    "kaga": ["echigo", "echizen"],
    "ise": ["owari", "omi"],
}

# 各家の個性（史実に寄せた能力・性格）。
# - attack/defense: 合戦での攻撃力・守備力の倍率
# - economy: 石高収入の倍率（内政の巧拙）
# - aggression: 0..1。簡易 AI の侵攻積極度と、LLM ペルソナの好戦性
# - loyalty: 0..1。同盟を重んじる度合い（LLM ペルソナ用）
# - trait: 一言の特徴（UI 表示・LLM ペルソナ）
# - persona: LLM に渡す人物像（史実に近い性格づけ）
HOUSES: dict[str, dict[str, Any]] = {
    "oda": {
        "name": "織田",
        "gold": 130,
        "attack": 1.10,
        "defense": 1.00,
        "economy": 1.20,
        "aggression": 0.85,
        "loyalty": 0.30,
        "trait": "革新・急進",
        "persona": "織田信長。革新的で果断、経済を重んじ、好機と見れば容赦なく攻める。既存の権威や盟約にはこだわらない。",
    },
    "takeda": {
        "name": "武田",
        "gold": 120,
        "attack": 1.25,
        "defense": 1.05,
        "economy": 1.00,
        "aggression": 0.75,
        "loyalty": 0.50,
        "trait": "最強の騎馬",
        "persona": "武田信玄。精強な騎馬軍団を率いる用兵の名手。堅実だが好機には力攻めを辞さない。",
    },
    "uesugi": {
        "name": "上杉",
        "gold": 120,
        "attack": 1.20,
        "defense": 1.10,
        "economy": 0.95,
        "aggression": 0.60,
        "loyalty": 0.80,
        "trait": "義の戦上手",
        "persona": "上杉謙信。軍神と称される戦上手。義を重んじ、理由なき裏切りや盟約破りを好まない。",
    },
    "hojo": {
        "name": "北条",
        "gold": 125,
        "attack": 0.95,
        "defense": 1.30,
        "economy": 1.15,
        "aggression": 0.35,
        "loyalty": 0.70,
        "trait": "難攻の守り",
        "persona": "北条氏康。堅城を背に守りを固める。領国経営に長け、慎重で守勢を旨とする。",
    },
    "imagawa": {
        "name": "今川",
        "gold": 135,
        "attack": 0.95,
        "defense": 1.00,
        "economy": 1.20,
        "aggression": 0.55,
        "loyalty": 0.50,
        "trait": "富貴の名門",
        "persona": "今川義元。裕福な名門で兵は多いが、やや油断しがち。上洛を狙う野心も持つ。",
    },
    "saito": {
        "name": "斎藤",
        "gold": 120,
        "attack": 1.05,
        "defense": 1.05,
        "economy": 1.05,
        "aggression": 0.65,
        "loyalty": 0.25,
        "trait": "下剋上・策謀",
        "persona": "斎藤道三。蝮と呼ばれる策謀家。下剋上を体現し、利のために手段を選ばない。",
    },
    "asakura": {
        "name": "朝倉",
        "gold": 120,
        "attack": 1.00,
        "defense": 1.15,
        "economy": 1.05,
        "aggression": 0.30,
        "loyalty": 0.65,
        "trait": "保守・守成",
        "persona": "朝倉義景。保守的で守成を重んじ、積極的な外征を好まない。",
    },
    "asai": {
        "name": "浅井",
        "gold": 115,
        "attack": 1.05,
        "defense": 1.05,
        "economy": 1.00,
        "aggression": 0.40,
        "loyalty": 0.90,
        "trait": "義理堅い",
        "persona": "浅井長政。義理堅く同盟を重んじる。小勢ながら結んだ盟約は守り抜こうとする。",
    },
}

SEASONS = ["春", "夏", "秋", "冬"]

# --- パラメータ --------------------------------------------------------------

DEVELOP_COST = 30
DEVELOP_GAIN = 5
KOKUDAKA_MAX = 60

RECRUIT_COST = 20
RECRUIT_GAIN = 15
# 兵の上限は石高に比例（石高 * この係数）
TROOPS_PER_KOKU = 2.0

# 侵攻・移動時に出撃元へ最低限残す守備兵
MIN_GARRISON = 5

# 兵糧: 毎ターン、兵 1 につきこの金を消費する（兵が多いほど金が減る）。
UPKEEP_PER_TROOP = 0.5

# 移動: 道中でわずかに落伍する兵が出ることがある（確率と、出る場合の割合レンジ）。
MARCH_DESERTION_CHANCE = 0.5
MARCH_DESERTION_RANGE = (0.02, 0.08)

# 外交: 同盟の有効期限（季節数）。過ぎると自動で中立に戻る。
ALLIANCE_TERM_SEASONS = 6
# 貢金が承諾確率に与える最大寄与と、その満額の目安。
DIPLO_GIFT_MAX_BONUS = 0.35
DIPLO_GIFT_FULL = 140


def _dip_key(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


def new_game(player_house: str | None) -> dict[str, Any]:
    """初期盤面を生成する。

    player_house は HOUSES のキー。None のときは観戦（AI のみ）モード。
    """
    if player_house is not None and player_house not in HOUSES:
        raise ValueError(f"不明な家: {player_house}")
    observer = player_house is None
    provinces = copy.deepcopy(PROVINCES)
    houses: dict[str, Any] = {}
    for hid, h in HOUSES.items():
        houses[hid] = {
            "name": h["name"],
            "gold": h["gold"],
            "alive": True,
            "is_player": hid == player_house,
            # 個性（能力・性格）を局に取り込む
            "attack": h["attack"],
            "defense": h["defense"],
            "economy": h["economy"],
            "aggression": h["aggression"],
            "loyalty": h["loyalty"],
            "trait": h["trait"],
            "persona": h["persona"],
        }
    # 外交は全ペア中立から
    diplomacy: dict[str, str] = {}
    hids = list(HOUSES.keys())
    for i in range(len(hids)):
        for j in range(i + 1, len(hids)):
            diplomacy[_dip_key(hids[i], hids[j])] = "neutral"
    return {
        "turn": 1,
        "season_index": 0,
        "player_house": player_house,
        "observer": observer,
        "status": "playing",
        "winner": None,
        "provinces": provinces,
        "adjacency": copy.deepcopy(ADJACENCY),
        "houses": houses,
        "diplomacy": diplomacy,
        "alliance_expiry": {},  # pair_key -> 期限（グローバル季節数）
        "log": [],
    }


# --- 参照系（純粋な読み取り） ------------------------------------------------

def provinces_of(state: dict[str, Any], house_id: str) -> list[str]:
    return [pid for pid, p in state["provinces"].items() if p["owner"] == house_id]


def alive_houses(state: dict[str, Any]) -> list[str]:
    return [hid for hid, h in state["houses"].items() if h["alive"]]


def visible_provinces(state: dict[str, Any], house_id: str) -> set[str]:
    """その家から兵力が見える国＝自国とその隣接国。"""
    own = provinces_of(state, house_id)
    visible = set(own)
    for pid in own:
        for nb in state["adjacency"].get(pid, []):
            visible.add(nb)
    return visible


def mask_state_for(state: dict[str, Any], house_id: str | None) -> dict[str, Any]:
    """人間プレイヤーの視界に合わせ、隣接外の国の兵力を隠した state を返す。

    観戦モード（house_id=None）や house_id 不明のときは何も隠さない。
    隠した国は troops=None にし、UI 側で「?」表示する。owner（勢力色）は見える。
    """
    if not house_id or house_id not in state.get("houses", {}):
        return state
    state = copy.deepcopy(state)
    visible = visible_provinces(state, house_id)
    for pid, p in state["provinces"].items():
        if pid not in visible:
            p["troops"] = None
            p["fog"] = True
    return state


def relation(state: dict[str, Any], a: str, b: str) -> str:
    if a == b:
        return "self"
    return state["diplomacy"].get(_dip_key(a, b), "neutral")


def troops_cap(kokudaka: int) -> int:
    return int(kokudaka * TROOPS_PER_KOKU)


def global_season(state: dict[str, Any]) -> int:
    """開始からの通算季節数（同盟期限の判定に使う）。"""
    return (state["turn"] - 1) * len(SEASONS) + state["season_index"]


def house_power(state: dict[str, Any], house_id: str) -> int:
    """家の国力（総兵数＋所領石高合計）。外交の承諾判定に使う。"""
    troops = total_troops(state, house_id)
    koku = sum(state["provinces"][pid]["kokudaka"] for pid in provinces_of(state, house_id))
    return troops + koku


def acceptance_prob(
    state: dict[str, Any],
    proposer: str,
    target: str,
    action: str,
    gift: int,
) -> float:
    """同盟/和睦の承諾確率。相手の loyalty・国力差・貢金で決まる。"""
    if action not in ("ally", "peace"):
        return 1.0
    loyalty = state["houses"][target].get("loyalty", 0.5)
    pp = house_power(state, proposer)
    tp = max(1, house_power(state, target))
    ratio = pp / tp  # >1 なら申し出た側が強い（＝相手が弱い）
    if action == "ally":
        p = 0.20 + 0.55 * loyalty
        if ratio >= 1:
            p += min(0.30, 0.15 * (ratio - 1))  # 強者の庇護を得たい
        else:
            p -= min(0.25, 0.25 * (1 - ratio))  # 格下との同盟は渋る
    else:  # peace
        p = 0.35 + 0.45 * loyalty
        if ratio >= 1:
            p += min(0.30, 0.15 * (ratio - 1))  # 劣勢の相手は和睦を受けやすい
        else:
            p -= min(0.25, 0.20 * (1 - ratio))  # 優勢の相手は和睦を渋る
    if gift > 0:
        p += min(DIPLO_GIFT_MAX_BONUS, gift / DIPLO_GIFT_FULL * DIPLO_GIFT_MAX_BONUS)
    return max(0.05, min(0.95, p))


def total_troops(state: dict[str, Any], house_id: str) -> int:
    return sum(state["provinces"][pid]["troops"] for pid in provinces_of(state, house_id))


def upkeep_for(state: dict[str, Any], house_id: str) -> int:
    """その家の兵糧（毎ターンの兵の維持費）。"""
    return int(round(total_troops(state, house_id) * UPKEEP_PER_TROOP))


def _log(state: dict[str, Any], house_id: str, text: str) -> None:
    state["log"].append(
        {
            "turn": state["turn"],
            "season": SEASONS[state["season_index"] % len(SEASONS)],
            "house": house_id,
            "house_name": state["houses"].get(house_id, {}).get("name", house_id),
            "text": text,
        }
    )


def _refresh_alive(state: dict[str, Any]) -> None:
    """所領を全て失った家を脱落させ、外交を破棄する。"""
    for hid, h in state["houses"].items():
        if h["alive"] and not provinces_of(state, hid):
            h["alive"] = False
            _log(
                state,
                hid,
                f"{h['name']}家はついに拠って立つ地を失い、その旗はこの世から消えた。",
            )


# --- 命令の検証と適用（1 家・1 命令） ---------------------------------------

def validate_command(state: dict[str, Any], house_id: str, command: Any) -> str | None:
    """命令が実行可能かを検証する。問題なければ None、あればエラーメッセージ。"""
    if not isinstance(command, dict):
        return "命令の形式が不正です"
    ctype = command.get("type")
    houses = state["houses"]
    if house_id not in houses or not houses[house_id]["alive"]:
        return "その家は行動できません"

    if ctype == "develop":
        pid = command.get("province")
        p = state["provinces"].get(pid)
        if not p or p["owner"] != house_id:
            return "自国の領地を指定してください"
        if houses[house_id]["gold"] < DEVELOP_COST:
            return "資金が足りません"
        if p["kokudaka"] >= KOKUDAKA_MAX:
            return "石高は既に上限です"
        return None

    if ctype == "recruit":
        pid = command.get("province")
        p = state["provinces"].get(pid)
        if not p or p["owner"] != house_id:
            return "自国の領地を指定してください"
        if houses[house_id]["gold"] < RECRUIT_COST:
            return "資金が足りません"
        if p["troops"] >= troops_cap(p["kokudaka"]):
            return "兵は既に上限です"
        return None

    if ctype == "invade":
        src = command.get("from")
        dst = command.get("to")
        ps = state["provinces"].get(src)
        pd = state["provinces"].get(dst)
        if not ps or ps["owner"] != house_id:
            return "出撃元は自国の領地である必要があります"
        if not pd:
            return "侵攻先が不正です"
        if pd["owner"] == house_id:
            return "自国へは侵攻できません"
        if dst not in state["adjacency"].get(src, []):
            return "隣接していない国へは侵攻できません"
        if relation(state, house_id, pd["owner"]) == "ally":
            return "同盟中の家へは侵攻できません"
        troops = command.get("troops")
        if not isinstance(troops, int) or troops <= 0:
            return "出撃兵数が不正です"
        if ps["troops"] - troops < MIN_GARRISON:
            return f"出撃元に守備兵を{MIN_GARRISON}以上残す必要があります"
        return None

    if ctype == "march":
        src = command.get("from")
        dst = command.get("to")
        ps = state["provinces"].get(src)
        pd = state["provinces"].get(dst)
        if not ps or ps["owner"] != house_id:
            return "移動元は自国の領地である必要があります"
        if not pd or pd["owner"] != house_id:
            return "移動先も自国の領地である必要があります"
        if src == dst:
            return "同じ国へは移動できません"
        if dst not in state["adjacency"].get(src, []):
            return "隣接していない国へは移動できません"
        troops = command.get("troops")
        if not isinstance(troops, int) or troops <= 0:
            return "移動兵数が不正です"
        if ps["troops"] - troops < MIN_GARRISON:
            return f"移動元に守備兵を{MIN_GARRISON}以上残す必要があります"
        return None

    if ctype == "diplomacy":
        target = command.get("target")
        action = command.get("action")
        if target not in houses or target == house_id:
            return "外交相手が不正です"
        if not houses[target]["alive"]:
            return "既に滅亡した家とは外交できません"
        if action not in ("ally", "declare", "peace"):
            return "外交の種類が不正です"
        cur = relation(state, house_id, target)
        if action == "ally" and cur == "war":
            return "交戦中の相手とは即時同盟できません（先に和睦が必要）"
        if action in ("ally", "peace"):
            gift = command.get("gift", 0)
            if not isinstance(gift, int) or gift < 0:
                return "貢金が不正です"
            if gift > houses[house_id].get("gold", 0):
                return "貢金にあてる金が足りません"
        return None

    if ctype in ("rest", None):
        return None  # 何もしない（休養）

    return f"未知の命令: {ctype}"


def _resolve_battle(
    attacker_troops: int,
    defender_troops: int,
    rng: random.Random,
    atk_mult: float = 1.0,
    def_mult: float = 1.0,
) -> tuple[bool, int, int]:
    """合戦を決定的（rng 依存）に解く。

    atk_mult / def_mult は攻撃側・守備側の家の個性（能力）による倍率。
    戻り値: (攻撃側勝利か, 勝者の残存兵, 敗者の残存兵=0)
    """
    atk = attacker_troops * (0.8 + rng.random() * 0.5) * atk_mult
    # 守備側は地の利で微加算
    dfn = defender_troops * (1.0 + rng.random() * 0.4) * def_mult
    if atk > dfn:
        # 攻撃側勝利。残存兵は戦力差に応じる（最低 1）
        ratio = max(0.15, 1.0 - defender_troops / max(1.0, atk))
        survivors = max(1, int(attacker_troops * ratio))
        return True, survivors, 0
    # 守備側勝利。守備側は損耗して残る
    ratio = max(0.15, 1.0 - attacker_troops / max(1.0, dfn))
    survivors = max(1, int(defender_troops * ratio))
    return False, survivors, 0


def apply_command(
    state: dict[str, Any],
    house_id: str,
    command: Any,
    rng: random.Random,
) -> dict[str, Any]:
    """1 家の 1 命令を適用した新しい state を返す（入力は変更しない）。

    検証に失敗する命令は休養（rest）として扱い、ログにその旨を残す。
    """
    state = copy.deepcopy(state)
    err = validate_command(state, house_id, command)
    if err:
        hname = state["houses"].get(house_id, {}).get("name", house_id)
        _log(
            state,
            house_id,
            f"{hname}家は下知を出したが、軍議まとまらずこの季は動かなかった（{err}）。",
        )
        return state

    ctype = command.get("type") if isinstance(command, dict) else None
    houses = state["houses"]
    provinces = state["provinces"]

    hname = houses[house_id]["name"]

    if ctype == "develop":
        p = provinces[command["province"]]
        houses[house_id]["gold"] -= DEVELOP_COST
        p["kokudaka"] = min(KOKUDAKA_MAX, p["kokudaka"] + DEVELOP_GAIN)
        _log(
            state,
            house_id,
            f"{hname}家は{p['name']}に新田を拓き、民は鍬をふるった。"
            f"実り増して石高は{p['kokudaka']}に達した。",
        )

    elif ctype == "recruit":
        p = provinces[command["province"]]
        houses[house_id]["gold"] -= RECRUIT_COST
        cap = troops_cap(p["kokudaka"])
        p["troops"] = min(cap, p["troops"] + RECRUIT_GAIN)
        _log(
            state,
            house_id,
            f"{hname}家は{p['name']}に触れを出して兵を募り、"
            f"陣容は{p['troops']}の兵にふくらんだ。",
        )

    elif ctype == "invade":
        src = provinces[command["from"]]
        dst = provinces[command["to"]]
        troops = int(command["troops"])
        defender_id = dst["owner"]
        src["troops"] -= troops
        # 侵攻は自動的に開戦扱い
        state["diplomacy"][_dip_key(house_id, defender_id)] = "war"
        atk_mult = houses[house_id].get("attack", 1.0)
        def_mult = houses[defender_id].get("defense", 1.0)
        won, survivors, _ = _resolve_battle(
            troops, dst["troops"], rng, atk_mult=atk_mult, def_mult=def_mult
        )
        def_name = houses[defender_id]["name"]
        if won:
            dst["owner"] = house_id
            dst["troops"] = survivors
            _log(
                state,
                house_id,
                f"{hname}家は{troops}の兵を率いて{src['name']}より{dst['name']}へ攻め寄せた。"
                f"激しい攻防のすえ{def_name}方の守りを打ち破り、{dst['name']}はついに落城。"
                f"城には{survivors}の兵が残り、旗指物が改まった。",
            )
            # この一戦で守備側が最後の所領を失ったなら、その蔵の金を勝者が接収する。
            if not provinces_of(state, defender_id):
                spoils = houses[defender_id].get("gold", 0)
                if spoils > 0:
                    houses[house_id]["gold"] += spoils
                    houses[defender_id]["gold"] = 0
                    _log(
                        state,
                        house_id,
                        f"{hname}家は滅亡した{def_name}家の蔵を接収し、金 {spoils} を得た。",
                    )
        else:
            dst["troops"] = survivors
            _log(
                state,
                house_id,
                f"{hname}家は{troops}の兵で{dst['name']}へ攻めかかったが、"
                f"{def_name}方の守将よく防ぎ、寄せ手は退いた。"
                f"城方には{survivors}の兵が踏みとどまった。",
            )

    elif ctype == "march":
        src = provinces[command["from"]]
        dst = provinces[command["to"]]
        troops = int(command["troops"])
        src["troops"] -= troops
        # 道中でわずかに落伍する兵が出ることがある（総兵数はそのぶん減る）。
        stragglers = 0
        if troops > 1 and rng.random() < MARCH_DESERTION_CHANCE:
            lo, hi = MARCH_DESERTION_RANGE
            stragglers = min(troops - 1, int(round(troops * rng.uniform(lo, hi))))
        arrived = troops - stragglers
        dst["troops"] += arrived
        if stragglers > 0:
            _log(
                state,
                house_id,
                f"{hname}家は{troops}の兵を{src['name']}から{dst['name']}へ移した。"
                f"道中で{stragglers}が落伍し、{arrived}が着陣した"
                f"（{src['name']}{src['troops']}・{dst['name']}{dst['troops']}）。",
            )
        else:
            _log(
                state,
                house_id,
                f"{hname}家は{troops}の兵を{src['name']}から{dst['name']}へ移し、"
                f"守りを固め直した（{src['name']}{src['troops']}・{dst['name']}{dst['troops']}）。",
            )

    elif ctype == "diplomacy":
        target = command["target"]
        action = command["action"]
        gift = int(command.get("gift", 0) or 0)
        key = _dip_key(house_id, target)
        tname = houses[target]["name"]
        expiry = state.setdefault("alliance_expiry", {})
        if action == "declare":
            # 宣戦は無条件。同盟中なら盟約破棄となる。
            state["diplomacy"][key] = "war"
            expiry.pop(key, None)
            _log(state, house_id, f"{hname}家は{tname}家へ宣戦を布告し、乱世に火の手が上がった。")
        else:
            # 同盟・和睦は相手の承諾が要る（loyalty・国力差・貢金で確率が決まる）。
            prob = acceptance_prob(state, house_id, target, action, gift)
            accepted = rng.random() < prob
            actname = "同盟" if action == "ally" else "和睦"
            if not accepted:
                _log(
                    state,
                    house_id,
                    f"{hname}家は{tname}家に{actname}を申し入れたが、断られた。",
                )
            else:
                if gift > 0:
                    houses[house_id]["gold"] -= gift
                    houses[target]["gold"] += gift
                if action == "ally":
                    state["diplomacy"][key] = "ally"
                    expiry[key] = global_season(state) + ALLIANCE_TERM_SEASONS
                    giftmsg = f"（貢金 {gift}）" if gift > 0 else ""
                    _log(
                        state,
                        house_id,
                        f"{hname}家は{tname}家と盟を結んだ{giftmsg}。"
                        f"約定は{ALLIANCE_TERM_SEASONS}季のうち。",
                    )
                else:  # peace
                    state["diplomacy"][key] = "neutral"
                    expiry.pop(key, None)
                    giftmsg = f"（贈物 {gift}）" if gift > 0 else ""
                    _log(
                        state,
                        house_id,
                        f"{hname}家は{tname}家と兵を収め、和睦の盃を交わした{giftmsg}。",
                    )

    else:  # rest
        _log(state, house_id, f"{hname}家はこの季、兵を休めて力を蓄え、次なる機をうかがった。")

    _refresh_alive(state)
    return state


# --- ターン進行（収入・勝敗） ------------------------------------------------

def _starve_troops(state: dict[str, Any], house_id: str, count: int) -> int:
    """兵糧不足の兵を、兵の多い国から順に離散させる。実際に減らした数を返す。"""
    if count <= 0:
        return 0
    removed = 0
    pids = sorted(
        provinces_of(state, house_id),
        key=lambda pid: state["provinces"][pid]["troops"],
        reverse=True,
    )
    remaining = count
    # 兵の多い国から均さず順に削る（0 未満にはしない）
    while remaining > 0:
        progressed = False
        for pid in pids:
            if remaining <= 0:
                break
            if state["provinces"][pid]["troops"] > 0:
                state["provinces"][pid]["troops"] -= 1
                removed += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break  # もう減らせる兵がいない
    return removed


def collect_income(state: dict[str, Any]) -> dict[str, Any]:
    """全生存家に石高ぶんの年貢を与え、兵糧（兵の維持費）を差し引く。

    兵糧を払えないと金は 0 になり、賄えなかったぶんの兵が離散する（兵糧攻めの飢餓）。
    プレイヤー家は毎ターン収支を合戦記に記す。
    """
    state = copy.deepcopy(state)
    player = state.get("player_house")
    for hid, h in state["houses"].items():
        if not h["alive"]:
            continue
        base = sum(state["provinces"][pid]["kokudaka"] for pid in provinces_of(state, hid))
        income = int(round(base * h.get("economy", 1.0)))
        upkeep = upkeep_for(state, hid)
        h["gold"] += income - upkeep
        if hid == player:
            _log(
                state,
                hid,
                f"{h['name']}家に年貢 {income} が納められ、兵糧 {upkeep} を給した"
                f"（金は {max(h['gold'], 0)}）。",
            )
        if h["gold"] < 0:
            deficit = -h["gold"]
            h["gold"] = 0
            starve = math.ceil(deficit / UPKEEP_PER_TROOP)
            lost = _starve_troops(state, hid, starve)
            if lost:
                _log(
                    state,
                    hid,
                    f"{h['name']}家は兵糧が尽き、{lost}の兵が飢えて離散した。",
                )
    _refresh_alive(state)
    return state


def check_status(state: dict[str, Any]) -> dict[str, Any]:
    """勝敗を反映した新しい state を返す。"""
    state = copy.deepcopy(state)
    player = state.get("player_house")
    living = alive_houses(state)
    if state.get("observer") or player is None:
        # 観戦（AI のみ）: 1 家に絞られたら終局。勝者を記録する。
        if len(living) <= 1:
            state["status"] = "ended"
            state["winner"] = living[0] if living else None
        else:
            state["status"] = "playing"
        return state
    if player not in living:
        state["status"] = "lost"
    elif living == [player]:
        state["status"] = "won"
    else:
        state["status"] = "playing"
    return state


def expire_alliances(state: dict[str, Any]) -> dict[str, Any]:
    """有効期限を過ぎた同盟を中立へ戻す。"""
    state = copy.deepcopy(state)
    now = global_season(state)
    expiry = state.setdefault("alliance_expiry", {})
    for key, until in list(expiry.items()):
        if state["diplomacy"].get(key) == "ally" and until <= now:
            state["diplomacy"][key] = "neutral"
            expiry.pop(key, None)
            a, b = key.split("|")
            na = state["houses"].get(a, {}).get("name", a)
            nb = state["houses"].get(b, {}).get("name", b)
            # 勢力に属さない出来事として記す（UI は中立の印で表示）。
            state["log"].append(
                {
                    "turn": state["turn"],
                    "season": SEASONS[state["season_index"] % len(SEASONS)],
                    "house": "",
                    "house_name": "",
                    "text": f"{na}家と{nb}家の同盟は約定の季を過ぎ、自然と解かれた。",
                    "event": True,
                }
            )
    return state


def advance_season(state: dict[str, Any]) -> dict[str, Any]:
    """季節を進め、冬を越えたらターンを繰り上げる。"""
    state = copy.deepcopy(state)
    state["season_index"] += 1
    if state["season_index"] >= len(SEASONS):
        state["season_index"] = 0
        state["turn"] += 1
    return state


# --- 簡易 AI（LLM フォールバック） -------------------------------------------

def heuristic_command(
    state: dict[str, Any], house_id: str, rng: random.Random
) -> dict[str, Any]:
    """脅威なら徴兵、有利なら侵攻、そうでなければ開墾する簡易 AI。

    LLM のタイムアウト・不正応答・不正命令のフォールバックに使う。
    """
    houses = state["houses"]
    gold = houses[house_id]["gold"]
    my_provinces = provinces_of(state, house_id)
    if not my_provinces:
        return {"type": "rest"}

    # 好戦的な家ほど、少ない兵力差でも攻める（個性を反映）。
    aggression = houses[house_id].get("aggression", 0.5)
    # 攻撃側能力も見込んで必要優位を割り引く
    attack = houses[house_id].get("attack", 1.0)
    # 必要優位倍率: aggression 0→1.6, 1→1.05 くらい。攻撃力が高いほどさらに緩む。
    need_ratio = (1.6 - 0.55 * aggression) / max(0.8, attack)

    # 侵攻候補: 自国の隣で、同盟でなく、自軍が十分に上回れる敵国
    invade_options: list[tuple[int, dict[str, Any]]] = []
    threats: list[str] = []  # 守りを固めたい自国
    for pid in my_provinces:
        p = state["provinces"][pid]
        for nb in state["adjacency"].get(pid, []):
            np_ = state["provinces"][nb]
            if np_["owner"] == house_id:
                continue
            if relation(state, house_id, np_["owner"]) == "ally":
                continue
            # 送れる兵（守備を残す）
            available = p["troops"] - MIN_GARRISON
            if available > np_["troops"] * need_ratio and available >= 8:
                margin = available - np_["troops"]
                invade_options.append(
                    (margin, {"type": "invade", "from": pid, "to": nb, "troops": int(available)})
                )
            # 隣接敵が自国守備を上回るなら脅威
            if np_["troops"] > p["troops"]:
                threats.append(pid)

    # 有利な侵攻があれば最も差が大きいものを選ぶ
    if invade_options:
        invade_options.sort(key=lambda x: x[0], reverse=True)
        return invade_options[0][1]

    # 脅威があり資金があれば徴兵
    if threats and gold >= RECRUIT_COST:
        # 最も手薄な脅威国を補強
        threats.sort(key=lambda pid: state["provinces"][pid]["troops"])
        for pid in threats:
            p = state["provinces"][pid]
            if p["troops"] < troops_cap(p["kokudaka"]):
                return {"type": "recruit", "province": pid}

    # 資金があれば石高の伸びしろが大きい国を開墾
    if gold >= DEVELOP_COST:
        candidates = [
            pid for pid in my_provinces if state["provinces"][pid]["kokudaka"] < KOKUDAKA_MAX
        ]
        if candidates:
            candidates.sort(key=lambda pid: state["provinces"][pid]["kokudaka"])
            return {"type": "develop", "province": candidates[0]}

    # 資金が乏しければ徴兵か休養
    if gold >= RECRUIT_COST:
        for pid in my_provinces:
            p = state["provinces"][pid]
            if p["troops"] < troops_cap(p["kokudaka"]):
                return {"type": "recruit", "province": pid}

    return {"type": "rest"}
