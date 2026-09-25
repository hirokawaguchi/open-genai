"""ルールエンジンの単体テスト（LLM 本体は対象外）。"""

from __future__ import annotations

import random

from app import rules


def _rng(seed: int = 1) -> random.Random:
    return random.Random(seed)


def test_new_game_initial_state():
    st = rules.new_game("oda")
    assert st["status"] == "playing"
    assert st["turn"] == 1
    assert st["houses"]["oda"]["is_player"] is True
    assert st["houses"]["saito"]["is_player"] is False
    # 織田は尾張・伊勢を持つ
    owned = set(rules.provinces_of(st, "oda"))
    assert owned == {"owari", "ise"}
    # 全ペア中立で開始
    assert rules.relation(st, "oda", "saito") == "neutral"


def test_new_game_rejects_unknown_house():
    try:
        rules.new_game("nobody")
    except ValueError:
        return
    raise AssertionError("不明な家で ValueError が出るべき")


def test_develop_increases_kokudaka_and_costs_gold():
    st = rules.new_game("oda")
    gold0 = st["houses"]["oda"]["gold"]
    koku0 = st["provinces"]["owari"]["kokudaka"]
    st2 = rules.apply_command(st, "oda", {"type": "develop", "province": "owari"}, _rng())
    assert st2["provinces"]["owari"]["kokudaka"] == koku0 + rules.DEVELOP_GAIN
    assert st2["houses"]["oda"]["gold"] == gold0 - rules.DEVELOP_COST
    # 入力は変更されない（純関数）
    assert st["provinces"]["owari"]["kokudaka"] == koku0


def test_develop_rejects_other_house_province():
    st = rules.new_game("oda")
    # 美濃は斎藤。織田は開墾できない → 休養扱いで石高変わらず
    koku0 = st["provinces"]["mino"]["kokudaka"]
    st2 = rules.apply_command(st, "oda", {"type": "develop", "province": "mino"}, _rng())
    assert st2["provinces"]["mino"]["kokudaka"] == koku0
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_recruit_increases_troops_capped():
    st = rules.new_game("oda")
    p = st["provinces"]["ise"]
    p["troops"] = rules.troops_cap(p["kokudaka"]) - 1  # 上限直前
    st2 = rules.apply_command(st, "oda", {"type": "recruit", "province": "ise"}, _rng())
    assert st2["provinces"]["ise"]["troops"] == rules.troops_cap(p["kokudaka"])


def test_invade_requires_adjacency():
    st = rules.new_game("oda")
    # 尾張(織田)から甲斐(武田)は隣接していない
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "kai", "troops": 20}, _rng()
    )
    # 攻略されず、武田のまま
    assert st2["provinces"]["kai"]["owner"] == "takeda"
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_invade_success_conquers_province():
    st = rules.new_game("oda")
    # 圧倒的兵力で三河(今川)を攻略
    st["provinces"]["owari"]["troops"] = 200
    st["provinces"]["mikawa"]["troops"] = 5
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "mikawa", "troops": 150}, _rng()
    )
    assert st2["provinces"]["mikawa"]["owner"] == "oda"
    assert st2["provinces"]["mikawa"]["troops"] >= 1
    # 出撃元は兵を減らす
    assert st2["provinces"]["owari"]["troops"] == 50
    # 侵攻で開戦状態になる
    assert rules.relation(st2, "oda", "imagawa") == "war"


def test_invade_failure_keeps_owner():
    st = rules.new_game("oda")
    st["provinces"]["owari"]["troops"] = 200
    st["provinces"]["mikawa"]["troops"] = 300  # 圧倒的守備
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "mikawa", "troops": 190}, _rng()
    )
    assert st2["provinces"]["mikawa"]["owner"] == "imagawa"


