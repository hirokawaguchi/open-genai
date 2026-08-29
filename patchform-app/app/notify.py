"""職員向けの申請到着メール。回答本文は載せない。"""

from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

def _truthy(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().lower() in ("1", "true", "yes", "on")


def smtp_host() -> str:
    return (os.environ.get("PATCHFORM_SMTP_HOST") or "").strip()


def smtp_from() -> str:
    return (os.environ.get("PATCHFORM_SMTP_FROM") or "").strip()


def dump_dir() -> Path | None:
    raw = (os.environ.get("PATCHFORM_MAIL_DUMP_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw)


def smtp_configured() -> bool:
    return bool(smtp_host() and smtp_from())


def mail_configured() -> bool:
    return smtp_configured() or dump_dir() is not None


def mail_status() -> dict[str, bool]:
    return {
        "configured": mail_configured(),
        "smtp": smtp_configured(),
        "dump": dump_dir() is not None,
    }


def staff_base_url() -> str:
    return (
        os.environ.get("PATCHFORM_STAFF_BASE_URL") or os.environ.get("PUBLIC_URL") or ""
    ).rstrip("/")


def parse_notify_emails(raw: Any) -> tuple[list[str] | None, str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                raw = parsed
            else:
                raw = raw.replace("、", ",").replace(";", ",")
                raw = [part.strip() for part in raw.replace("\n", ",").split(",")]
        except (json.JSONDecodeError, TypeError):
            raw = raw.replace("、", ",").replace(";", ",")
            raw = [part.strip() for part in raw.replace("\n", ",").split(",")]
    if not isinstance(raw, list):
        return None, "通知先の形式が不正です"
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        addr = str(item or "").strip()
        if not addr:
            continue
        if "@" not in addr or addr.startswith("@") or addr.endswith("@") or " " in addr:
            return None, f"メールアドレスの形式が不正です（{addr}）"
        if len(addr) > 254:
            return None, "メールアドレスが長すぎます"
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
        if len(out) > 20:
            return None, "通知先は20件までです"
    return out, None


def application_url(application_id: str) -> str:
    base = staff_base_url()
    if not base or not application_id:
        return ""
    return f"{base}/patchform/applications/{application_id}"


def public_base_url() -> str:
    """庁外（公開）SPA の到達先ベースURL。"""
    return (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")


def magic_link_url(token: str) -> str:
    from urllib.parse import quote

    base = public_base_url()
    path = f"/public/auth/verify?token={quote(token)}"
    return f"{base}{path}" if base else path


def build_magic_link_message(*, email: str, token: str) -> EmailMessage:
    link = magic_link_url(token)
    lines = [
        "マイ手続きにログインするためのリンクです。",
        "",
        "下のリンクを開くとログインが完了します（有効期限あり・1回のみ有効）。",
        "",
        link,
        "",
        "このメールに心当たりがない場合は破棄してください。",
    ]
    msg = EmailMessage()
    msg["Subject"] = "【マイ手続き】ログイン用リンク"
    msg["From"] = smtp_from() or "patchform@localhost"
    msg["To"] = email
    msg.set_content("\n".join(lines))
    return msg


def send_magic_link(*, email: str, token: str) -> dict[str, Any]:
    """マジックリンクを送信（SMTP）またはダンプ（dev）する。"""
    dest = (email or "").strip()
    if not dest:
        return {"sent": False, "reason": "no_recipient"}
    if not mail_configured():
        # メール未設定でも dev では動作確認できるよう、リンクをログ出力する。
        print(f"[patchform] magic link for {dest}: {magic_link_url(token)}")
        return {"sent": False, "reason": "smtp_unconfigured"}
    message = build_magic_link_message(email=dest, token=token)
    dumped: str | None = None
    if dump_dir() is not None:
        try:
            dumped = str(dump_email(message, token=dest))
        except Exception as exc:  # noqa: BLE001
            print(f"[patchform] magic link dump failed: {exc}")
            if not smtp_configured():
                return {"sent": False, "reason": "dump_failed"}
    if smtp_configured():
        try:
            send_email(message)
        except Exception as exc:  # noqa: BLE001
            print(f"[patchform] magic link send failed: {exc}")
            return {"sent": False, "reason": "send_failed", "dumped": dumped}
        return {"sent": True, "dumped": dumped}
    return {"sent": False, "reason": "dumped", "dumped": dumped}


def build_staff_message(
    *,
    procedure_name: str,
    token: str,
    application_id: str,
    recipients: list[str],
) -> EmailMessage:
    title = (procedure_name or "手続き").strip() or "手続き"
    code = (token or "").strip()
    link = application_url(application_id)
    lines = [
        f"「{title}」に申請が1件届きました。",
        "",
        f"案内番号: {code}" if code else "案内番号: （なし）",
    ]
    if link:
        lines.extend(["", "申請受付:", link])
    lines.extend(
        [
            "",
            "回答の内容はこのメールには書いていません。上のリンクから確認してください。",
        ]
    )
    msg = EmailMessage()
    msg["Subject"] = f"【フォーム】申請が届きました（{title}）"
    msg["From"] = smtp_from() or "patchform@localhost"
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    return msg


def message_as_text(message: EmailMessage) -> str:
    parts = [
        f"From: {message.get('From') or ''}",
        f"To: {message.get('To') or ''}",
        f"Subject: {message.get('Subject') or ''}",
        "",
        message.get_content(),
    ]
    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (cleaned or "mail")[:80]


def dump_email(message: EmailMessage, *, token: str = "", application_id: str = "") -> Path:
    dest = dump_dir()
    if dest is None:
        raise RuntimeError("PATCHFORM_MAIL_DUMP_DIR が未設定です")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = _safe_name(token or application_id or "application")
    path = dest / f"{stamp}_{name}.txt"
    text = message_as_text(message)
    path.write_text(text, encoding="utf-8")
    print(f"[patchform] mail dump: {path}\n{text}")
    return path


def send_email(message: EmailMessage) -> None:
    host = smtp_host()
    port = int(os.environ.get("PATCHFORM_SMTP_PORT") or "587")
    user = (os.environ.get("PATCHFORM_SMTP_USER") or "").strip()
    password = os.environ.get("PATCHFORM_SMTP_PASSWORD") or ""
    timeout = float(os.environ.get("PATCHFORM_SMTP_TIMEOUT") or "10")
    if _truthy("PATCHFORM_SMTP_SSL"):
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    try:
        if _truthy("PATCHFORM_SMTP_STARTTLS", "1") and not _truthy("PATCHFORM_SMTP_SSL"):
            client.starttls()
        if user:
            client.login(user, password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001
            client.close()


def notify_new_application(
    application: dict[str, Any] | None,
    *,
    recipients: list[str] | None = None,
    procedure_name: str | None = None,
) -> dict[str, Any]:
    if not application:
        return {"sent": False, "reason": "no_application"}
    dest = [addr for addr in (recipients or []) if addr]
    if not dest:
        return {"sent": False, "reason": "no_recipients"}
    if not mail_configured():
        return {"sent": False, "reason": "smtp_unconfigured"}
    message = build_staff_message(
        procedure_name=str(
            procedure_name or application.get("procedure_name") or ""
        ),
        token=str(application.get("token") or ""),
        application_id=str(application.get("id") or ""),
        recipients=dest,
    )
    dumped: str | None = None
    if dump_dir() is not None:
        try:
            dumped = str(
                dump_email(
                    message,
                    token=str(application.get("token") or ""),
                    application_id=str(application.get("id") or ""),
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[patchform] mail dump failed: {exc}")
            if not smtp_configured():
                return {"sent": False, "reason": "dump_failed"}
    if smtp_configured():
        try:
            send_email(message)
        except Exception as exc:  # noqa: BLE001
            print(f"[patchform] notify failed: {exc}")
            return {"sent": False, "reason": "send_failed", "dumped": dumped}
        return {"sent": True, "recipients": dest, "dumped": dumped}
    return {"sent": False, "reason": "dumped", "dumped": dumped, "recipients": dest}
