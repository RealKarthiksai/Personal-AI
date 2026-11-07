"""Lightweight data models representing persisted rows and tool entities.

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


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: Optional[str] = None


@dataclass
class ExtractedContent:
    url: str
    title: str
    markdown: str
    success: bool = True
    error: Optional[str] = None
    raw_html: Optional[str] = None


@dataclass
class SearchCacheRow:
    query_hash: str
    query: str
    results_json: str
    created_at: Optional[str] = None


@dataclass
class PageCacheRow:
    url_hash: str
    url: str
    title: str
    markdown_content: str
    created_at: Optional[str] = None


@dataclass
class ToolExecutionLog:
    id: Optional[int]
    tool_name: str
    input_data: str
    output_summary: str
    duration_ms: float
    created_at: Optional[str] = None