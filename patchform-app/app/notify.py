"""職員向けの申請到着メール。回答本文は載せない。"""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from typing import Any

def _truthy(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().lower() in ("1", "true", "yes", "on")


def smtp_host() -> str:
    return (os.environ.get("PATCHFORM_SMTP_HOST") or "").strip()


def smtp_from() -> str:
    return (os.environ.get("PATCHFORM_SMTP_FROM") or "").strip()


def smtp_configured() -> bool:
    return bool(smtp_host() and smtp_from())


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
    msg["From"] = smtp_from()
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    return msg


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
    if not smtp_configured():
        return {"sent": False, "reason": "smtp_unconfigured"}
    dest = [addr for addr in (recipients or []) if addr]
    if not dest:
        return {"sent": False, "reason": "no_recipients"}
    message = build_staff_message(
        procedure_name=str(
            procedure_name or application.get("procedure_name") or ""
        ),
        token=str(application.get("token") or ""),
        application_id=str(application.get("id") or ""),
        recipients=dest,
    )
    try:
        send_email(message)
    except Exception as exc:  # noqa: BLE001
        print(f"[patchform] notify failed: {exc}")
        return {"sent": False, "reason": "send_failed"}
    return {"sent": True, "recipients": dest}
