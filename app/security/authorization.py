"""Sender authorization allowlist.

Supports Telegram user IDs (integers) via TELEGRAM_ALLOWED_USER_IDS.
Unauthorized senders are rejected silently: no response is sent.
"""

from __future__ import annotations

from app.config import config


def is_sender_authorized(sender_id: str) -> bool:
    """Return True if the sender (Telegram chat/user ID) is on the allowlist."""
    if not sender_id:
        return False
    normalized = str(sender_id).strip()

    # Check parsed integer list
    allowed_tg = getattr(config, "allowed_telegram_user_ids", None)
    if allowed_tg:
        try:
            if int(normalized) in allowed_tg:
                return True
        except ValueError:
            pass

    # Check raw comma-separated string
    raw_tg = getattr(config, "telegram_allowed_user_ids", "") or ""
    if raw_tg:
        if isinstance(raw_tg, str):
            tg_items = [s.strip() for s in raw_tg.split(",") if s.strip()]
        else:
            tg_items = [str(s).strip() for s in raw_tg if str(s).strip()]
        if normalized in tg_items:
            return True

    return False


def is_telegram_user_authorized(user_id: int) -> bool:
    """Return True if the Telegram user ID is on the allowlist."""
    if not getattr(config, "telegram_allowed_user_ids", None):
        return False
    allowed = getattr(config, "allowed_telegram_user_ids", None)
    if allowed is not None:
        return user_id in allowed
    raw = str(config.telegram_allowed_user_ids)
    return str(user_id) in [s.strip() for s in raw.split(",") if s.strip()]