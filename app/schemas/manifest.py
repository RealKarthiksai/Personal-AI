"""Retrieval Manifest schema and disclosure renderer for Karna.

Provides structured, empirical accounting of per-source retrieval statuses
(ok, empty, error, unconfigured, rate_limited, timeout) and latencies.
Guarantees that disclosures in user responses are generated deterministically
by code from runtime facts, never by the LLM.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SourceStatus(str, Enum):
    """Execution status of an individual external source."""

    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    UNCONFIGURED = "unconfigured"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"


class SourceOrigin(str, Enum):
    """Where the retrieved candidate records originated."""

    LIVE = "live"
    CACHE = "cache"
    DATABASE = "database"
    ADHOC = "adhoc"


class SourceManifestEntry(BaseModel):
    """Per-source accounting of items, status, and latency."""

    source: str
    status: SourceStatus
    origin: SourceOrigin = SourceOrigin.LIVE
    count: int = 0  # Number of items returned upstream
    latency_ms: float = 0.0
    error_code: Optional[str] = None
    authenticated: Optional[bool] = None


class RetrievalManifest(BaseModel):
    """Unified retrieval manifest tracking full audit trail for a turn."""

    requested_count: Optional[int] = None
    retrieved_count: int = 0
    shown_count: int = 0
    sources: Dict[str, SourceManifestEntry] = Field(default_factory=dict)
    topic_counts: Dict[str, int] = Field(default_factory=dict)
    allowed_urls: List[str] = Field(default_factory=list)


def render_manifest_disclosure(manifest: RetrievalManifest) -> str:
    """Deterministically render a concise HTML footnote disclosure from manifest facts."""
    if not manifest.sources and not manifest.topic_counts:
        return ""

    parts: List[str] = []

    # Count claim
    if manifest.requested_count is not None:
        parts.append(f"Showing {manifest.shown_count} items (requested {manifest.requested_count}).")
    else:
        parts.append(f"Showing {manifest.shown_count} items.")

    # Source breakdown
    src_parts: List[str] = []
    for name, entry in manifest.sources.items():
        src_label = name.capitalize()
        if entry.status == SourceStatus.OK:
            src_parts.append(f"{src_label}: {entry.count} ok")
        elif entry.status == SourceStatus.EMPTY:
            src_parts.append(f"{src_label}: 0 found")
        elif entry.status == SourceStatus.UNCONFIGURED:
            src_parts.append(f"{src_label}: unconfigured")
        elif entry.status == SourceStatus.RATE_LIMITED:
            src_parts.append(f"{src_label}: rate limited")
        elif entry.status == SourceStatus.TIMEOUT:
            src_parts.append(f"{src_label}: timeout")
        else:
            code = entry.error_code or "failed"
            src_parts.append(f"{src_label}: error ({code})")

    if src_parts:
        parts.append(f"Sources: {'; '.join(src_parts)}.")

    # Topic coverage if applicable
    unconfigured_topics = [t for t, count in manifest.topic_counts.items() if count == 0]
    if unconfigured_topics:
        parts.append(f"No configured sources for: {', '.join(unconfigured_topics)}.")

    return "\n\n───\n📊 <b>Retrieval Summary</b>\n" + " ".join(parts)
