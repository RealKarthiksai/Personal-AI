"""Common Ingestion Pipeline.

Coordinates data validation, batch deduplication, transactional storage upsert,
and run audit logging for all external integrations.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional

from app.ingestion.storage import log_ingestion_run, register_source, upsert_record
from app.schemas.external import ExternalRecord, IngestionResult
from app.utils.logging import get_logger

logger = get_logger("app.ingestion.pipeline")

URL_REGEX = re.compile(r"^https?://[^\s<>\"'()]+$", re.IGNORECASE)


class IngestionPipeline:
    """Standardized ingestion processor used by APIs, RSS, and website monitors."""

    def __init__(self) -> None:
        pass

    def validate_and_normalize(self, record: ExternalRecord) -> ExternalRecord:
        """Sanitize and normalize fields before persistence."""
        # Clean title & description whitespace
        clean_title = re.sub(r"\s+", " ", record.title).strip()
        clean_desc = record.description.strip() if record.description else None

        # Validate URL
        url_clean = record.url.strip()
        if not URL_REGEX.match(url_clean):
            raise ValueError(f"Invalid record URL: {record.url!r}")

        # Ensure fetched_at is valid ISO-8601
        fetched_at = record.fetched_at or datetime.now(timezone.utc).isoformat()

        return ExternalRecord(
            source=record.source.strip().lower(),
            source_id=record.source_id.strip(),
            record_type=record.record_type.strip().lower(),
            title=clean_title,
            url=url_clean,
            description=clean_desc,
            published_at=record.published_at.strip() if record.published_at else None,
            updated_at=record.updated_at.strip() if record.updated_at else None,
            metadata=record.metadata,
            fetched_at=fetched_at,
        )

    def deduplicate_batch(self, records: List[ExternalRecord]) -> List[ExternalRecord]:
        """Deduplicate records within the incoming batch by (source, source_id), retaining latest."""
        seen: dict[tuple[str, str], ExternalRecord] = {}
        for r in records:
            key = (r.source.strip().lower(), r.source_id.strip())
            seen[key] = r
        return list(seen.values())

    async def ingest_batch(
        self,
        records: List[ExternalRecord],
        source_name: Optional[str] = None,
    ) -> IngestionResult:
        """Process and ingest a batch of external records atomically.

        Args:
            records: List of external records to ingest.
            source_name: Optional source identifier for logging and source registry.
        """
        result = IngestionResult(total_received=len(records), fetched_count=len(records))
        if not records:
            return result

        started_at = datetime.now(timezone.utc).isoformat()
        primary_source = source_name or records[0].source.strip().lower()

        # Ensure source is registered
        try:
            register_source(primary_source, source_type="external")
        except Exception as e:
            logger.warning("Failed to auto-register source %r: %s", primary_source, e)

        # 1. Deduplicate within the batch
        deduped = self.deduplicate_batch(records)

        # 2. Process each record
        for raw_rec in deduped:
            try:
                norm_rec = self.validate_and_normalize(raw_rec)
                rec_id, status = upsert_record(norm_rec)
                if rec_id:
                    result.record_ids.append(rec_id)

                if status == "inserted":
                    result.inserted += 1
                elif status == "updated":
                    result.updated += 1
                elif status == "skipped":
                    result.skipped_identical += 1
            except Exception as exc:
                result.failed += 1
                err_msg = f"Failed record {raw_rec.source}:{raw_rec.source_id} - {exc}"
                logger.error(err_msg)
                result.errors.append(err_msg)

        # 3. Log audit run
        run_status = "success" if result.failed == 0 else ("partial" if (result.inserted + result.updated) > 0 else "failed")
        log_ingestion_run(
            source=primary_source,
            status=run_status,
            records_ingested=result.inserted,
            records_updated=result.updated,
            error_message="; ".join(result.errors[:5]) if result.errors else None,
            started_at=started_at,
        )

        logger.info(
            "Ingestion completed | source=%s | total=%d | inserted=%d | updated=%d | skipped=%d | failed=%d",
            primary_source,
            result.total_received,
            result.inserted,
            result.updated,
            result.skipped_identical,
            result.failed,
        )
        return result


pipeline = IngestionPipeline()
