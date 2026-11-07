"""Unit tests for Official API integrations (GitHub, OpenAlex, Reddit)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.database import database
from app.integrations.github.client import GitHubClient
from app.integrations.github.service import GitHubService
from app.integrations.openalex.client import OpenAlexClient
from app.integrations.openalex.service import OpenAlexService, reconstruct_abstract
from app.integrations.reddit.client import RedditClient
from app.integrations.reddit.service import RedditService
from app.main import app
from app.schemas.external import ExternalRecord


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch):
    """Provide a fresh SQLite database for each test."""
    db_file = tmp_path / "test_integrations.db"
    import app.config as cfg_module

    orig_url = cfg_module.config.database_url
    cfg_module.config.database_url = f"sqlite:///{db_file}"
    database._init_lock = False
    database.init_db()
    yield
    cfg_module.config.database_url = orig_url


# ============================================================================
# GitHub Tests
# ============================================================================

def test_github_mapping() -> None:
    service = GitHubService()
    raw_repo = {
        "id": 123456,
        "full_name": "ggerganov/llama.cpp",
        "html_url": "https://github.com/ggerganov/llama.cpp",
        "description": "Port of Facebook's LLaMA model in C/C++",
        "created_at": "2023-03-10T12:00:00Z",
        "updated_at": "2026-11-01T12:00:00Z",
        "stargazers_count": 65000,
        "forks_count": 9200,
        "language": "C++",
        "topics": ["llm", "llama", "cpp"],
        "owner": {"login": "ggerganov"},
    }

    record = service.map_repo_to_record(raw_repo)
    assert record.source == "github"
    assert record.source_id == "ggerganov/llama.cpp"
    assert record.record_type == "repository"
    assert record.title == "ggerganov/llama.cpp"
    assert record.url == "https://github.com/ggerganov/llama.cpp"
    assert record.metadata["stars"] == 65000
    assert record.metadata["language"] == "C++"
    assert "llama" in record.metadata["topics"]

    raw_release = {
        "id": 9999,
        "tag_name": "b4200",
        "name": "llama.cpp Release b4200",
        "html_url": "https://github.com/ggerganov/llama.cpp/releases/tag/b4200",
        "body": "Bug fixes and AVX-512 acceleration.",
        "published_at": "2026-11-06T15:00:00Z",
        "prerelease": False,
        "author": {"login": "ggerganov"},
    }

    release_record = service.map_release_to_record("ggerganov", "llama.cpp", raw_release)
    assert release_record.source == "github"
    assert release_record.source_id == "ggerganov/llama.cpp@b4200"
    assert release_record.record_type == "release"
    assert "llama.cpp Release b4200" in release_record.title


@pytest.mark.asyncio
async def test_github_service_search_and_ingest() -> None:
    mock_client = AsyncMock(spec=GitHubClient)
    mock_client.search_repositories.return_value = [
        {
            "id": 1,
            "full_name": "test/repo",
            "html_url": "https://github.com/test/repo",
            "description": "Test Repo",
            "stargazers_count": 100,
            "forks_count": 10,
            "language": "Python",
            "topics": ["ai"],
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]

    service = GitHubService(client=mock_client)
    res = await service.search_and_ingest("ai", limit=1)
    assert res.inserted == 1
    assert res.total_received == 1


# ============================================================================
# OpenAlex Tests
# ============================================================================

def test_openalex_abstract_reconstruction() -> None:
    inverted_index = {
        "Small": [0],
        "language": [1],
        "models": [2],
        "are": [3],
        "efficient": [4],
        "and": [5],
        "fast.": [6],
    }
    abstract = reconstruct_abstract(inverted_index)
    assert abstract == "Small language models are efficient and fast."

    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_openalex_mapping() -> None:
    service = OpenAlexService()
    raw_work = {
        "id": "https://openalex.org/W4388832049",
        "doi": "https://doi.org/10.48550/arxiv.2401.00001",
        "title": "On-Device LLMs with Edge Optimization",
        "publication_year": 2026,
        "publication_date": "2026-02-15",
        "abstract_inverted_index": {
            "We": [0],
            "present": [1],
            "Karna": [2],
            "architecture.": [3],
        },
        "authorships": [
            {"author": {"display_name": "Alice Smith"}},
            {"author": {"display_name": "Bob Jones"}},
        ],
        "primary_location": {
            "source": {"display_name": "arXiv"},
            "landing_page_url": "https://arxiv.org/abs/2401.00001",
        },
        "concepts": [
            {"display_name": "Artificial Intelligence"},
            {"display_name": "Computer Science"},
        ],
        "cited_by_count": 12,
        "is_oa": True,
    }

    record = service.map_work_to_record(raw_work)
    assert record.source == "openalex"
    assert record.source_id == "W4388832049"
    assert record.record_type == "research_paper"
    assert record.title == "On-Device LLMs with Edge Optimization"
    assert record.description == "We present Karna architecture."
    assert record.metadata["doi"] == "https://doi.org/10.48550/arxiv.2401.00001"
    assert "Alice Smith" in record.metadata["authors"]
    assert record.metadata["cited_by_count"] == 12


@pytest.mark.asyncio
async def test_openalex_service_search_and_ingest() -> None:
    mock_client = AsyncMock(spec=OpenAlexClient)
    mock_client.search_works.return_value = [
        {
            "id": "https://openalex.org/W111",
            "title": "Fast Inference on ARM",
            "publication_date": "2026-05-01",
            "primary_location": {"landing_page_url": "https://example.com/paper"},
            "abstract_inverted_index": {"Fast": [0], "inference": [1]},
            "authorships": [],
            "concepts": [],
            "cited_by_count": 5,
        }
    ]

    service = OpenAlexService(client=mock_client)
    res = await service.search_and_ingest("Fast Inference", limit=1)
    assert res.inserted == 1
    assert res.total_received == 1


# ============================================================================
# Reddit Tests
# ============================================================================

def test_reddit_mapping() -> None:
    service = RedditService()
    raw_post = {
        "id": "1g9h8kl",
        "name": "t3_1g9h8kl",
        "title": "Running Qwen 3.5 2B locally at 55 tokens/sec",
        "url": "https://www.reddit.com/r/LocalLLaMA/comments/1g9h8kl/running_qwen_35_2b/",
        "permalink": "/r/LocalLLaMA/comments/1g9h8kl/running_qwen_35_2b/",
        "selftext": "Here are my benchmark results with llama.cpp on a modest CPU.",
        "author": "localllm_fan",
        "subreddit": "LocalLLaMA",
        "score": 340,
        "upvote_ratio": 0.98,
        "num_comments": 47,
        "created_utc": 1794000000.0,
        "link_flair_text": "Discussion",
    }

    record = service.map_post_to_record(raw_post)
    assert record.source == "reddit"
    assert record.source_id == "t3_1g9h8kl"
    assert record.record_type == "discussion"
    assert record.title == "Running Qwen 3.5 2B locally at 55 tokens/sec"
    assert "benchmark results" in record.description
    assert record.metadata["author"] == "localllm_fan"
    assert record.metadata["score"] == 340
    assert record.metadata["num_comments"] == 47
    assert "r/LocalLLaMA" in record.metadata["tags"]


@pytest.mark.asyncio
async def test_reddit_service_fetch_and_ingest() -> None:
    mock_client = AsyncMock(spec=RedditClient)
    mock_client.get_subreddit_posts.return_value = [
        {
            "id": "p1",
            "name": "t3_p1",
            "title": "Discussion on Local AI",
            "permalink": "/r/LocalLLaMA/comments/p1/",
            "selftext": "Great insights here.",
            "author": "user1",
            "subreddit": "LocalLLaMA",
            "score": 50,
            "num_comments": 12,
            "created_utc": 1794000000.0,
        }
    ]

    service = RedditService(client=mock_client)
    res = await service.fetch_and_ingest(subreddit="LocalLLaMA", listing="hot", limit=1)
    assert res.inserted == 1
    assert res.total_received == 1


# ============================================================================
# FastAPI Integration Endpoints Tests
# ============================================================================

def test_api_routes_with_mocks() -> None:
    client = TestClient(app)

    # Test GitHub search endpoint
    with patch("app.integrations.github.routes.github_client.search_repositories", new_callable=AsyncMock) as mock_gh:
        mock_gh.return_value = [
            {
                "id": 101,
                "full_name": "fastapi/fastapi",
                "html_url": "https://github.com/fastapi/fastapi",
                "description": "FastAPI framework",
                "stargazers_count": 75000,
                "forks_count": 6000,
                "language": "Python",
                "topics": ["api"],
                "created_at": "2018-12-08T00:00:00Z",
            }
        ]
        resp = client.get("/api/integrations/github/search?query=fastapi&limit=1&ingest=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["items"][0]["full_name"] == "fastapi/fastapi"
        assert data["ingestion"]["inserted"] == 1

    # Test OpenAlex search endpoint
    with patch("app.integrations.openalex.routes.openalex_client.search_works", new_callable=AsyncMock) as mock_oa:
        mock_oa.return_value = [
            {
                "id": "https://openalex.org/W222",
                "title": "Attention Is All You Need",
                "publication_date": "2017-06-12",
                "primary_location": {"landing_page_url": "https://arxiv.org/abs/1706.03762"},
                "abstract_inverted_index": {"The": [0], "dominant": [1], "sequence": [2]},
                "authorships": [{"author": {"display_name": "Vaswani"}}],
                "concepts": [{"display_name": "Transformers"}],
                "cited_by_count": 100000,
            }
        ]
        resp = client.get("/api/integrations/openalex/search?query=transformers&limit=1&ingest=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["title"] == "Attention Is All You Need"
        assert data["ingestion"]["inserted"] == 1

    # Test Reddit posts endpoint
    with patch("app.integrations.reddit.routes.reddit_client.get_subreddit_posts", new_callable=AsyncMock) as mock_rd:
        mock_rd.return_value = [
            {
                "id": "rd1",
                "name": "t3_rd1",
                "title": "State of Open Source AI in 2026",
                "permalink": "/r/MachineLearning/comments/rd1/",
                "selftext": "A comprehensive retrospective.",
                "author": "researcher_x",
                "subreddit": "MachineLearning",
                "score": 520,
                "num_comments": 88,
                "created_utc": 1794000000.0,
            }
        ]
        resp = client.get("/api/integrations/reddit/posts?subreddit=MachineLearning&limit=1&ingest=true")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["posts"][0]["title"] == "State of Open Source AI in 2026"
        assert data["ingestion"]["inserted"] == 1
