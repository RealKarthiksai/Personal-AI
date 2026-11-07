"""Lightweight data models representing persisted rows.

Plain dataclasses keep this module dependency-free (stdlib only).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Sender:
    id: Optional[int]
    phone_number_id: str
    created_at: Optional[str] = None


@dataclass
class Message:
    id: Optional[int]
    external_message_id: Optional[str]
    sender_id: str
    direction: str  # 'inbound' or 'outbound'
    text: str
    timestamp: Optional[str] = None
    status: str = "received"
    created_at: Optional[str] = None