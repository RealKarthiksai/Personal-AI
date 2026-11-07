"""Data models and enums for the long-term memory subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryTier(str, Enum):
    """Memory retention tiers."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    CORE = "core"


class MemorySource(str, Enum):
    """Origin of a memory item."""

    EXPLICIT = "explicit"
    RULE = "rule"
    LLM = "llm"
    MERGED = "merged"


class FactCategory(str, Enum):
    """Categorization for extracted user facts."""

    IDENTITY = "identity"
    PREFERENCE = "preference"
    PROJECT = "project"
    PERSON = "person"
    WORK = "work"
    HEALTH = "health"
    EVENT = "event"
    INTEREST = "interest"
    GENERAL = "general"


@dataclass
class MemoryItem:
    """An individual memory record."""

    id: Optional[int] = None
    user_id: int = 0
    tier: MemoryTier = MemoryTier.DAILY
    period: str = ""
    text: str = ""
    importance: int = 1
    confidence: float = 1.0
    category: str = "general"
    source: MemorySource = MemorySource.RULE
    source_message_ids: List[int] = field(default_factory=list)
    source_snippet: Optional[str] = None
    source_channels: List[str] = field(default_factory=list)
    pinned: bool = False
    access_count: int = 0
    last_accessed_at: Optional[str] = None
    superseded_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


@dataclass
class ProfileFieldItem:
    """A structured profile attribute for a user."""

    id: Optional[int] = None
    user_id: int = 0
    key: str = ""
    value: Any = None
    confidence: float = 1.0
    confirmed: bool = False
    source_memory_id: Optional[int] = None
    updated_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtractedFact:
    """A candidate fact extracted from user communication."""

    text: str
    category: str
    importance: int
    confidence: float = 1.0
    source_snippet: str = ""
    source_message_id: Optional[int] = None
    profile_key: Optional[str] = None
    profile_value: Optional[str] = None


@dataclass
class UserIdentity:
    """Channel binding to a canonical user entity."""

    user_id: int
    channel: str
    external_user_id: str
    display_name: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    locale: Optional[str] = None
