"""Data structures representing structural blocks of a message."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Block:
    """Base class for all structural message blocks."""
    pass


@dataclass
class HeadingBlock(Block):
    level: int  # 1 for #, 2 for ##, 3 for ###, etc.
    text: str


@dataclass
class ParagraphBlock(Block):
    text: str


@dataclass
class TableBlock(Block):
    headers: List[str]
    rows: List[List[str]]


@dataclass
class ListItem:
    text: str
    level: int = 0
    index: Optional[int] = None  # None for unordered, 1, 2, 3... for ordered


@dataclass
class ListBlock(Block):
    items: List[ListItem] = field(default_factory=list)
    ordered: bool = False


@dataclass
class CodeBlock(Block):
    language: str
    code: str


@dataclass
class DividerBlock(Block):
    pass


@dataclass
class QuoteBlock(Block):
    text: str


@dataclass
class Document:
    blocks: List[Block] = field(default_factory=list)
    raw_text: Optional[str] = None
