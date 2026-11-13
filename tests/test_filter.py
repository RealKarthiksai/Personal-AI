import pytest
from app.services.pipeline.filter import _passages, _norm, filter_pages

def test_passages_splitting():
    text = "\n".join([f"Paragraph {i} has enough characters to be valid and long." for i in range(10)])
    ps = _passages(text, size=200)
    assert len(ps) > 1
    assert all(len(p) <= 300 for p in ps)

def test_norm():
    assert _norm("  Hello   World \n\n ") == "hello world"

@pytest.mark.asyncio
async def test_filter_pages_mock(monkeypatch):
    async def mock_call(role, messages, schema=None, name="out"):
        return {"quotes": ["Paragraph 1 has enough characters to be valid and long."]}
    monkeypatch.setattr("app.services.pipeline.filter.call", mock_call)

    pages = [
        {"url": "https://example.com/1", "text": "Paragraph 1 has enough characters to be valid and long.\n\nParagraph 2 is different."},
        {"url": "https://example.com/2", "text": "Irrelevant text with nothing useful here."},
    ]
    kept = await filter_pages("Paragraph 1?", ["valid"], pages)
    assert len(kept) == 1
    assert kept[0]["url"] == "https://example.com/1"
    assert "Paragraph 1" in kept[0]["text"]


def test_passages_preserves_short_bullet_lists():
    bullet_text = "Upcoming Events in City:\n- AI Dhamaka: Nov 14\n- WCSET: Nov 17\n- Prize: $8,000"
    ps = _passages(bullet_text, size=200)
    assert len(ps) == 1
    assert "- AI Dhamaka: Nov 14" in ps[0]
    assert "- Prize: $8,000" in ps[0]


def test_passages_empty():
    assert _passages("") == []
    assert _passages("   \n\n  ") == []


def test_tok_caching():
    from app.services.pipeline.filter import _tok
    t1 = _tok("Fast search query")
    t2 = _tok("Fast search query")
    assert t1 == ("fast", "search", "query")
    assert t1 is t2  # Cache identity

