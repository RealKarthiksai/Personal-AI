"""Structured information extraction service for hackathons and events.

Provides hybrid extraction:
1. Fast, deterministic rule-based table and listing parser (0ms latency).
2. Schema-constrained model-assisted fallback using local LLM if tables are absent.
3. Persistence to SQLite extracted_entities table.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import List, Optional
from urllib.parse import urlparse

from app.database.repository import save_extracted_entity
from app.schemas.entities import Hackathon
from app.services.llm_client import LLMClient
from app.utils.logging import get_logger

logger = get_logger("app.structured_extractor")

MARKDOWN_LINK_REGEX = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")


def _clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip().strip("|").strip()
    return s if s else None


def _extract_url_from_cell(cell: str) -> tuple[str, Optional[str]]:
    """Extract plain text and link from cell if it contains a markdown link."""
    match = MARKDOWN_LINK_REGEX.search(cell)
    if match:
        text, url = match.group(1).strip(), match.group(2).strip()
        return text, url
    return cell.strip(), None


class StructuredExtractor:
    """Extracts and validates structured event entities from extracted web content."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def parse_markdown_tables(self, markdown_text: str, source_url: str) -> List[Hackathon]:
        """Extract hackathons from Markdown tables."""
        hackathons: List[Hackathon] = []
        lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("|") and line.endswith("|") and i + 1 < len(lines):
                next_line = lines[i + 1]
                # Check for table header separator (e.g. |---|---|)
                if re.match(r"^\|(\s*:?-+:?\s*\|)+$", next_line):
                    header_cells = [
                        c.strip().lower() for c in line.split("|")[1:-1]
                    ]
                    
                    # Map column indexes
                    col_map: dict[str, int] = {}
                    for idx, cell in enumerate(header_cells):
                        if any(k in cell for k in ("name", "event", "title", "hackathon", "competition")):
                            col_map["name"] = idx
                        elif any(k in cell for k in ("organizer", "host", "college", "company", "by")):
                            col_map["organizer"] = idx
                        elif any(k in cell for k in ("deadline", "last date", "reg end", "apply by")):
                            col_map["deadline"] = idx
                        elif any(k in cell for k in ("date", "schedule", "when", "timing", "held")):
                            col_map["event_date"] = idx
                        elif any(k in cell for k in ("location", "venue", "city", "mode")):
                            col_map["location"] = idx
                        elif any(k in cell for k in ("eligibility", "participants", "who can")):
                            col_map["eligibility"] = idx
                        elif any(k in cell for k in ("prize", "cash", "rewards", "award")):
                            col_map["prize"] = idx
                        elif any(k in cell for k in ("link", "url", "register", "apply")):
                            col_map["registration_url"] = idx

                    # Only proceed if we at least matched an event name
                    if "name" in col_map:
                        i += 2
                        while i < len(lines) and lines[i].startswith("|") and lines[i].endswith("|"):
                            row_cells = [c.strip() for c in lines[i].split("|")[1:-1]]
                            name_idx = col_map["name"]
                            if name_idx < len(row_cells):
                                raw_name = row_cells[name_idx]
                                clean_name, embedded_url = _extract_url_from_cell(raw_name)
                                
                                if clean_name and len(clean_name) > 2 and not clean_name.startswith("---"):
                                    organizer = _clean_text(row_cells[col_map["organizer"]]) if "organizer" in col_map and col_map["organizer"] < len(row_cells) else None
                                    deadline = _clean_text(row_cells[col_map["deadline"]]) if "deadline" in col_map and col_map["deadline"] < len(row_cells) else None
                                    event_date = _clean_text(row_cells[col_map["event_date"]]) if "event_date" in col_map and col_map["event_date"] < len(row_cells) else None
                                    location = _clean_text(row_cells[col_map["location"]]) if "location" in col_map and col_map["location"] < len(row_cells) else None
                                    eligibility = _clean_text(row_cells[col_map["eligibility"]]) if "eligibility" in col_map and col_map["eligibility"] < len(row_cells) else None
                                    prize = _clean_text(row_cells[col_map["prize"]]) if "prize" in col_map and col_map["prize"] < len(row_cells) else None
                                    
                                    reg_url = None
                                    if "registration_url" in col_map and col_map["registration_url"] < len(row_cells):
                                        _, reg_url = _extract_url_from_cell(row_cells[col_map["registration_url"]])
                                    if not reg_url:
                                        reg_url = embedded_url

                                    hackathons.append(
                                        Hackathon(
                                            name=clean_name,
                                            organizer=organizer,
                                            deadline=deadline,
                                            event_date=event_date,
                                            location=location,
                                            eligibility=eligibility,
                                            prize=prize,
                                            registration_url=reg_url,
                                            source_url=source_url,
                                            confidence="HIGH",
                                        )
                                    )
                            i += 1
                        continue
            i += 1
        return hackathons

    def parse_listing_blocks(self, markdown_text: str, source_url: str) -> List[Hackathon]:
        """Extract hackathons from list-based or heading-based cards (e.g. Unstop, Devfolio)."""
        hackathons: List[Hackathon] = []
        
        # Pattern 1: Heading cards (### Hackathon Name \n Date: ... \n Location: ...)
        card_chunks = re.split(r"\n#{2,4}\s+", markdown_text)
        for chunk in card_chunks[1:]:
            lines = chunk.strip().splitlines()
            if not lines:
                continue
            raw_title = lines[0].strip()
            title, link = _extract_url_from_cell(raw_title)
            
            # Check if title looks like an event or hackathon
            title_lower = title.lower()
            if any(k in title_lower for k in ("hack", "challenge", "code", "dev", "tech", "thon", "summit")):
                chunk_text = "\n".join(lines[1:])
                date_match = re.search(r"(?:Date|When|Schedule|Dates)\s*:\s*([^\n]+)", chunk_text, re.I)
                deadline_match = re.search(r"(?:Deadline|Apply by|Last Date)\s*:\s*([^\n]+)", chunk_text, re.I)
                location_match = re.search(r"(?:Location|Venue|Mode)\s*:\s*([^\n]+)", chunk_text, re.I)
                prize_match = re.search(r"(?:Prize|Prizes|Rewards?|Cash)\s*:\s*([^\n]+)", chunk_text, re.I)
                reg_match = MARKDOWN_LINK_REGEX.search(chunk_text)
                
                reg_url = link or (reg_match.group(2) if reg_match else None)
                
                hackathons.append(
                    Hackathon(
                        name=title,
                        organizer=None,
                        deadline=deadline_match.group(1).strip() if deadline_match else None,
                        event_date=date_match.group(1).strip() if date_match else None,
                        location=location_match.group(1).strip() if location_match else None,
                        eligibility=None,
                        prize=prize_match.group(1).strip() if prize_match else None,
                        registration_url=reg_url,
                        source_url=source_url,
                        confidence="HIGH",
                    )
                )

        return hackathons

    async def extract_with_model_fallback(
        self,
        text: str,
        source_url: str,
    ) -> List[Hackathon]:
        """Fallback to local LLM with schema-constrained JSON output."""
        if not text or len(text.strip()) < 100:
            return []

        # Check if text is relevant enough before calling LLM
        lower = text.lower()
        if not any(k in lower for k in ("hackathon", "competition", "challenge", "registration", "deadline")):
            return []

        prompt = (
            "You are a factual data extraction engine. Extract all hackathons or tech competitions "
            "mentioned in the text below into a JSON array of objects.\n\n"
            "Output MUST be valid JSON only, starting with `[` and ending with `]`. "
            "If no hackathons are found, output `[]`.\n\n"
            "Each object must have the following keys:\n"
            '- "name": string (Event name)\n'
            '- "organizer": string or null\n'
            '- "deadline": string or null (Registration deadline)\n'
            '- "event_date": string or null (Date of the event)\n'
            '- "location": string or null (City, venue or Online)\n'
            '- "prize": string or null\n'
            '- "registration_url": string or null\n\n'
            f"Source text (first 3500 chars):\n{text[:3500]}"
        )

        try:
            response = await self.llm_client.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You extract structured JSON only without markdown formatting or preamble.",
                max_tokens=600,
                temperature=0.1,
            )
            raw = response.strip()
            # Find json array boundaries
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                json_str = raw[start : end + 1]
                data = json.loads(json_str)
                results: List[Hackathon] = []
                for item in data:
                    if isinstance(item, dict) and item.get("name"):
                        results.append(
                            Hackathon(
                                name=str(item["name"]).strip(),
                                organizer=str(item.get("organizer")).strip() if item.get("organizer") else None,
                                deadline=str(item.get("deadline")).strip() if item.get("deadline") else None,
                                event_date=str(item.get("event_date")).strip() if item.get("event_date") else None,
                                location=str(item.get("location")).strip() if item.get("location") else None,
                                prize=str(item.get("prize")).strip() if item.get("prize") else None,
                                registration_url=str(item.get("registration_url")).strip() if item.get("registration_url") else None,
                                source_url=source_url,
                                confidence="MEDIUM",
                            )
                        )
                return results
        except Exception as exc:
            logger.warning("Model fallback extraction failed: %s", exc)

        return []

    async def extract_hackathons(
        self,
        markdown_text: str,
        source_url: str,
        use_model_fallback: bool = True,
        save_to_db: bool = True,
    ) -> List[Hackathon]:
        """Run full extraction pipeline (tables -> cards -> model fallback) and persist."""
        extracted: List[Hackathon] = []

        # 1. Try markdown table parsing
        table_results = self.parse_markdown_tables(markdown_text, source_url)
        extracted.extend(table_results)

        # 2. Try listing cards parsing
        if not extracted:
            card_results = self.parse_listing_blocks(markdown_text, source_url)
            extracted.extend(card_results)

        # 3. Model fallback if still empty
        if not extracted and use_model_fallback:
            model_results = await self.extract_with_model_fallback(markdown_text, source_url)
            extracted.extend(model_results)

        # Deduplicate by normalized name
        seen_names = set()
        deduped: List[Hackathon] = []
        for h in extracted:
            norm_name = re.sub(r"[^\w\s]", "", h.name).strip().lower()
            if norm_name and norm_name not in seen_names:
                seen_names.add(norm_name)
                deduped.append(h)

        # Save to SQLite database
        if save_to_db:
            content_hash = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()[:16]
            for h in deduped:
                try:
                    save_extracted_entity(
                        entity_type="hackathon",
                        name=h.name,
                        structured_data=h.model_dump_json(),
                        source_url=h.source_url,
                        content_hash=content_hash,
                    )
                except Exception as exc:
                    logger.warning("Failed to save extracted entity %s: %s", h.name, exc)

        return deduped

    @staticmethod
    def format_for_llm(hackathons: List[Hackathon]) -> str:
        """Format extracted hackathons into a concise, factual context block for LLM prompt."""
        if not hackathons:
            return ""

        lines = [
            f"### Verified Hackathons & Competitions ({len(hackathons)} found):"
        ]
        for h in hackathons:
            parts = [f"- **{h.name}** [{h.confidence}]"]
            if h.organizer:
                parts.append(f"  - Organizer: {h.organizer}")
            if h.event_date:
                parts.append(f"  - Date: {h.event_date}")
            if h.deadline:
                parts.append(f"  - Deadline: {h.deadline}")
            if h.location:
                parts.append(f"  - Location: {h.location}")
            if h.prize:
                parts.append(f"  - Prize: {h.prize}")
            if h.eligibility:
                parts.append(f"  - Eligibility: {h.eligibility}")
            reg = h.registration_url or h.source_url
            parts.append(f"  - Link: {reg}")
            lines.append("\n".join(parts))

        return "\n\n".join(lines)
