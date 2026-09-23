from app.kcadmin import (
    build_user_representation,
    email_change_forbidden,
    parse_csv,
    plan_rows,
    validate_row,
)


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


def test_csv_tenant_column_is_parsed() -> None:
    rows = parse_csv("username,tenant\nyamada,能代市役所\n")
    assert rows == [{"username": "yamada", "tenant": "能代市役所"}]
    # 別名（棟）でも同じキーに正規化する
    rows2 = parse_csv("username,棟\nyamada,能代市役所\n")
    assert rows2 == [{"username": "yamada", "tenant": "能代市役所"}]


def test_explicit_empty_first_name_is_written() -> None:
    rep = build_user_representation(
        {"username": "yamada", "lastName": "山田", "firstName": ""}
    )
    assert rep["lastName"] == "山田"
    assert rep["firstName"] == ""


def test_omitted_first_name_is_left_unset() -> None:
    rep = build_user_representation({"username": "yamada", "lastName": "山田"})
    assert rep["lastName"] == "山田"
    assert "firstName" not in rep


def test_email_is_required() -> None:
    assert validate_row({"username": "yamada", "action": "create"}) == "メールアドレスは必須です"


def test_same_email_ignores_case_and_space() -> None:
    assert email_change_forbidden(" Hiro@example.com ", "hiro@example.com") is False


def test_different_email_is_forbidden() -> None:
    assert email_change_forbidden("hiro@kawaguchi.com", "new@kawaguchi.com") is True


def test_plan_rows_keep_groups_mode() -> None:
    rows = parse_csv(
        "username,email,groups,groupsMode\nyamada,yamada@example.com,UserGroup,replace\n"
    )
    plans = plan_rows(rows)
    assert plans[0]["groupsMode"] == "replace"
    assert plans[0]["groups"] == ["UserGroup"]


def test_plan_rows_echo_tenant_and_email() -> None:
    rows = parse_csv(
        "action,username,email,tenant\ncreate,yamada,yamada@example.com,能代市役所\n"
    )
    plans = plan_rows(rows)
    assert plans[0]["tenant"] == "能代市役所"
    assert plans[0]["email"] == "yamada@example.com"
    assert plans[0]["error"] is None
