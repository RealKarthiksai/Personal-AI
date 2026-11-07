"""Database storage and retrieval operations for the Common Ingestion Pipeline.

Provides atomic upsert with SHA-256 content hashing, version tracking of changed
content, query filtering, and run metric logging.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database.database import transaction
from app.schemas.external import ExternalRecord, ExternalRecordQuery
from app.utils.logging import get_logger

logger = get_logger("app.ingestion.storage")


def compute_content_hash(
    title: str,
    description: Optional[str],
    url: str,
    metadata: Dict[str, Any],
) -> str:
    """Compute deterministic SHA-256 hash of core content fields to detect modifications."""
    canonical_meta = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
    payload = f"{title.strip()}|{(description or '').strip()}|{url.strip()}|{canonical_meta}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_record(record: ExternalRecord) -> Tuple[int, str]:
    """Atomically upsert an external record.

    Returns:
        tuple (record_id, status) where status is:
        - 'inserted': New record created.
        - 'updated': Existing record modified (previous version archived).
        - 'skipped': Existing record identical (no content change).
    """
    content_hash = compute_content_hash(
        record.title,
        record.description,
        record.url,
        record.metadata,
    )
    meta_json = json.dumps(record.metadata, ensure_ascii=False)

    with transaction() as conn:
        existing = conn.execute(
            """
            SELECT id, title, description, metadata, content_hash
            FROM external_records
            WHERE source = ? AND source_id = ?
            """,
            (record.source, record.source_id),
        ).fetchone()

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO external_records
                    (source, source_id, record_type, title, url, description,
                     published_at, updated_at, fetched_at, metadata, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source,
                    record.source_id,
                    record.record_type,
                    record.title.strip(),
                    record.url.strip(),
                    record.description.strip() if record.description else None,
                    record.published_at,
                    record.updated_at,
                    record.fetched_at,
                    meta_json,
                    content_hash,
                ),
            )
            return int(cur.lastrowid), "inserted"

        existing_id = int(existing["id"])
        existing_hash = existing["content_hash"]

        # If content has not changed at all, skip without updating
        if existing_hash == content_hash:
            return existing_id, "skipped"

        # Content changed: archive previous version into record_versions
        conn.execute(
            """
            INSERT INTO record_versions
                (record_id, title, description, metadata, content_hash, changed_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                existing_id,
                existing["title"],
                existing["description"],
                existing["metadata"],
                existing_hash,
            ),
        )

        # Update the live record with new content and update timestamp
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE external_records
            SET title = ?,
                url = ?,
                description = ?,
                published_at = COALESCE(?, published_at),
                updated_at = ?,
                fetched_at = ?,
                metadata = ?,
                content_hash = ?
            WHERE id = ?
            """,
            (
                record.title.strip(),
                record.url.strip(),
                record.description.strip() if record.description else None,
                record.published_at,
                record.updated_at or now_iso,
                record.fetched_at,
                meta_json,
                content_hash,
                existing_id,
            ),
        )
        return existing_id, "updated"


def query_records(params: ExternalRecordQuery) -> List[ExternalRecord]:
    """Retrieve external records based on query parameters."""
    clauses: List[str] = []
    args: List[Any] = []

    if params.query and params.query.strip():
        q_term = f"%{params.query.strip()}%"
        clauses.append("(title LIKE ? OR description LIKE ?)")
        args.extend([q_term, q_term])

    if params.sources:
        placeholders = ",".join("?" for _ in params.sources)
        clauses.append(f"source IN ({placeholders})")
        args.extend(params.sources)

    if params.record_types:
        placeholders = ",".join("?" for _ in params.record_types)
        clauses.append(f"record_type IN ({placeholders})")
        args.extend(params.record_types)

    if params.since:
        clauses.append("(published_at >= ? OR fetched_at >= ?)")
        args.extend([params.since, params.since])

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT id, source, source_id, record_type, title, url, description,
               published_at, updated_at, metadata, fetched_at
        FROM external_records
        {where_sql}
        ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC
        LIMIT ? OFFSET ?
    """
    args.extend([params.limit, params.offset])

    with transaction() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()

    results: List[ExternalRecord] = []
    for r in rows:
        meta_dict = {}
        if r["metadata"]:
            try:
                meta_dict = json.loads(r["metadata"])
            except Exception:
                meta_dict = {}
        results.append(
            ExternalRecord(
                id=r["id"],
                source=r["source"],
                source_id=r["source_id"],
                record_type=r["record_type"],
                title=r["title"],
                url=r["url"],
                description=r["description"],
                published_at=r["published_at"],
                updated_at=r["updated_at"],
                metadata=meta_dict,
                fetched_at=r["fetched_at"],
            )
        )
    return results


def get_record_versions(record_id: int) -> List[dict]:
    """Return historical versions for a given record id, newest first."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, record_id, title, description, metadata, content_hash, changed_at
            FROM record_versions
            WHERE record_id = ?
            ORDER BY changed_at DESC, id DESC
            """,
            (record_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_ingestion_run(
    source: str,
    status: str,
    records_ingested: int = 0,
    records_updated: int = 0,
    error_message: Optional[str] = None,
    started_at: Optional[str] = None,
) -> int:
    """Log an ingestion execution run for auditability and observability."""
    start_time = started_at or datetime.now(timezone.utc).isoformat()
    end_time = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO ingestion_runs
                (source, status, records_ingested, records_updated, error_message, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                status,
                records_ingested,
                records_updated,
                error_message,
                start_time,
                end_time,
            ),
        )
        return int(cur.lastrowid)


def list_sources() -> List[dict]:
    """Return list of registered sources with record counts."""
    with transaction() as conn:
        rows = conn.execute(
            """
            SELECT s.name, s.source_type, s.base_url, s.enabled,
                   COUNT(e.id) AS total_records,
                   MAX(e.fetched_at) AS last_fetched_at
            FROM sources s
            LEFT JOIN external_records e ON s.name = e.source
            GROUP BY s.name, s.source_type, s.base_url, s.enabled
            ORDER BY s.name ASC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def register_source(
    name: str,
    source_type: str,
    base_url: Optional[str] = None,
) -> int:
    """Register or enable a source provider."""
    with transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO sources (name, source_type, base_url, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(name) DO UPDATE SET
                source_type = excluded.source_type,
                base_url = COALESCE(excluded.base_url, sources.base_url),
                enabled = 1
            """,
            (name, source_type, base_url),
        )
        return int(cur.lastrowid)
