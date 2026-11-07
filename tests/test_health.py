"""Tests for application health and root endpoints using FastAPI TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "telegram_configured" in body
    assert "llm_configured" in body


def test_root() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Local AI Chatbot (Karna)"
    assert body["endpoints"] == ["/health"]
