"""Cross-channel identity resolution and account linking."""

from __future__ import annotations

import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database.database import transaction
from app.utils.logging import get_logger

logger = get_logger("app.memory.identity")


def resolve_user_id(
    channel: str,
    external_user_id: str,
    display_name: Optional[str] = None,
) -> int:
    """Resolve an incoming channel identity to a canonical user_id.

    Creates a new user and identity mapping if first seen.
    """
    clean_channel = channel.strip().lower()
    clean_ext_id = str(external_user_id).strip()

    with transaction() as conn:
        # Check existing identity
        row = conn.execute(
            """
            SELECT user_id FROM identities
            WHERE channel = ? AND external_user_id = ?
            """,
            (clean_channel, clean_ext_id),
        ).fetchone()

        if row:
            return int(row["user_id"])

        # Create new user
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cur = conn.execute(
            """
            INSERT INTO users (display_name, timezone, created_at)
            VALUES (?, 'Asia/Kolkata', ?)
            """,
            (display_name, now_utc),
        )
        new_user_id = cur.lastrowid
        if new_user_id is None:
            raise RuntimeError("Failed to create new user record")

        # Map channel identity
        conn.execute(
            """
            INSERT INTO identities (user_id, channel, external_user_id, verified, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (new_user_id, clean_channel, clean_ext_id, now_utc),
        )
        logger.info(
            "Created canonical user %d for channel=%s external_id=%s",
            new_user_id,
            clean_channel,
            clean_ext_id,
        )
        return int(new_user_id)


def generate_link_code(user_id: int, expiry_minutes: int = 10) -> str:
    """Generate a one-time 6-digit numeric pairing code for cross-channel linking."""
    # Cryptographically secure 6-digit code
    code = f"{secrets.randbelow(900000) + 100000:06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO link_codes (code, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (code, user_id, expires_at),
        )
    return code


def redeem_link_code(
    code: str,
    channel: str,
    external_user_id: str,
    now: Optional[datetime] = None,
) -> Tuple[bool, str, Optional[int]]:
    """Redeem a pairing code to attach this channel identity to the target user_id.

    Returns (success, message, target_user_id).
    """
    clean_code = code.strip()
    clean_channel = channel.strip().lower()
    clean_ext_id = str(external_user_id).strip()
    current_time = now or datetime.now(timezone.utc)
    current_iso = current_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    with transaction() as conn:
        row = conn.execute(
            """
            SELECT code, user_id, expires_at, used_at FROM link_codes
            WHERE code = ?
            """,
            (clean_code,),
        ).fetchone()

        if not row:
            return False, "Invalid linking code.", None

        if row["used_at"] is not None:
            return False, "This linking code has already been used.", None

        if row["expires_at"] < current_iso:
            return False, "This linking code has expired.", None

        target_user_id = int(row["user_id"])

        # Check if already linked
        existing = conn.execute(
            """
            SELECT user_id FROM identities
            WHERE channel = ? AND external_user_id = ?
            """,
            (clean_channel, clean_ext_id),
        ).fetchone()

        if existing:
            if int(existing["user_id"]) == target_user_id:
                return True, "This channel identity is already linked to your account.", target_user_id
            # Move identity to the new target user_id
            conn.execute(
                """
                UPDATE identities SET user_id = ?
                WHERE channel = ? AND external_user_id = ?
                """,
                (target_user_id, clean_channel, clean_ext_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO identities (user_id, channel, external_user_id, verified, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (target_user_id, clean_channel, clean_ext_id, current_iso),
            )

        # Mark code as used
        conn.execute(
            """
            UPDATE link_codes SET used_at = ? WHERE code = ?
            """,
            (current_iso, clean_code),
        )

        logger.info(
            "Linked identity channel=%s ext_id=%s to user_id=%d",
            clean_channel,
            clean_ext_id,
            target_user_id,
        )
        return True, "Successfully linked this channel to your account!", target_user_id


def get_user_identities(user_id: int) -> List[Dict[str, Any]]:
    """Return all linked identities for a given user."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT channel, external_user_id, verified, created_at
            FROM identities WHERE user_id = ?
            ORDER BY created_at ASC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