def test_invade_blocked_by_alliance():
    st = rules.new_game("oda")
    st["diplomacy"][rules._dip_key("oda", "imagawa")] = "ally"
    st["provinces"]["owari"]["troops"] = 200
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "mikawa", "troops": 150}, _rng()
    )
    assert st2["provinces"]["mikawa"]["owner"] == "imagawa"
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_invade_must_leave_garrison():
    st = rules.new_game("oda")
    st["provinces"]["owari"]["troops"] = 30
    # 30 全部出すと守備 0 → 拒否
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "mikawa", "troops": 30}, _rng()
    )
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_diplomacy_ally_and_peace():
    st = rules.new_game("oda")
    st2 = rules.apply_command(
        st, "oda", {"type": "diplomacy", "target": "takeda", "action": "ally"}, _rng()
    )
    assert rules.relation(st2, "oda", "takeda") == "ally"
    st3 = rules.apply_command(
        st2, "oda", {"type": "diplomacy", "target": "takeda", "action": "peace"}, _rng()
    )
    assert rules.relation(st3, "oda", "takeda") == "neutral"


class _SeqRandom(random.Random):
    """random() が指定値を順に返すスタブ（承諾判定の制御用）。"""

    def __init__(self, values):
        super().__init__()
        self._values = list(values)

    def random(self):  # noqa: D401
        return self._values.pop(0) if self._values else 0.999


def test_diplomacy_ally_needs_consent_and_can_be_rejected():
    st = rules.new_game("oda")
    # 承諾確率は 0.05..0.95。random()=0.999 は必ず拒否側。
    st2 = rules.apply_command(
        st, "oda", {"type": "diplomacy", "target": "takeda", "action": "ally"}, _SeqRandom([0.999])
    )
    assert rules.relation(st2, "oda", "takeda") == "neutral"  # 成立せず
    assert "断られた" in st2["log"][-1]["text"]


def test_diplomacy_ally_accept_sets_expiry():
    st = rules.new_game("oda")
    st2 = rules.apply_command(
        st, "oda", {"type": "diplomacy", "target": "takeda", "action": "ally"}, _SeqRandom([0.0])
    )
    assert rules.relation(st2, "oda", "takeda") == "ally"
    key = rules._dip_key("oda", "takeda")
    assert st2["alliance_expiry"][key] == rules.global_season(st2) + rules.ALLIANCE_TERM_SEASONS


def test_diplomacy_gift_paid_only_on_accept():
    st = rules.new_game("oda")
    oda0 = st["houses"]["oda"]["gold"]
    tak0 = st["houses"]["takeda"]["gold"]
    # 承諾: 貢金が相手へ移る
    acc = rules.apply_command(
        st,
        "oda",
        {"type": "diplomacy", "target": "takeda", "action": "ally", "gift": 40},
        _SeqRandom([0.0]),
    )
    assert acc["houses"]["oda"]["gold"] == oda0 - 40
    assert acc["houses"]["takeda"]["gold"] == tak0 + 40
    # 拒否: 貢金は支払われない
    rej = rules.apply_command(
        st,
        "oda",
        {"type": "diplomacy", "target": "takeda", "action": "ally", "gift": 40},
        _SeqRandom([0.999]),
    )
    assert rej["houses"]["oda"]["gold"] == oda0
    assert rej["houses"]["takeda"]["gold"] == tak0


def test_diplomacy_gift_validation_insufficient_gold():
    st = rules.new_game("oda")
    st["houses"]["oda"]["gold"] = 10
    err = rules.validate_command(
        st, "oda", {"type": "diplomacy", "target": "takeda", "action": "ally", "gift": 50}
    )
    assert err is not None and "貢金" in err


def test_alliance_expires_after_term():
    st = rules.new_game("oda")
    st = rules.apply_command(
        st, "oda", {"type": "diplomacy", "target": "takeda", "action": "ally"}, _SeqRandom([0.0])
    )
    assert rules.relation(st, "oda", "takeda") == "ally"
    # 期限ぶんだけ季節を進める
    for _ in range(rules.ALLIANCE_TERM_SEASONS):
        st = rules.advance_season(st)
    st = rules.expire_alliances(st)
    assert rules.relation(st, "oda", "takeda") == "neutral"
    assert "自然と解かれた" in " ".join(e["text"] for e in st["log"])


