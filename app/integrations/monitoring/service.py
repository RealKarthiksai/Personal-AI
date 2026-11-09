"""Website monitoring service.

Manages page watches in SQLite, performs differential content checks,
ingests change alerts into the Common Ingestion Pipeline, and dispatches
Telegram notifications.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import config
from app.database.database import transaction
from app.database.repository import save_extracted_entity
from app.ingestion.pipeline import IngestionPipeline, pipeline as default_pipeline
from app.ingestion.storage import get_record_versions, upsert_record
from app.integrations.monitoring.client import ChangeDetectionClient, monitoring_client
from app.schemas.entities import Hackathon
from app.schemas.external import ExternalRecord, IngestionResult
from app.services.telegram_client import TelegramClient
from app.utils.logging import get_logger

logger = get_logger("app.integrations.monitoring.service")


def _format_iso_date(val: Optional[str]) -> Optional[str]:
    """Format an ISO-8601 date string to human readable date."""
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return val[:10]


def _format_date_range(start: Optional[str], end: Optional[str]) -> Optional[str]:
    """Format start and end ISO dates into a readable range."""
    s = _format_iso_date(start)
    e = _format_iso_date(end)
    if s and e:
        if s == e:
            return s
        return f"{s} - {e}"
    return s or e or "Dates TBA"


def extract_hackathons_from_html(url: str, html_text: str) -> List[Hackathon]:
    """Extract structured Hackathon objects from HTML content."""
    if not html_text:
        return []

    hackathons: List[Hackathon] = []

    # 1. Devfolio Next.js dehydrated state parsing
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            props = data.get("props", {}).get("pageProps", {})
            queries = props.get("dehydratedState", {}).get("queries", [])
            for q in queries:
                if q.get("queryKey") == "fetchAllHackathonTypes":
                    st = q.get("state", {}).get("data", {})
                    # Focus on open and upcoming hackathons
                    raw_items = st.get("open_hackathons", []) + st.get("upcoming_hackathons", [])
                    for item in raw_items:
                        name = item.get("name")
                        if not name:
                            continue
                        slug = item.get("slug")
                        is_online = item.get("is_online", True)
                        location = "Online / Virtual" if is_online else "In-Person (Offline)"

                        themes_raw = item.get("themes") or []
                        theme_names = []
                        for t in themes_raw:
                            if isinstance(t, dict):
                                t_info = t.get("theme")
                                if isinstance(t_info, dict) and t_info.get("name"):
                                    theme_names.append(t_info["name"])
                                elif t.get("name"):
                                    theme_names.append(t["name"])
                        details = ", ".join(theme_names) if theme_names else "Open Innovation"

                        starts_at = item.get("starts_at")
                        ends_at = item.get("ends_at")
                        event_date_str = _format_date_range(starts_at, ends_at)

                        settings = item.get("settings") or {}
                        deadline_raw = settings.get("reg_ends_at")
                        deadline_str = _format_iso_date(deadline_raw) if deadline_raw else None

                        reg_url = settings.get("external_apply_url") or (f"https://{slug}.devfolio.co" if slug else url)
                        prize_str = item.get("prize") or item.get("prizes") or "Check page for details"

                        hackathons.append(
                            Hackathon(
                                name=name,
                                organizer="Devfolio",
                                deadline=deadline_str,
                                event_date=event_date_str,
                                location=location,
                                eligibility=details,
                                prize=str(prize_str) if prize_str else None,
                                registration_url=reg_url,
                                source_url=url,
                                confidence="HIGH",
                            )
                        )
        except Exception as exc:
            logger.warning("Failed to extract hackathons from __NEXT_DATA__: %s", exc)

    return hackathons


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

    async def notify_hackathon(self, hackathon: Hackathon) -> None:
        """Dispatch clean, formatted hackathon notification to Telegram."""
        if not config.is_telegram_configured():
            logger.info("Telegram not configured; skipping hackathon notification dispatch")
            return

        allowed_ids = config.allowed_telegram_user_ids
        if not allowed_ids:
            logger.info("No allowed Telegram user IDs configured; skipping hackathon notification dispatch")
            return

        name = html.escape(hackathon.name or "Unnamed Hackathon")
        location = html.escape(hackathon.location or "Online / Virtual")
        details = html.escape(hackathon.eligibility or hackathon.organizer or "Check event details")
        prize = html.escape(hackathon.prize or "See website for details")
        dates = html.escape(hackathon.event_date or "Dates TBA")
        if hackathon.deadline:
            dates += f" (Reg Deadline: {html.escape(hackathon.deadline)})"
        link = hackathon.registration_url or hackathon.source_url

        message = (
            f"🚀 <b>New Hackathon Detected!</b>\n\n"
            f"🏆 <b>Name:</b> {name}\n"
            f"📍 <b>Place:</b> {location}\n"
            f"📝 <b>Details:</b> {details}\n"
            f"💰 <b>Amount:</b> {prize}\n"
            f"🗓️ <b>Date & Time:</b> {dates}\n"
            f"🔗 <b>Link:</b> {link}"
        )

        for user_id in allowed_ids:
            try:
                await self.telegram.send_text(chat_id=str(user_id), text=message)
                logger.info("Sent hackathon notification for '%s' to Telegram user %d", hackathon.name, user_id)
            except Exception as exc:
                logger.error("Failed to send hackathon notification to user %d: %s", user_id, exc)

    async def notify_users_of_change(self, title: str, url: str, snippet: Optional[str] = None) -> None:
        """Dispatch Telegram alert to configured allowed users."""
        if not config.is_telegram_configured():
            logger.info("Telegram not configured; skipping change notification dispatch")
            return

        allowed_ids = config.allowed_telegram_user_ids
        if not allowed_ids:
            logger.info("No allowed Telegram user IDs configured; skipping change notification dispatch")
            return

        clean_title = html.escape(title)
        message = (
            f"🔔 <b>Website Change Detected</b>\n\n"
            f"<b>Source:</b> {clean_title}\n"
            f"<b>URL:</b> {url}\n"
        )
        if snippet:
            clean_snippet = re.sub(r"\s+", " ", snippet).strip()[:400]
            clean_snippet = html.escape(clean_snippet)
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
        is_hackathon_site = any(kw in url.lower() or kw in title.lower() for kw in ("hackathon", "devfolio", "bounty", "contest"))

        raw_html = ""
        if is_hackathon_site and hasattr(self.client, "fetch_page_raw"):
            try:
                raw_res = await self.client.fetch_page_raw(url)
                if isinstance(raw_res, str):
                    raw_html = raw_res
            except Exception as exc:
                logger.debug("Failed to fetch raw HTML for %s: %s", url, exc)

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
                "full_length": len(content) if content else 0,
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

        if is_hackathon_site:
            html_source = raw_html or (content if isinstance(content, str) else "")
            hackathons = extract_hackathons_from_html(url, html_source)
            if hackathons:
                with transaction() as conn:
                    rows = conn.execute(
                        "SELECT name FROM extracted_entities WHERE entity_type = 'hackathon'"
                    ).fetchall()
                    existing_names = {r["name"].strip().lower() for r in rows}

                new_hackathons = [h for h in hackathons if h.name.strip().lower() not in existing_names]

                # Save new hackathons into extracted_entities
                for h in new_hackathons:
                    save_extracted_entity(
                        entity_type="hackathon",
                        name=h.name,
                        structured_data=h.model_dump_json(),
                        source_url=h.registration_url or url,
                        content_hash=hashlib.sha256(h.name.encode()).hexdigest()[:16],
                    )

                if status == "updated":
                    if new_hackathons:
                        logger.info("Detected %d new hackathons for watch: %s", len(new_hackathons), title)
                        for h in new_hackathons:
                            await self.notify_hackathon(h)
                    else:
                        logger.info("Page content changed for %s, but no new hackathons were detected (suppressing alert)", title)
        elif status == "updated":
            # Significant content modification detected on a general watch!
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

        # Check all watches in parallel using asyncio.gather
        coros = [self.check_watch(w) for w in watches]
        res_list = await asyncio.gather(*coros)

        for w, res in zip(watches, res_list):
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
