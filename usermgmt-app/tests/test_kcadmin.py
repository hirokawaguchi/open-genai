from app.kcadmin import build_user_representation, parse_csv


def test_split_space_separated_name_as_family_then_given() -> None:
    rep = build_user_representation({"username": "yamada", "name": "山田 太郎"})
    assert rep["lastName"] == "山田"
    assert rep["firstName"] == "太郎"


def test_single_token_name_goes_to_last_name() -> None:
    rep = build_user_representation({"username": "admin", "name": "管理者"})
    assert rep["lastName"] == "管理者"
    assert "firstName" not in rep


def test_explicit_first_last_are_kept() -> None:
    rep = build_user_representation(
        {"username": "yamada", "firstName": "太郎", "lastName": "山田"}
    )
    assert rep["lastName"] == "山田"
    assert rep["firstName"] == "太郎"


def test_csv_japanese_headers() -> None:
    rows = parse_csv("username,姓,名\nyamada,山田,太郎\n")
    assert rows == [{"username": "yamada", "lastName": "山田", "firstName": "太郎"}]