def test_diplomacy_ally_rejected_during_war():
    st = rules.new_game("oda")
    st["diplomacy"][rules._dip_key("oda", "saito")] = "war"
    st2 = rules.apply_command(
        st, "oda", {"type": "diplomacy", "target": "saito", "action": "ally"}, _rng()
    )
    # 交戦中の即時同盟は不可 → warのまま
    assert rules.relation(st2, "oda", "saito") == "war"


def test_income_adds_kokudaka_minus_upkeep():
    st = rules.new_game("oda")
    gold0 = st["houses"]["oda"]["gold"]
    st2 = rules.collect_income(st)
    base = sum(st["provinces"][pid]["kokudaka"] for pid in rules.provinces_of(st, "oda"))
    income = round(base * st["houses"]["oda"]["economy"])  # 経済（内政）倍率を反映
    upkeep = rules.upkeep_for(st, "oda")
    assert upkeep > 0  # 兵糧が効いている
    assert st2["houses"]["oda"]["gold"] == gold0 + income - upkeep


def test_house_traits_present_and_affect_combat():
    st = rules.new_game("oda")
    # 個性が state に取り込まれている
    assert st["houses"]["takeda"]["attack"] > 1.0  # 武田は攻撃力が高い
    assert st["houses"]["hojo"]["defense"] > 1.0  # 北条は守備が固い
    # 守備倍率が高いほど、同条件で守り切りやすい（多数試行での勝率で確認）
    import random as _r

    def atk_wins(def_mult: float, seed0: int, n: int) -> int:
        wins = 0
        for s in range(n):
            won, _, _ = rules._resolve_battle(50, 50, _r.Random(seed0 + s), 1.0, def_mult)
            wins += 1 if won else 0
        return wins
    weak = atk_wins(1.0, 0, 200)
    strong = atk_wins(1.3, 0, 200)
    assert strong < weak  # 守備倍率が高いほど攻撃側の勝率は下がる


def test_observer_mode_no_player_and_winner_on_last_house():
    st = rules.new_game(None)
    assert st["observer"] is True
    assert st["player_house"] is None
    # 織田以外を全て滅亡させる
    for pid, p in st["provinces"].items():
        p["owner"] = "oda"
    for hid in st["houses"]:
        if hid != "oda":
            st["houses"][hid]["alive"] = False
    st2 = rules.check_status(st)
    assert st2["status"] == "ended"
    assert st2["winner"] == "oda"


def test_fog_hides_non_adjacent_troops():
    st = rules.new_game("oda")
    visible = rules.visible_provinces(st, "oda")
    masked = rules.mask_state_for(st, "oda")
    for pid, p in masked["provinces"].items():
        if pid in visible:
            assert p["troops"] is not None
        else:
            assert p["troops"] is None
            assert p.get("fog") is True


def test_fog_none_for_observer():
    st = rules.new_game(None)
    masked = rules.mask_state_for(st, None)
    # 観戦は隠さない（全ての troops が数値）
    assert all(isinstance(p["troops"], int) for p in masked["provinces"].values())


def test_upkeep_starves_troops_when_broke():
    st = rules.new_game("oda")
    # 金を尽きさせ、兵糧を払えない状態にする
    st["houses"]["oda"]["gold"] = 0
    # 石高を下げて収入を絞り、兵は多めに
    for pid in rules.provinces_of(st, "oda"):
        st["provinces"][pid]["kokudaka"] = 1
        st["provinces"][pid]["troops"] = 40
    before = rules.total_troops(st, "oda")
    st2 = rules.collect_income(st)
    after = rules.total_troops(st2, "oda")
    assert st2["houses"]["oda"]["gold"] == 0
    assert after < before  # 兵糧不足で離散
    assert "兵糧" in " ".join(e["text"] for e in st2["log"])


