"""Website monitoring service.

Manages page watches in SQLite, performs differential content checks,
ingests change alerts into the Common Ingestion Pipeline, and dispatches
Telegram notifications.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import config
from app.database.database import transaction
from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.ingestion.storage import get_record_versions, upsert_record
from app.integrations.monitoring.client import ChangeDetectionClient, monitoring_client
from app.schemas.external import ExternalRecord, IngestionResult
from app.services.telegram_client import TelegramClient
from app.utils.logging import get_logger

logger = get_logger("app.integrations.monitoring.service")


class MonitoringService:
    """Service for managing website change monitors and sending alerts."""

    def __init__(
        self,
        client: Optional[ChangeDetectionClient] = None,
        ingestion_pipeline: Optional[IngestionPipeline] = None,
        telegram_client: Optional[TelegramClient] = None,
    ) -> None:
        self.client = client or monitoring_client
        self.pipeline = ingestion_pipeline or default_pipeline
        self.telegram = telegram_client or TelegramClient()

    # --------------------------------------------------------------------------
    # Watch Management
    # --------------------------------------------------------------------------

    def create_watch(
        self,
        url: str,
        title: Optional[str] = None,
        watch_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register a website URL to be monitored for content changes."""
        url_clean = url.strip()
        wid = watch_id or f"watch_{uuid.uuid4().hex[:12]}"
        watch_title = title or url_clean

        with transaction() as conn:
            existing = conn.execute(
                "SELECT id, watch_id, url, title FROM monitor_watches WHERE url = ?",
                (url_clean,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE monitor_watches SET title = COALESCE(?, title) WHERE id = ?",
                    (title, existing["id"]),
                )
                return {
                    "id": existing["id"],
                    "watch_id": existing["watch_id"],
                    "url": url_clean,
                    "title": title or existing["title"],
                    "created": False,
                }

            cur = conn.execute(
                "INSERT INTO monitor_watches (watch_id, url, title) VALUES (?, ?, ?)",
                (wid, url_clean, watch_title),
            )
            return {
                "id": cur.lastrowid,
                "watch_id": wid,
                "url": url_clean,
                "title": watch_title,
                "created": True,
            }

    def delete_watch(self, watch_id_or_url: str) -> bool:
        """Remove a website monitor watch."""
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM monitor_watches WHERE watch_id = ? OR url = ?",
                (watch_id_or_url, watch_id_or_url),
            )
            return cur.rowcount > 0

    def list_watches(self) -> List[Dict[str, Any]]:
        """List all active website watches."""
        with transaction() as conn:
            rows = conn.execute(
                "SELECT id, watch_id, url, title, last_checked_at, last_changed_at, created_at FROM monitor_watches ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --------------------------------------------------------------------------
    # Notification Helper
    # --------------------------------------------------------------------------

    async def notify_users_of_change(self, title: str, url: str, snippet: Optional[str] = None) -> None:
        """Dispatch Telegram alert to configured allowed users."""
        if not config.is_telegram_configured():
            logger.info("Telegram not configured; skipping change notification dispatch")
            return

        allowed_ids = config.allowed_telegram_user_ids
        if not allowed_ids:
            logger.info("No allowed Telegram user IDs configured; skipping change notification dispatch")
            return

        message = (
            f"🔔 <b>Website Change Detected</b>\n\n"
            f"<b>Source:</b> {title}\n"
            f"<b>URL:</b> {url}\n"
        )
        if snippet:
            clean_snippet = snippet[:400]
            message += f"\n<b>Updated Content:</b>\n{clean_snippet}"

        for user_id in allowed_ids:
            try:
                await self.telegram.send_text(chat_id=str(user_id), text=message)
                logger.info("Sent change notification to Telegram user %d", user_id)
            except Exception as exc:
                logger.error("Failed to send change notification to user %d: %s", user_id, exc)

    # --------------------------------------------------------------------------
    # Differential Check Execution
    # --------------------------------------------------------------------------

    async def check_watch(self, watch: Dict[str, Any]) -> Dict[str, Any]:
        """Perform differential content check on a single watch."""
        wid = watch["watch_id"]
        url = watch["url"]
        title = watch.get("title") or url
        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            content = await self.client.fetch_page_content(url)
        except Exception as exc:
            logger.warning("Failed to fetch monitored page %s: %s", url, exc)
            with transaction() as conn:
                conn.execute(
                    "UPDATE monitor_watches SET last_checked_at = ? WHERE watch_id = ?",
                    (now_iso, wid),
                )
            return {"watch_id": wid, "url": url, "status": "fetch_error", "error": str(exc)}

        record = ExternalRecord(
            source="monitoring",
            source_id=wid,
            record_type="change_alert",
            title=f"Change Watch: {title}",
            url=url,
            description=content[:2000] if content else None,
            metadata={
                "watch_id": wid,
                "url": url,
                "title": title,
                "full_length": len(content),
            },
        )

        record_id, status = upsert_record(record)

        with transaction() as conn:
            if status in ("inserted", "updated"):
                conn.execute(
                    "UPDATE monitor_watches SET last_checked_at = ?, last_changed_at = ? WHERE watch_id = ?",
                    (now_iso, now_iso, wid),
                )
            else:
                conn.execute(
                    "UPDATE monitor_watches SET last_checked_at = ? WHERE watch_id = ?",
                    (now_iso, wid),
                )

        if status == "updated":
            # Significant content modification detected!
            logger.info("Content change detected for watch: %s (%s)", title, url)
            await self.notify_users_of_change(title=title, url=url, snippet=content[:300])

        return {
            "watch_id": wid,
            "url": url,
            "status": status,
            "record_id": record_id,
        }

    async def check_all_watches(self) -> Dict[str, Any]:
        """Check all registered website watches."""
        watches = self.list_watches()
        results: Dict[str, Any] = {}
        changed_count = 0

        for w in watches:
            res = await self.check_watch(w)
            results[w["watch_id"]] = res
            if res.get("status") == "updated":
                changed_count += 1

        return {
            "total_watches": len(watches),
            "changes_detected": changed_count,
            "results": results,
        }

    # --------------------------------------------------------------------------
    # Webhook Ingestion (from ChangeDetection.io)
    # --------------------------------------------------------------------------

    async def handle_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest inbound change notification from ChangeDetection.io webhook."""
        url = payload.get("watch_url") or payload.get("url") or payload.get("current_url")
        if not url:
            return {"status": "ignored", "reason": "No URL in webhook payload"}

        title = payload.get("watch_title") or payload.get("title") or url
        diff_text = payload.get("diff") or payload.get("snapshot") or ""
        watch_id = payload.get("watch_uuid") or f"cdio_{uuid.uuid4().hex[:8]}"

        record = ExternalRecord(
            source="changedetection",
            source_id=watch_id,
            record_type="change_alert",
            title=f"Change Alert: {title}",
            url=url,
            description=diff_text[:2000] if diff_text else f"Website modified: {url}",
            metadata=payload,
        )

        res = await self.pipeline.ingest_batch([record], source_name="changedetection")
        await self.notify_users_of_change(title=title, url=url, snippet=diff_text[:300])

        return {
            "status": "processed",
            "url": url,
            "watch_id": watch_id,
            "ingested": res.model_dump(),
        }


monitoring_service = MonitoringService()
