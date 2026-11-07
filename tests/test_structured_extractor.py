"""Tests for StructuredExtractor and persistent entity extraction."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.database.database import init_db
from app.database.repository import get_entities_by_type, find_entity_by_name
from app.schemas.entities import Hackathon
from app.services.structured_extractor import StructuredExtractor


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_parse_markdown_tables():
    markdown = """
# Upcoming Hackathons

| Event Name | Date | Location | Prize | Apply |
| :--- | :--- | :--- | :--- | :--- |
| [CodeStorm 2026](https://codestorm.io) | Nov 20-22, 2026 | Hyderabad | ₹1,00,000 | [Register](https://codestorm.io/apply) |
| AI Blitz | Dec 5, 2026 | Online | $5,000 | https://aiblitz.dev |
"""
    extractor = StructuredExtractor()
    results = extractor.parse_markdown_tables(markdown, source_url="https://example.com/hackathons")

    assert len(results) == 2
    assert results[0].name == "CodeStorm 2026"
    assert results[0].event_date == "Nov 20-22, 2026"
    assert results[0].location == "Hyderabad"
    assert results[0].prize == "₹1,00,000"
    assert results[0].registration_url == "https://codestorm.io/apply"
    assert results[0].source_url == "https://example.com/hackathons"

    assert results[1].name == "AI Blitz"
    assert results[1].event_date == "Dec 5, 2026"
    assert results[1].location == "Online"
    assert results[1].prize == "$5,000"


def test_parse_listing_blocks():
    markdown = """
## Tech Challenges

### HackTheFuture 2026
Date: Nov 15-17, 2026
Deadline: Nov 10, 2026
Location: Hyderabad / Offline
Prize: ₹2,50,000
[Apply Here](https://hackthefuture.org)

### Web3 Summit
Date: Dec 1-2, 2026
Location: Bengaluru
"""
    extractor = StructuredExtractor()
    results = extractor.parse_listing_blocks(markdown, source_url="https://example.com/listings")

    assert len(results) >= 1
    assert any(h.name == "HackTheFuture 2026" for h in results)
    h = next(item for item in results if item.name == "HackTheFuture 2026")
    assert h.event_date == "Nov 15-17, 2026"
    assert h.deadline == "Nov 10, 2026"
    assert "Hyderabad" in (h.location or "")
    assert h.registration_url == "https://hackthefuture.org"


@pytest.mark.asyncio
async def test_extract_with_model_fallback():
    mock_llm = MagicMock()
    json_response = json.dumps([
        {
            "name": "DevFest Hackathon 2026",
            "organizer": "GDG Hyderabad",
            "deadline": "2026-11-20",
            "event_date": "2026-11-28",
            "location": "Hyderabad",
            "prize": "₹50,000",
            "registration_url": "https://gdghyd.org/hackathon"
        }
    ])
    mock_llm.generate = AsyncMock(return_value=f"Here is the JSON: {json_response}")

    extractor = StructuredExtractor(llm_client=mock_llm)
    raw_text = "Join us for the GDG Hyderabad DevFest Hackathon on November 28, 2026. Registration deadline is Nov 20."
    results = await extractor.extract_with_model_fallback(raw_text, source_url="https://gdghyd.org")

    assert len(results) == 1
    assert results[0].name == "DevFest Hackathon 2026"
    assert results[0].organizer == "GDG Hyderabad"
    assert results[0].location == "Hyderabad"


@pytest.mark.asyncio
async def test_extract_hackathons_end_to_end_and_persistence():
    markdown = """
| Hackathon | Dates | City |
| --- | --- | --- |
| CyberHack 2026 | Nov 25, 2026 | Hyderabad |
"""
    extractor = StructuredExtractor()
    results = await extractor.extract_hackathons(
        markdown_text=markdown,
        source_url="https://cyberhack.com",
        use_model_fallback=False,
        save_to_db=True,
    )

    assert len(results) == 1
    assert results[0].name == "CyberHack 2026"

    # Verify SQLite persistence
    entity = find_entity_by_name("hackathon", "CyberHack 2026")
    assert entity is not None
    assert entity["name"] == "CyberHack 2026"
    assert "CyberHack 2026" in entity["structured_data"]


def test_format_for_llm():
    hackathons = [
        Hackathon(
            name="TestHack",
            organizer="TestOrg",
            event_date="Nov 20, 2026",
            location="Hyderabad",
            registration_url="https://testhack.org",
            source_url="https://source.org",
        )
    ]
    formatted = StructuredExtractor.format_for_llm(hackathons)
    assert "TestHack" in formatted
    assert "TestOrg" in formatted
    assert "Nov 20, 2026" in formatted
    assert "Hyderabad" in formatted
    assert "https://testhack.org" in formatted