def test_march_moves_troops_between_own_adjacent():
    st = rules.new_game("oda")
    # 尾張(織田)→伊勢(織田) は隣接
    o0 = st["provinces"]["owari"]["troops"]
    i0 = st["provinces"]["ise"]["troops"]
    st2 = rules.apply_command(
        st, "oda", {"type": "march", "from": "owari", "to": "ise", "troops": 10}, _rng()
    )
    # 出撃元は必ず移動兵ぶん減る
    assert st2["provinces"]["owari"]["troops"] == o0 - 10
    arrived = st2["provinces"]["ise"]["troops"] - i0
    # 落伍があり得るので、着陣は 1..10 の範囲
    assert 1 <= arrived <= 10
    # 総兵数は「元の総数 - 落伍数」で、増えることはない
    assert rules.total_troops(st2, "oda") <= rules.total_troops(st, "oda")


def test_march_desertion_happens_for_some_seeds():
    # 乱数次第で道中の落伍が発生し、着陣が移動兵より少なくなる seed が存在する
    saw_desertion = False
    for seed in range(60):
        st = rules.new_game("oda")
        st["provinces"]["owari"]["troops"] = 60
        i0 = st["provinces"]["ise"]["troops"]
        st2 = rules.apply_command(
            st, "oda", {"type": "march", "from": "owari", "to": "ise", "troops": 40}, _rng(seed)
        )
        arrived = st2["provinces"]["ise"]["troops"] - i0
        if arrived < 40:
            saw_desertion = True
            assert arrived >= 1
            assert rules.total_troops(st2, "oda") < rules.total_troops(st, "oda")
            break
    assert saw_desertion


def test_march_rejects_enemy_destination():
    st = rules.new_game("oda")
    # 尾張(織田)→美濃(斎藤) は他家なので移動不可
    st2 = rules.apply_command(
        st, "oda", {"type": "march", "from": "owari", "to": "mino", "troops": 10}, _rng()
    )
    assert st2["provinces"]["mino"]["owner"] == "saito"
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_march_rejects_non_adjacent():
    st = rules.new_game("oda")
    # 伊勢(織田)と、隣接しない自国が無いので、尾張→三河(隣接だが他家)ではなく
    # 非隣接の自国ケースを作る: 伊勢を甲斐と非隣接のまま織田領にしても甲斐は他家。
    # ここでは駿河を織田領にして（尾張と非隣接）試す。
    st["provinces"]["suruga"]["owner"] = "oda"
    st2 = rules.apply_command(
        st, "oda", {"type": "march", "from": "owari", "to": "suruga", "troops": 10}, _rng()
    )
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_march_must_leave_garrison():
    st = rules.new_game("oda")
    st["provinces"]["owari"]["troops"] = 30
    st2 = rules.apply_command(
        st, "oda", {"type": "march", "from": "owari", "to": "ise", "troops": 30}, _rng()
    )
    assert "軍議まとまらず" in st2["log"][-1]["text"]


def test_house_eliminated_when_no_province():
    st = rules.new_game("oda")
    # 今川の領地を全て織田に移す
    for pid, p in st["provinces"].items():
        if p["owner"] == "imagawa":
            p["owner"] = "oda"
    st2 = rules.apply_command(st, "oda", {"type": "rest"}, _rng())
    assert st2["houses"]["imagawa"]["alive"] is False


