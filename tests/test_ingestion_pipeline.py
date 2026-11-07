"""Tests for the Common Ingestion Pipeline, storage, versioning, and retrieval."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import database
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.retrieval import format_records_for_llm, retrieve_external_information
from app.ingestion.storage import (
    get_record_versions,
    list_sources,
    query_records,
    upsert_record,
)
from app.main import app
from app.schemas.external import ExternalRecord, ExternalRecordQuery


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Provide a fresh SQLite database for each test."""
    db_file = tmp_path / "test_ingestion.db"
    import app.config as cfg_module

    orig_url = cfg_module.config.database_url
    cfg_module.config.database_url = f"sqlite:///{db_file}"
    database._init_lock = False
    database.init_db()
    yield
    cfg_module.config.database_url = orig_url


def test_batch_ingestion_and_idempotency() -> None:
    pipeline = IngestionPipeline()
    records = [
        ExternalRecord(
            source="github",
            source_id="vhanghar/karna",
            record_type="repository",
            title="Karna AI Assistant",
            url="https://github.com/vhanghar/karna",
            description="Personal AI companion with tool routing.",
            published_at="2026-11-01T12:00:00Z",
            metadata={"stars": 42, "language": "Python"},
        ),
        ExternalRecord(
            source="reddit",
            source_id="t3_abc123",
            record_type="discussion",
            title="Local LLM benchmarks for Qwen 3.5 2B",
            url="https://reddit.com/r/LocalLLaMA/comments/abc123",
            description="Discussion on lightweight quantized models.",
            published_at="2026-11-05T08:30:00Z",
            metadata={"score": 150, "comments": 28},
        ),
        ExternalRecord(
            source="openalex",
            source_id="W987654321",
            record_type="research_paper",
            title="Efficient Retrieval Architectures for Edge AI",
            url="https://doi.org/10.1234/example.2026",
            description="A novel approach to single-host RAG pipelines.",
            published_at="2026-10-20T00:00:00Z",
            metadata={"authors": ["Dr. Smith", "Dr. Patel"], "doi": "10.1234/example.2026"},
        ),
    ]

    import asyncio

    # 1. Initial ingestion: all 3 should be inserted
    res1 = asyncio.run(pipeline.ingest_batch(records))
    assert res1.total_received == 3
    assert res1.inserted == 3
    assert res1.updated == 0
    assert res1.skipped_identical == 0
    assert res1.failed == 0

    # 2. Idempotent re-ingestion: all 3 should be skipped without modification
    res2 = asyncio.run(pipeline.ingest_batch(records))
    assert res2.total_received == 3
    assert res2.inserted == 0
    assert res2.updated == 0
    assert res2.skipped_identical == 3
    assert res2.failed == 0


def test_version_tracking_on_content_change() -> None:
    record = ExternalRecord(
        source="rss",
        source_id="https://news.ycombinator.com/item?id=1",
        record_type="article",
        title="Initial Article Title",
        url="https://news.ycombinator.com/item?id=1",
        description="Version 1 of the article summary.",
        metadata={"author": "alice"},
    )

    rec_id, status1 = upsert_record(record)
    assert status1 == "inserted"

    # Modify content
    record.title = "Updated Headline for Article"
    record.description = "Version 2 with expanded coverage."
    record.metadata["tags"] = ["breaking"]

    rec_id2, status2 = upsert_record(record)
    assert rec_id2 == rec_id
    assert status2 == "updated"

    # Verify history in record_versions table
    versions = get_record_versions(rec_id)
    assert len(versions) == 1
    assert versions[0]["title"] == "Initial Article Title"
    assert versions[0]["description"] == "Version 1 of the article summary."


def test_batch_in_memory_deduplication() -> None:
    pipeline = IngestionPipeline()
    batch = [
        ExternalRecord(
            source="github",
            source_id="project/repo",
            record_type="repository",
            title="First Draft",
            url="https://github.com/project/repo",
        ),
        ExternalRecord(
            source="github",
            source_id="project/repo",
            record_type="repository",
            title="Final Update in Batch",
            url="https://github.com/project/repo",
        ),
    ]
    import asyncio

    res = asyncio.run(pipeline.ingest_batch(batch))
    assert res.total_received == 2
    assert res.inserted == 1

    stored = query_records(ExternalRecordQuery(sources=["github"]))
    assert len(stored) == 1
    assert stored[0].title == "Final Update in Batch"


def test_query_and_filtering() -> None:
    records = [
        ExternalRecord(
            source="github",
            source_id="org/fastapi-tool",
            record_type="repository",
            title="FastAPI Tooling Kit",
            url="https://github.com/org/fastapi-tool",
            description="Utilities for FastAPI apps.",
        ),
        ExternalRecord(
            source="reddit",
            source_id="t3_disc1",
            record_type="discussion",
            title="FastAPI vs Django discussion",
            url="https://reddit.com/r/python/disc1",
            description="Community debate on API frameworks.",
        ),
        ExternalRecord(
            source="openalex",
            source_id="W111222",
            record_type="research_paper",
            title="Neural Architecture Search",
            url="https://doi.org/10.1111/nas",
            description="Deep learning optimization paper.",
        ),
    ]
    for r in records:
        upsert_record(r)

    # 1. Filter by source
    github_only = query_records(ExternalRecordQuery(sources=["github"]))
    assert len(github_only) == 1
    assert github_only[0].source == "github"

    # 2. Filter by keyword
    search_res = query_records(ExternalRecordQuery(query="Neural"))
    assert len(search_res) == 1
    assert search_res[0].record_type == "research_paper"

    # 3. Filter by record type
    disc_only = query_records(ExternalRecordQuery(record_types=["discussion"]))
    assert len(disc_only) == 1
    assert disc_only[0].source == "reddit"


def test_retrieval_bridge_and_formatting() -> None:
    record = ExternalRecord(
        source="github",
        source_id="langchain-ai/langchain",
        record_type="repository",
        title="LangChain Framework",
        url="https://github.com/langchain-ai/langchain",
        description="Framework for developing LLM applications.",
        published_at="2026-11-01T00:00:00Z",
        metadata={"stars": 85000},
    )
    upsert_record(record)

    results = retrieve_external_information(query="LangChain", sources=["github"])
    assert len(results) == 1

    formatted = format_records_for_llm(results)
    assert "LangChain Framework" in formatted
    assert "https://github.com/langchain-ai/langchain" in formatted
    assert "Github • Repository" in formatted
    assert "⭐ 85000 stars" in formatted


def test_fastapi_endpoints() -> None:
    client = TestClient(app)

    # 1. POST /api/v1/ingest
    payload = [
        {
            "source": "github",
            "source_id": "test/api-repo",
            "record_type": "repository",
            "title": "API Test Repo",
            "url": "https://github.com/test/api-repo",
            "description": "Repo ingested via FastAPI test endpoint.",
            "metadata": {"stars": 10},
        }
    ]
    resp = client.post("/api/v1/ingest", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_received"] == 1
    assert data["inserted"] == 1

    # 2. GET /api/v1/records
    get_resp = client.get("/api/v1/records", params={"source": "github"})
    assert get_resp.status_code == 200
    records = get_resp.json()
    assert len(records) >= 1
    assert records[0]["title"] == "API Test Repo"

    # 3. GET /api/v1/records/sources
    sources_resp = client.get("/api/v1/records/sources")
    assert sources_resp.status_code == 200
    sources_data = sources_resp.json()
    assert any(s["name"] == "github" for s in sources_data)
