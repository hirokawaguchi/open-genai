"""初期サンプル。ナビゲーション無しの単一申請用紙。"""

from __future__ import annotations

import json
import os

from . import spec, store

SAMPLE_FORM_TITLE = "【サンプル】ご意見・お問い合わせ"
SAMPLE_PROC_NAME = "【サンプル】ご意見・お問い合わせ"
SEED_USER = "seed"


def seed_enabled() -> bool:
    return os.environ.get("PATCHFORM_SEED", "").strip().lower() in ("1", "true", "yes")


def _sample_definition() -> dict:
    raw = spec.empty_definition(
        SAMPLE_FORM_TITLE,
        "ご意見やお問い合わせを受け付けます。追加の申請用紙はありません。",
    )
    raw["components"] = [
        {
            "id": "intro",
            "type": "text_display",
            "label": "案内",
            "properties": {
                "text": "この手続きは申請用紙1枚だけです。ナビゲーションフォームは使いません。",
            },
        },
        {
            "id": "name",
            "type": "text",
            "label": "お名前",
            "required": True,
            "placeholder": "例: 山田 太郎",
        },
        {
            "id": "email",
            "type": "email",
            "label": "メールアドレス",
            "required": True,
        },
        {
            "id": "body",
            "type": "textarea",
            "label": "ご意見・お問い合わせ",
            "required": True,
            "placeholder": "内容を入力してください",
        },
    ]
    return raw


def _existing_procedure_id() -> str | None:
    db = store.connect()
    with store._lock:
        row = db.execute(
            "SELECT id FROM procedures WHERE name = ?",
            (SAMPLE_PROC_NAME,),
        ).fetchone()
        return str(row["id"]) if row else None


def _existing_form_id() -> str | None:
    db = store.connect()
    with store._lock:
        row = db.execute(
            "SELECT id FROM forms WHERE title = ? AND (source_form_id IS NULL OR source_form_id = '')",
            (SAMPLE_FORM_TITLE,),
        ).fetchone()
        return str(row["id"]) if row else None


SAMPLE_PROC_DESC = "ナビゲーションフォームは使いません。申請用紙はこの1枚だけです。"


def _retouch_sample() -> None:
    """既存サンプルから「ナビゲーション」タグを外す。"""
    db = store.connect()
    with store._lock:
        for row in db.execute(
            "SELECT id, tags FROM forms WHERE title = ?",
            (SAMPLE_FORM_TITLE,),
        ).fetchall():
            raw = []
            try:
                raw = json.loads(row["tags"] or "[]")
            except (TypeError, json.JSONDecodeError):
                raw = []
            tags, _err = store.normalize_tags(raw if isinstance(raw, list) else [])
            next_tags = [t for t in (tags or []) if t != store.NAVIGATION_TAG]
            if "サンプル" not in next_tags:
                next_tags.append("サンプル")
            if next_tags != (tags or []):
                db.execute(
                    "UPDATE forms SET tags = ? WHERE id = ?",
                    (json.dumps(next_tags, ensure_ascii=False), row["id"]),
                )
        db.execute(
            "UPDATE procedures SET description = ? WHERE name = ?",
            (SAMPLE_PROC_DESC, SAMPLE_PROC_NAME),
        )
        db.commit()


def ensure_sample_data() -> str | None:
    """単一フォームの手続きが無ければ作る。既にあればタグだけ直す。"""
    existing = _existing_procedure_id()
    if existing:
        _retouch_sample()
        return None
    form_id = _existing_form_id()
    if not form_id:
        form, err = store.create_form(
            title=SAMPLE_FORM_TITLE,
            description="ご意見やお問い合わせを受け付けます。追加の申請用紙はありません。",
            creator_user_id=SEED_USER,
            creator_name="初期データ",
            visibility="both",
            definition=_sample_definition(),
            tags=["サンプル", "ご意見"],
        )
        if err or form is None:
            print(f"[patchform] sample form skipped: {err}")
            return None
        form_id = form["id"]
    proc, perr = store.create_procedure(
        name=SAMPLE_PROC_NAME,
        description=SAMPLE_PROC_DESC,
        guide_form_id=form_id,
        mapping={"rules": []},
        creator_user_id=SEED_USER,
        creator_name="初期データ",
    )
    if perr or proc is None:
        print(f"[patchform] sample procedure skipped: {perr}")
        return None
    published, serr = store.set_procedure_status(
        proc["id"], actor_user_id=SEED_USER, status="published"
    )
    if serr:
        print(f"[patchform] sample procedure left as draft: {serr}")
        return proc["id"]
    print(f"[patchform] sample procedure ready id={published['id'] if published else proc['id']}")
    return (published or proc)["id"]