def test_conquest_of_last_province_transfers_gold():
    st = rules.new_game("oda")
    # 浅井を1国(近江)だけにして、その近江を尾張から圧倒的兵力で攻略する。
    # 近江(asai)は尾張(oda)と隣接。asai は初期から近江のみ。
    assert rules.provinces_of(st, "asai") == ["omi"]
    st["provinces"]["owari"]["troops"] = 300
    st["provinces"]["omi"]["troops"] = 3
    st["houses"]["asai"]["gold"] = 90
    oda_gold0 = st["houses"]["oda"]["gold"]
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "omi", "troops": 250}, _rng()
    )
    assert st2["provinces"]["omi"]["owner"] == "oda"
    assert st2["houses"]["asai"]["alive"] is False
    # 浅井の金(90)を織田が接収
    assert st2["houses"]["asai"]["gold"] == 0
    assert st2["houses"]["oda"]["gold"] == oda_gold0 + 90
    assert "接収" in " ".join(e["text"] for e in st2["log"])


def test_conquest_not_eliminating_does_not_transfer_gold():
    st = rules.new_game("oda")
    # 今川は3国。三河を1つ取っても滅亡しないので金は移らない。
    st["provinces"]["owari"]["troops"] = 300
    st["provinces"]["mikawa"]["troops"] = 3
    imagawa_gold0 = st["houses"]["imagawa"]["gold"]
    oda_gold0 = st["houses"]["oda"]["gold"]
    st2 = rules.apply_command(
        st, "oda", {"type": "invade", "from": "owari", "to": "mikawa", "troops": 250}, _rng()
    )
    assert st2["provinces"]["mikawa"]["owner"] == "oda"
    assert st2["houses"]["imagawa"]["alive"] is True
    assert st2["houses"]["imagawa"]["gold"] == imagawa_gold0
    assert st2["houses"]["oda"]["gold"] == oda_gold0


def test_check_status_win_and_loss():
    st = rules.new_game("oda")
    for pid, p in st["provinces"].items():
        p["owner"] = "oda"
    for hid in st["houses"]:
        if hid != "oda":
            st["houses"][hid]["alive"] = False
    won = rules.check_status(st)
    assert won["status"] == "won"

    st2 = rules.new_game("oda")
    st2["houses"]["oda"]["alive"] = False
    lost = rules.check_status(st2)
    assert lost["status"] == "lost"


def test_advance_season_wraps_turn():
    st = rules.new_game("oda")
    st["season_index"] = len(rules.SEASONS) - 1  # 冬
    st2 = rules.advance_season(st)
    assert st2["season_index"] == 0
    assert st2["turn"] == 2


def test_heuristic_prefers_strong_invasion():
    st = rules.new_game("oda")
    # 尾張を強大にし、隣接の三河(今川)を手薄にする
    st["provinces"]["owari"]["troops"] = 200
    st["provinces"]["mikawa"]["troops"] = 10
    cmd = rules.heuristic_command(st, "oda", _rng())
    assert cmd["type"] == "invade"
    assert cmd["to"] == "mikawa"


def test_heuristic_recruits_when_threatened():
    st = rules.new_game("oda")
    # 全隣接を強くして侵攻は無理、かつ脅威にする
    for pid in st["provinces"]:
        if st["provinces"][pid]["owner"] != "oda":
            st["provinces"][pid]["troops"] = 500
    st["provinces"]["owari"]["troops"] = 10
    st["provinces"]["ise"]["troops"] = 10
    cmd = rules.heuristic_command(st, "oda", _rng())
    assert cmd["type"] in ("recruit", "develop")


def test_heuristic_rest_when_broke():
    st = rules.new_game("oda")
    st["houses"]["oda"]["gold"] = 0
    # 侵攻できないよう隣接を強大に
    for pid in st["provinces"]:
        if st["provinces"][pid]["owner"] != "oda":
            st["provinces"][pid]["troops"] = 999
    # 兵も上限にして徴兵の余地なし
    for pid in rules.provinces_of(st, "oda"):
        st["provinces"][pid]["troops"] = rules.troops_cap(st["provinces"][pid]["kokudaka"])
    cmd = rules.heuristic_command(st, "oda", _rng())
    assert cmd["type"] == "rest"
