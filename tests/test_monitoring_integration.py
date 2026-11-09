"""Unit tests for website change monitoring and alert dispatching."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.database import database
from app.integrations.monitoring.client import ChangeDetectionClient, extract_clean_text
from app.integrations.monitoring.service import MonitoringService
from app.main import app
from app.services.telegram_client import TelegramClient


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """Provide a fresh SQLite database for each test."""
    db_file = tmp_path / "test_monitoring.db"
    import app.config as cfg_module

    orig_url = cfg_module.config.database_url
    cfg_module.config.database_url = f"sqlite:///{db_file}"
    database._init_lock = False
    database.init_db()
    yield
    cfg_module.config.database_url = orig_url


def test_extract_clean_text() -> None:
    html = """
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <script>console.log("ignore");</script>
        <h1>Hackathon 2026 Announcements</h1>
        <p>Registration deadline is <b>December 15</b>.</p>
      </body>
    </html>
    """
    text = extract_clean_text(html)
    assert "Hackathon 2026 Announcements" in text
    assert "December 15" in text
    assert "console.log" not in text
    assert "color: red" not in text


def test_watch_crud() -> None:
    service = MonitoringService()

    # 1. Create
    w1 = service.create_watch("https://example.com/hackathons", title="Global Hackathons")
    assert w1["created"] is True
    assert w1["title"] == "Global Hackathons"

    # 2. List
    watches = service.list_watches()
    assert len(watches) == 1
    assert watches[0]["url"] == "https://example.com/hackathons"

    # 3. Duplicate create (idempotent / updates title)
    w2 = service.create_watch("https://example.com/hackathons", title="Renamed Hackathons")
    assert w2["created"] is False
    assert w2["title"] == "Renamed Hackathons"

    # 4. Delete
    deleted = service.delete_watch(w1["watch_id"])
    assert deleted is True
    assert len(service.list_watches()) == 0


@pytest.mark.asyncio
async def test_differential_check_lifecycle(monkeypatch) -> None:
    mock_client = AsyncMock(spec=ChangeDetectionClient)
    mock_telegram = AsyncMock(spec=TelegramClient)

    service = MonitoringService(client=mock_client, telegram_client=mock_telegram)
    watch = service.create_watch("https://example.com/status", title="API Status Page")

    # Pass 1: Initial fetch
    mock_client.fetch_page_content.return_value = "System Operational - All services normal"
    res1 = await service.check_watch(watch)
    assert res1["status"] == "inserted"
    assert mock_telegram.send_text.call_count == 0  # Initial insertion does not spam alerts

    # Pass 2: Unchanged content
    mock_client.fetch_page_content.return_value = "System Operational - All services normal"
    res2 = await service.check_watch(watch)
    assert res2["status"] == "skipped"
    assert mock_telegram.send_text.call_count == 0

    # Pass 3: Content changed!
    monkeypatch.setattr("app.config.config.is_telegram_configured", lambda: True)
    monkeypatch.setattr("app.config.config.allowed_telegram_user_ids", [99999])
    mock_client.fetch_page_content.return_value = "MAJOR OUTAGE: Database connection failure in us-east"
    res3 = await service.check_watch(watch)
    assert res3["status"] == "updated"
    # Telegram notification should have been dispatched
    assert mock_telegram.send_text.call_count == 1


@pytest.mark.asyncio
async def test_webhook_ingestion(monkeypatch) -> None:
    mock_telegram = AsyncMock(spec=TelegramClient)
    service = MonitoringService(telegram_client=mock_telegram)

    monkeypatch.setattr("app.config.config.is_telegram_configured", lambda: True)
    monkeypatch.setattr("app.config.config.allowed_telegram_user_ids", [12345])
    payload = {
        "watch_url": "https://hackathons.org/ai-2026",
        "watch_title": "AI Global Hackathon 2026",
        "diff": "Prize pool increased from $50k to $100k! Submissions open.",
        "watch_uuid": "watch_test_123",
    }
    res = await service.handle_webhook(payload)
    assert res["status"] == "processed"
    assert res["ingested"]["inserted"] == 1
    assert mock_telegram.send_text.call_count == 1


def test_monitoring_api_routes() -> None:
    client = TestClient(app)

    # 1. Create watch
    resp = client.post(
        "/api/integrations/monitoring/watches",
        json={"url": "https://example.com/bounties", "title": "Bug Bounties"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created"] is True
    wid = data["watch_id"]

    # 2. List watches
    resp = client.get("/api/integrations/monitoring/watches")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # 3. Check endpoint with mock
    with patch("app.integrations.monitoring.service.monitoring_client.fetch_page_content", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = "Page content sample"
        resp_check = client.post("/api/integrations/monitoring/check", json={"watch_id": wid})
        assert resp_check.status_code == 200
        assert resp_check.json()["status"] == "inserted"

    # 4. Webhook endpoint
    with patch("app.integrations.monitoring.service.monitoring_service.notify_users_of_change", new_callable=AsyncMock) as mock_notify:
        resp_wh = client.post(
            "/api/integrations/monitoring/webhook",
            json={"watch_url": "https://example.com/alerts", "title": "Alert Page", "diff": "Changed text"},
        )
        assert resp_wh.status_code == 200
        assert resp_wh.json()["status"] == "processed"
        mock_notify.assert_awaited_once()

    # 5. Delete watch
    resp_del = client.delete(f"/api/integrations/monitoring/watches/{wid}")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "deleted"


def test_extract_hackathons_devfolio_next_data() -> None:
    from app.integrations.monitoring.service import extract_hackathons_from_html

    sample_html = """
    <html>
      <head><title>Hackathons</title></head>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "dehydratedState": {
                "queries": [
                  {
                    "queryKey": "fetchAllHackathonTypes",
                    "state": {
                      "data": {
                        "open_hackathons": [
                          {
                            "name": "AI SuperHack 2026",
                            "slug": "ai-superhack-2026",
                            "is_online": true,
                            "starts_at": "2026-12-01T10:00:00Z",
                            "ends_at": "2026-12-03T18:00:00Z",
                            "themes": [{"theme": {"name": "Generative AI"}}, {"theme": {"name": "Fintech"}}],
                            "prize": "$25,000",
                            "settings": {
                              "reg_ends_at": "2026-11-28T23:59:00Z",
                              "external_apply_url": "https://superhack.ai/apply"
                            }
                          }
                        ],
                        "upcoming_hackathons": []
                      }
                    }
                  }
                ]
              }
            }
          }
        }
        </script>
      </body>
    </html>
    """
    hackathons = extract_hackathons_from_html("https://devfolio.co/hackathons", sample_html)
    assert len(hackathons) == 1
    h = hackathons[0]
    assert h.name == "AI SuperHack 2026"
    assert h.location == "Online / Virtual"
    assert "Generative AI" in h.eligibility
    assert h.prize == "$25,000"
    assert h.registration_url == "https://superhack.ai/apply"
    assert "Dec 01, 2026 - Dec 03, 2026" in h.event_date
    assert h.deadline == "Nov 28, 2026"


@pytest.mark.asyncio
async def test_notify_hackathon_format(monkeypatch) -> None:
    from app.schemas.entities import Hackathon

    mock_telegram = AsyncMock(spec=TelegramClient)
    service = MonitoringService(telegram_client=mock_telegram)

    monkeypatch.setattr("app.config.config.is_telegram_configured", lambda: True)
    monkeypatch.setattr("app.config.config.allowed_telegram_user_ids", [7814496829])

    h = Hackathon(
        name="Buildathon 2026",
        organizer="Devfolio",
        deadline="Dec 10, 2026",
        event_date="Dec 15, 2026 - Dec 17, 2026",
        location="Hyderabad, India",
        eligibility="Open Innovation, AI/ML",
        prize="₹5,00,000",
        registration_url="https://buildathon.devfolio.co",
        source_url="https://devfolio.co/hackathons",
        confidence="HIGH",
    )

    await service.notify_hackathon(h)

    assert mock_telegram.send_text.call_count == 1
    sent_text = mock_telegram.send_text.call_args[1]["text"]

    assert "🚀 <b>New Hackathon Detected!</b>" in sent_text
    assert "🏆 <b>Name:</b> Buildathon 2026" in sent_text
    assert "📍 <b>Place:</b> Hyderabad, India" in sent_text
    assert "📝 <b>Details:</b> Open Innovation, AI/ML" in sent_text
    assert "💰 <b>Amount:</b> ₹5,00,000" in sent_text
    assert "🗓️ <b>Date & Time:</b> Dec 15, 2026 - Dec 17, 2026 (Reg Deadline: Dec 10, 2026)" in sent_text
    assert "🔗 <b>Link:</b> https://buildathon.devfolio.co" in sent_text


@pytest.mark.asyncio
async def test_hackathon_differential_suppression(monkeypatch) -> None:
    mock_client = AsyncMock(spec=ChangeDetectionClient)
    mock_telegram = AsyncMock(spec=TelegramClient)
    service = MonitoringService(client=mock_client, telegram_client=mock_telegram)

    monkeypatch.setattr("app.config.config.is_telegram_configured", lambda: True)
    monkeypatch.setattr("app.config.config.allowed_telegram_user_ids", [7814496829])

    watch = service.create_watch("https://devfolio.co/hackathons", title="Devfolio Hackathons")

    sample_html_v1 = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"dehydratedState":{"queries":[{"queryKey":"fetchAllHackathonTypes","state":{"data":{"open_hackathons":[{"name":"Hack V1","slug":"hack-v1","is_online":true,"starts_at":"2026-11-20T00:00:00Z","ends_at":"2026-11-21T00:00:00Z","themes":[],"settings":{}}],"upcoming_hackathons":[]}}}]}}}}
    </script>
    <div>Dynamic token 111</div>
    """

    # Pass 1: Baseline insertion
    mock_client.fetch_page_raw.return_value = sample_html_v1
    mock_client.fetch_page_content.return_value = "Hack V1 Dynamic token 111"
    res1 = await service.check_watch(watch)
    assert res1["status"] == "inserted"
    assert mock_telegram.send_text.call_count == 0  # Baseline doesn't spam alerts

    # Pass 2: Content hash changed due to dynamic token, but no new hackathon
    sample_html_v2 = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"dehydratedState":{"queries":[{"queryKey":"fetchAllHackathonTypes","state":{"data":{"open_hackathons":[{"name":"Hack V1","slug":"hack-v1","is_online":true,"starts_at":"2026-11-20T00:00:00Z","ends_at":"2026-11-21T00:00:00Z","themes":[],"settings":{}}],"upcoming_hackathons":[]}}}]}}}}
    </script>
    <div>Dynamic token 222 (timestamp changed)</div>
    """
    mock_client.fetch_page_raw.return_value = sample_html_v2
    mock_client.fetch_page_content.return_value = "Hack V1 Dynamic token 222 (timestamp changed)"
    res2 = await service.check_watch(watch)
    assert res2["status"] == "updated"
    # False positive alert MUST be suppressed because Hack V1 was already known!
    assert mock_telegram.send_text.call_count == 0

    # Pass 3: A genuinely NEW hackathon is added to Devfolio!
    sample_html_v3 = """
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"dehydratedState":{"queries":[{"queryKey":"fetchAllHackathonTypes","state":{"data":{"open_hackathons":[{"name":"Hack V1","slug":"hack-v1","is_online":true,"starts_at":"2026-11-20T00:00:00Z","ends_at":"2026-11-21T00:00:00Z","themes":[],"settings":{}},{"name":"Brand New Hackathon 2026","slug":"brand-new-2026","is_online":false,"starts_at":"2026-12-10T00:00:00Z","ends_at":"2026-12-12T00:00:00Z","themes":[{"theme":{"name":"Web3"}}],"prize":"$50,000","settings":{"reg_ends_at":"2026-12-05T00:00:00Z"}}],"upcoming_hackathons":[]}}}]}}}}
    </script>
    <div>Dynamic token 333</div>
    """
    mock_client.fetch_page_raw.return_value = sample_html_v3
    mock_client.fetch_page_content.return_value = "Hack V1 Brand New Hackathon 2026 Dynamic token 333"
    res3 = await service.check_watch(watch)
    assert res3["status"] == "updated"
    # Notification MUST be dispatched for Brand New Hackathon 2026!
    assert mock_telegram.send_text.call_count == 1
    sent_text = mock_telegram.send_text.call_args[1]["text"]
    assert "Brand New Hackathon 2026" in sent_text
    assert "In-Person (Offline)" in sent_text
    assert "$50,000" in sent_text

