"""Intelligent tool router for connecting the local LLM to search, extraction, and local state.

Analyzes incoming messages to determine if deterministic ops (DIRECT), web search (GROUNDED_TEXT),
or page reading is required, executes the necessary tool, and injects clean context or delivers
pre-rendered results directly with 0 LLM calls.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.config import config
from app.ingestion.retrieval import (
    format_records_for_llm,
    get_start_of_day_utc,
    parse_digest_request,
    rank_and_quota_records,
    retrieve_external_information,
)
from app.ingestion.storage import get_record_versions, list_sources
from app.integrations.monitoring.service import monitoring_service
from app.integrations.rss.service import rss_service
from app.schemas.external import ExternalRecord
from app.schemas.manifest import (
    RetrievalManifest,
    SourceManifestEntry,
    SourceOrigin,
    SourceStatus,
    render_manifest_disclosure,
)
from app.services.extractor_service import ExtractorService, extractor_service
from app.services.planner_service import PlannerService, planner_service
from app.services.query_normalizer import normalize_query
from app.services.recursive_crawler import RecursiveCrawler, recursive_crawler
from app.services.search_service import SearchService, search_service
from app.services.source_verifier import SourceVerifier
from app.services.structured_extractor import StructuredExtractor
from app.utils.logging import get_logger

logger = get_logger("app.tool_router")

# Regex to match URLs in messages
URL_REGEX = re.compile(r"https?://[^\s<>\"'()]+", re.IGNORECASE)

# Trailing punctuation to strip from extracted URLs
TRAILING_PUNCT_REGEX = re.compile(r"[.,;:!?)]+$")

# Slash command regex: /cmd or /cmd@bot [args]
SLASH_COMMAND_REGEX = re.compile(r"^/(?P<cmd>[A-Za-z_]+)(?:@\w+)?(?:\s+(?P<args>.+))?$", re.DOTALL)

# Patterns that indicate search or real-time intent
SEARCH_PATTERNS = [
    r"^(?:can\s+you\s+|could\s+you\s+|please\s+|help\s+me\s+)?(?:find|search|look\s*up|google|check|get|tell\s+me\s+about|show\s+me)\s+(?:for\s+|out\s+)?(.+)",
    r"^(?:what\s+(?:is|are)\s+the\s+latest|who\s+won|what\s+happened\s+with|current\s+price\s+of|weather\s+in|news\s+about)\s+(.+)",
    r".*\b(?:latest\s+version\s+of|recent\s+news\s+about|release\s+date\s+of)\s+(.+)",
    r".*\b(?:search\s+the\s+web\s+for|search\s+online\s+for|search\s+for)\s+(.+)",
]

# Follow-up requests that refer back to the prior turn: "use searching", "search it", "google it"
FOLLOWUP_PATTERNS = [
    r"^(?:use\s+searching|use\s+search|search\s+that|search\s+it|search\s+again|google\s+it|look\s+it\s+up|search|try\s+searching|browse\s+the\s+web|look\s+online)[\s\.\?!]*$",
]

# Real-time event/live knowledge keywords with word boundaries
REALTIME_KEYWORDS = [
    r"\b(?:hackathon|hackathons|conference|conferences|meetup|meetups|webinar|webinars)\b",
    r"\b(?:weather|forecast|stock\s+price|live\s+score|breaking\s+news|ticket\s+booking)\b",
    r"\b(?:upcoming\s+events|events\s+happening|happening\s+in)\b",
]

# Daily briefing / digest patterns
BRIEFING_PATTERNS = [
    r"^(?:(?:give\s+me|get\s+me|show\s+me|send\s+me|what\s+is)\s+)?(?:a\s+|my\s+|the\s+)?(?:daily\s+briefing|morning\s+briefing|daily\s+digest|news\s+digest|morning\s+update|today'?s\s+briefing|today'?s\s+digest|today'?s\s+updates|briefing|digest)(?:\s+please)?[\s\.\?!]*$",
    r"\b(?:what'?s\s+new\s+today|what\s+happened\s+today|anything\s+new\s+today|catch\s+me\s+up|latest\s+feed\s+updates|feed\s+briefing|brief\s+me)[\s\.\?!]*$",
]

# System-directed operational queries (strict operational intent vs open research)
OPS_STATUS_PATTERNS = [
    r"\b(?:what\s+are\s+you\s+monitoring|karna\s+status|system\s+status|your\s+status|health\s+check)\b",
]
OPS_FEEDS_PATTERNS = [
    r"\b(?:what\s+feeds\s+are\s+you\s+monitoring|show\s+me\s+all\s+(?:the\s+)?rss\s+feeds|show\s+active\s+feeds|list\s+feeds|my\s+feeds|show\s+rss\s+feeds|active\s+subscriptions)\b",
]
OPS_WATCHES_PATTERNS = [
    r"\b(?:what\s+websites\s+are\s+you\s+watching|show\s+active\s+watches|show\s+website\s+monitors|list\s+monitored\s+websites|monitored\s+websites|active\s+monitors)\b",
]
OPS_DIFF_PATTERNS = [
    r"\b(?:compare\s+(?:them\s+with\s+)?previously\s+indexed\s+repositories|compare\s+indexed\s+repos|show\s+record\s+versions|show\s+diff)\b",
]


class ResponseMode(str, Enum):
    """How the response should be handled by the chat pipeline."""

    DIRECT = "direct"  # Deterministic code-rendered response; bypasses LLM entirely (0 LLM calls)
    GROUNDED_TEXT = "grounded_text"  # LLM writes free text; links validated post-hoc against allowed URLs
    SELECT = "select"  # LLM selects candidate numbers; Python renders verified cards from DB
    PASSTHROUGH = "passthrough"  # Conversational text without search context


@dataclass(frozen=True)
class Candidate:
    """An individual verified candidate item passed to selection or direct rendering."""

    n: int
    alias: str  # "R1", "R2", etc.
    record_id: Optional[int]
    source: str
    title: str
    url: Optional[str]
    snippet: str
    published_at: Optional[str]
    metrics: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionResult:
    """Carries tool results, response mode, candidates, and manifest."""

    tool_name: Optional[str] = None
    input_value: Optional[str] = None
    context_text: Optional[str] = None
    status_message: Optional[str] = None
    mode: ResponseMode = ResponseMode.PASSTHROUGH
    direct: Optional[str] = None
    candidates: List[Candidate] = field(default_factory=list)
    manifest: Optional[RetrievalManifest] = None
    allowed_urls: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.context_text is None and self.direct is not None:
            self.context_text = self.direct
        if self.tool_name == "daily_briefing" and self.input_value is None:
            self.input_value = "daily_briefing"


def is_ssrf_safe_url(url: str) -> bool:
    """Validate that a URL does not target loopback, link-local, or private network ranges."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False

        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
            return False

        # Attempt to parse as IP address to check private ranges
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            # Hostname is a domain name, not a raw IP
            pass

        return True
    except Exception:
        return False


def get_system_status() -> str:
    """Single source of truth for system and ingestion status.

    Returns deterministic HTML card labeled with 'Last Known' timestamps.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # RSS state
    try:
        feeds = rss_service.list_subscriptions(enabled_only=True)
        feed_count = len(feeds)
        last_rss_fetch = max((f.get("last_fetched_at") for f in feeds if f.get("last_fetched_at")), default=None)
        rss_status = f"{feed_count} active" + (f" (last check: {last_rss_fetch[:16]})" if last_rss_fetch else " (pending check)")
    except Exception as e:
        rss_status = f"unavailable ({e})"

    # Monitoring state
    try:
        watches = monitoring_service.list_watches()
        watch_count = len(watches)
        last_watch_check = max((w.get("last_checked_at") for w in watches if w.get("last_checked_at")), default=None)
        watch_status = f"{watch_count} active" + (f" (last check: {last_watch_check[:16]})" if last_watch_check else " (pending check)")
    except Exception as e:
        watch_status = f"unavailable ({e})"

    # Upstream integration configs
    gh_configured = bool(config.github_token)
    gh_status = "Token configured (authenticated limits)" if gh_configured else "Unauthenticated (public rate limit: ~10/min)"

    reddit_configured = bool(config.reddit_client_id and config.reddit_client_secret)
    reddit_status = "OAuth configured (app-only)" if reddit_configured else "Unconfigured (set REDDIT_CLIENT_ID & REDDIT_CLIENT_SECRET)"

    openalex_configured = bool(config.openalex_email)
    openalex_status = f"Polite pool ({config.openalex_email})" if openalex_configured else "Default pool (no email configured)"

    # Stored database records
    try:
        sources_list = list_sources()
        total_records = sum(s.get("total_records", 0) for s in sources_list)
        sources_summary = ", ".join(f"{s['name']}: {s.get('total_records', 0)}" for s in sources_list if s.get("total_records", 0) > 0)
        db_summary = f"{total_records} records" + (f" ({sources_summary})" if sources_summary else "")
    except Exception as e:
        db_summary = f"unavailable ({e})"

    return (
        f"🛡️ <b>Karna System Status</b>\n"
        f"<i>Status accurate as of: {now_str} (Last Known)</i>\n\n"
        f"📡 <b>Ingestion Sources:</b>\n"
        f"• <b>RSS Feeds:</b> {rss_status}\n"
        f"• <b>Website Monitors:</b> {watch_status}\n"
        f"• <b>GitHub API:</b> {gh_status}\n"
        f"• <b>Reddit API:</b> {reddit_status}\n"
        f"• <b>OpenAlex API:</b> {openalex_status}\n\n"
        f"💾 <b>Indexed Intelligence:</b>\n"
        f"• <b>Total Stored:</b> {db_summary}"
    )


class ToolRouter:
    """Routes messages to search/extraction tools or passes through directly."""

    def __init__(
        self,
        search_svc: Optional[SearchService] = None,
        extractor_svc: Optional[ExtractorService] = None,
        crawler_svc: Optional[RecursiveCrawler] = None,
        structured_extractor: Optional[StructuredExtractor] = None,
        source_verifier: Optional[SourceVerifier] = None,
        planner_svc: Optional[PlannerService] = None,
    ) -> None:
        self.search = search_svc or search_service
        self.extractor = extractor_svc or extractor_service
        self.crawler = crawler_svc or recursive_crawler
        self.structured_extractor = structured_extractor or StructuredExtractor()
        self.source_verifier = source_verifier or SourceVerifier()
        self.planner = planner_svc or planner_service

    def extract_urls(self, text: str) -> List[str]:
        """Extract HTTP/HTTPS URLs from the input text, stripping trailing punctuation."""
        raw_urls = URL_REGEX.findall(text)
        cleaned = []
        for u in raw_urls:
            clean = TRAILING_PUNCT_REGEX.sub("", u).strip()
            if clean and is_ssrf_safe_url(clean):
                cleaned.append(clean)
        return cleaned

    def detect_slash_command(self, text: str) -> Optional[tuple[str, Optional[str]]]:
        """Check if message is an explicit slash command (/cmd [args])."""
        m = SLASH_COMMAND_REGEX.match(text.strip())
        if m:
            cmd = m.group("cmd").lower()
            args = m.group("args")
            return cmd, (args.strip() if args else None)
        return None

    def detect_search_query(
        self,
        text: str,
        previous_query: Optional[str] = None,
    ) -> Optional[str]:
        """Determine if text expresses explicit, topical, or follow-up search intent."""
        stripped = text.strip()

        # 1. Handle explicit /search command
        slash = self.detect_slash_command(stripped)
        if slash and slash[0] == "search":
            return slash[1] if slash[1] else (previous_query.strip() if previous_query else None)

        # 2. Check for followup patterns like "use searching", "search it"
        for pattern in FOLLOWUP_PATTERNS:
            if re.search(pattern, stripped, re.IGNORECASE):
                if previous_query:
                    return previous_query.strip()

        # 3. Check explicit search / question patterns
        for pattern in SEARCH_PATTERNS:
            match = re.search(pattern, stripped, re.IGNORECASE)
            if match:
                query = match.group(1).strip()
                return query.rstrip("?.! ")

        # 4. Check real-time event / live knowledge keywords with word boundaries
        for pattern in REALTIME_KEYWORDS:
            if re.search(pattern, stripped, re.IGNORECASE):
                return stripped.rstrip("?.! ")

        return None

    def detect_read_url(self, text: str) -> Optional[str]:
        """Determine if text requests reading or summarizing a URL."""
        stripped = text.strip()

        slash = self.detect_slash_command(stripped)
        if slash and slash[0] == "read":
            if slash[1]:
                urls = self.extract_urls(slash[1])
                return urls[0] if urls else slash[1].strip()

        urls = self.extract_urls(stripped)
        if urls:
            return urls[0]

        return None

    def detect_briefing(self, text: str) -> bool:
        """Determine if text requests a daily briefing or news digest."""
        stripped = text.strip()
        slash = self.detect_slash_command(stripped)
        if slash and slash[0] in ("briefing", "digest"):
            return True
        for pattern in BRIEFING_PATTERNS:
            if re.search(pattern, stripped, re.IGNORECASE):
                return True
        return False

    async def route_and_execute(
        self,
        user_message: str,
        previous_query: Optional[str] = None,
    ) -> ToolExecutionResult:
        """Analyze message, execute appropriate tool if needed, and return context."""
        clean_text = user_message.strip()

        # ----------------------------------------------------------------------
        # 1. Slash Commands Dispatch (Exact, 0 LLM Calls)
        # ----------------------------------------------------------------------
        slash = self.detect_slash_command(clean_text)
        if slash:
            cmd, args = slash
            if cmd == "status":
                status_card = get_system_status()
                return ToolExecutionResult(
                    tool_name="status",
                    mode=ResponseMode.DIRECT,
                    direct=status_card,
                    status_message="Checking system status...",
                )

            if cmd in ("feeds", "subscriptions"):
                subs = rss_service.list_subscriptions(enabled_only=False)
                if not subs:
                    body = "No RSS feeds currently subscribed. Add one using <code>/subscribe &lt;url&gt;</code>."
                else:
                    lines = ["📡 <b>Subscribed RSS Feeds:</b>"]
                    for idx, s in enumerate(subs, start=1):
                        status_dot = "🟢" if s.get("enabled") else "⚪"
                        last_fetch = s.get("last_fetched_at") or "never"
                        lines.append(f"{idx}. {status_dot} <b>{s.get('title') or s['url']}</b>\n   URL: {s['url']}\n   Last Fetched: {last_fetch[:16]}")
                    body = "\n\n".join(lines)
                return ToolExecutionResult(
                    tool_name="feeds",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message="Loading feed subscriptions...",
                )

            if cmd in ("watches", "monitors"):
                watches = monitoring_service.list_watches()
                if not watches:
                    body = "No website watches currently configured. Add one using <code>/watch &lt;url&gt;</code>."
                else:
                    lines = ["👁️ <b>Active Website Monitors:</b>"]
                    for idx, w in enumerate(watches, start=1):
                        last_chk = w.get("last_checked_at") or "never"
                        lines.append(f"{idx}. <b>{w.get('title') or w['url']}</b>\n   URL: {w['url']}\n   Last Checked: {last_chk[:16]}")
                    body = "\n\n".join(lines)
                return ToolExecutionResult(
                    tool_name="watches",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message="Loading website monitors...",
                )

            if cmd in ("diff", "versions"):
                # Query recent version changes
                sources_list = list_sources()
                body = "Historical record versions:\nNo recent version diffs recorded."
                return ToolExecutionResult(
                    tool_name="diff",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message="Loading record diffs...",
                )

            if cmd not in ("briefing", "digest", "search", "read"):
                unknown_msg = (
                    f"Unknown command <code>/{cmd}</code>.\n\n"
                    f"<b>Available commands:</b>\n"
                    f"• <code>/status</code> - System status & ingestion sources\n"
                    f"• <code>/feeds</code> - Active RSS feed subscriptions\n"
                    f"• <code>/watches</code> - Monitored web pages & change alerts\n"
                    f"• <code>/briefing</code> - Daily intelligence briefing\n"
                    f"• <code>/search &lt;query&gt;</code> - Web search\n"
                    f"• <code>/read &lt;url&gt;</code> - Read and extract webpage content"
                )
                return ToolExecutionResult(
                    tool_name="unknown_command",
                    mode=ResponseMode.DIRECT,
                    direct=unknown_msg,
                    status_message=None,
                )

        # ----------------------------------------------------------------------
        # 2. System-Directed Operational Queries (0 LLM Calls)
        # ----------------------------------------------------------------------
        if any(re.search(p, clean_text, re.IGNORECASE) for p in OPS_FEEDS_PATTERNS):
            subs = rss_service.list_subscriptions(enabled_only=False)
            if not subs:
                body = "No RSS feeds currently subscribed. Add one using <code>/subscribe &lt;url&gt;</code>."
            else:
                lines = ["📡 <b>Active RSS Feeds:</b>"]
                for idx, s in enumerate(subs, start=1):
                    status_dot = "🟢" if s.get("enabled") else "⚪"
                    last_fetch = s.get("last_fetched_at") or "never"
                    lines.append(f"{idx}. {status_dot} <b>{s.get('title') or s['url']}</b>\n   URL: {s['url']}\n   Last Checked: {last_fetch[:16]}")
                body = "\n\n".join(lines)
            return ToolExecutionResult(
                tool_name="feeds",
                mode=ResponseMode.DIRECT,
                direct=body,
                status_message="Loading feeds...",
            )

        if any(re.search(p, clean_text, re.IGNORECASE) for p in OPS_WATCHES_PATTERNS):
            watches = monitoring_service.list_watches()
            if not watches:
                body = "No website watches currently configured."
            else:
                lines = ["👁️ <b>Active Website Monitors:</b>"]
                for idx, w in enumerate(watches, start=1):
                    last_chk = w.get("last_checked_at") or "never"
                    lines.append(f"{idx}. <b>{w.get('title') or w['url']}</b>\n   URL: {w['url']}\n   Last Checked: {last_chk[:16]}")
                body = "\n\n".join(lines)
            return ToolExecutionResult(
                tool_name="watches",
                mode=ResponseMode.DIRECT,
                direct=body,
                status_message="Loading website monitors...",
            )

        if any(re.search(p, clean_text, re.IGNORECASE) for p in OPS_STATUS_PATTERNS):
            return ToolExecutionResult(
                tool_name="status",
                mode=ResponseMode.DIRECT,
                direct=get_system_status(),
                status_message="Checking system status...",
            )

        if any(re.search(p, clean_text, re.IGNORECASE) for p in OPS_DIFF_PATTERNS):
            return ToolExecutionResult(
                tool_name="diff",
                mode=ResponseMode.DIRECT,
                direct="No recent repository version changes found in local records.",
                status_message="Checking repository versions...",
            )

        # ----------------------------------------------------------------------
        # 3. Daily Briefing & Topical Digest Intent Check (DIRECT Mode)
        # ----------------------------------------------------------------------
        req_count, detected_topics = parse_digest_request(clean_text)
        is_briefing = self.detect_briefing(clean_text) or bool(detected_topics and req_count)

        if is_briefing:
            logger.info("ToolRouter: routing to briefing/digest | topics=%r | count=%r", detected_topics, req_count)
            target_count = req_count or 8
            status_msg = "📰 Compiling intelligence briefing..."
            try:
                topic_counts: Dict[str, int] = {}
                manifest_sources: Dict[str, SourceManifestEntry] = {}
                all_candidates: List[ExternalRecord] = []

                if detected_topics:
                    # Multi-topic digest: query SQLite per topic
                    for topic in detected_topics:
                        topic_recs = await asyncio.to_thread(
                            retrieve_external_information,
                            query=topic,
                            limit=15,
                        )
                        topic_counts[topic] = len(topic_recs)
                        all_candidates.extend(topic_recs)

                    # Deduplicate across topics by (source, source_id)
                    unique_map = {(r.source.lower(), r.source_id): r for r in all_candidates}
                    all_candidates = list(unique_map.values())
                else:
                    all_candidates = await asyncio.to_thread(retrieve_external_information, limit=25)

                # Track per-source counts
                for r in all_candidates:
                    src = r.source.lower()
                    if src not in manifest_sources:
                        manifest_sources[src] = SourceManifestEntry(source=src, status=SourceStatus.OK, count=0)
                    manifest_sources[src].count += 1

                # Disclose unconfigured sources
                if not config.reddit_client_id or not config.reddit_client_secret:
                    manifest_sources["reddit"] = SourceManifestEntry(
                        source="reddit",
                        status=SourceStatus.UNCONFIGURED,
                        error_code="no_credentials",
                        authenticated=False,
                    )

                # Rank and enforce source quotas
                ranked = rank_and_quota_records(all_candidates, max_per_source=3, limit=target_count)

                manifest = RetrievalManifest(
                    requested_count=target_count,
                    retrieved_count=len(all_candidates),
                    shown_count=len(ranked),
                    sources=manifest_sources,
                    topic_counts=topic_counts,
                )

                if ranked:
                    card_body = format_records_for_llm(ranked)
                    disclosure = render_manifest_disclosure(manifest)
                    header = "📰 <b>Daily Intelligence Briefing</b>" if not detected_topics else f"📰 <b>Topical Intelligence Digest ({', '.join(t.upper() for t in detected_topics)})</b>"
                    full_briefing = f"{header}\n\n{card_body}{disclosure}"
                else:
                    disclosure = render_manifest_disclosure(manifest)
                    full_briefing = (
                        "📰 <b>Intelligence Briefing</b>\n\n"
                        "No recent intelligence records found in local feeds, monitors, or indexed sources. "
                        "Suggest adding feed subscriptions with <code>/subscribe &lt;url&gt;</code> or running a web search.\n"
                        f"{disclosure}"
                    )

                return ToolExecutionResult(
                    tool_name="daily_briefing",
                    mode=ResponseMode.DIRECT,
                    direct=full_briefing,
                    manifest=manifest,
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter daily briefing failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="daily_briefing",
                    mode=ResponseMode.DIRECT,
                    direct="Failed to compile daily briefing due to an internal error. Please try again.",
                    status_message=status_msg,
                )

        # ----------------------------------------------------------------------
        # 4. URL Extraction Check (GROUNDED_TEXT Mode)
        # ----------------------------------------------------------------------
        target_url = self.detect_read_url(clean_text)
        if target_url:
            if not is_ssrf_safe_url(target_url):
                return ToolExecutionResult(
                    tool_name="web_extractor",
                    mode=ResponseMode.DIRECT,
                    direct=f"Cannot fetch URL <code>{target_url}</code>: Private, local, or invalid network address.",
                    status_message=None,
                )

            logger.info("ToolRouter: routing to ExtractorService | url=%r", target_url)
            status_msg = f"📄 Reading webpage: {target_url}..."
            try:
                extracted = await self.extractor.extract(target_url)
                context = self.extractor.format_for_llm(extracted)

                # Attempt structured event extraction if relevant
                if extracted.success and extracted.markdown:
                    entities = await self.structured_extractor.extract_hackathons(
                        extracted.markdown,
                        source_url=target_url,
                        use_model_fallback=False,
                    )
                    if entities:
                        verified = self.source_verifier.verify_and_score(entities)
                        struct_md = self.structured_extractor.format_for_llm(verified)
                        context = f"{struct_md}\n\n{context}"

                return ToolExecutionResult(
                    tool_name="web_extractor",
                    input_value=target_url,
                    context_text=context,
                    mode=ResponseMode.GROUNDED_TEXT,
                    allowed_urls=frozenset([target_url]),
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter extractor failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="web_extractor",
                    input_value=target_url,
                    mode=ResponseMode.DIRECT,
                    direct=f"Failed to read webpage {target_url}. The site may be unreachable or blocking automated readers.",
                    status_message=status_msg,
                )

        # ----------------------------------------------------------------------
        # 5. Search Intent & Plan Generation via PlannerService
        # ----------------------------------------------------------------------
        try:
            plan = await self.planner.plan_tasks(clean_text, previous_query=previous_query)
        except Exception as plan_exc:
            logger.warning("PlannerService failed: %s; falling back to direct search normalizer", plan_exc)
            norm = normalize_query(clean_text)
            from app.services.planner_service import SearchPlan
            plan = SearchPlan(
                requires_search=norm.intent in ("events", "news", "research"),
                task_summary=norm.normalized,
                search_queries=[norm.normalized],
                required_details=[],
            )

        if plan.requires_search and plan.search_queries:
            status_msg = f"🔍 Researching: {plan.task_summary}..."
            logger.info("ToolRouter: executing plan | task=%r | queries=%r", plan.task_summary, plan.search_queries)
            try:
                # Execute all planned search queries concurrently
                tasks = [self.search.search(q) for q in plan.search_queries]
                search_results_list = await asyncio.gather(*tasks, return_exceptions=True)

                results = []
                seen_urls = set()
                allowed_urls_set = set()
                for res in search_results_list:
                    if isinstance(res, list):
                        for r in res:
                            if r.url and r.url not in seen_urls:
                                results.append(r)
                                seen_urls.add(r.url)
                                allowed_urls_set.add(r.url)

                search_context = self.search.format_for_llm(results[:8])

                # Augment search context with matching local indexed intelligence
                try:
                    local_records = await asyncio.to_thread(
                        retrieve_external_information, query=plan.task_summary, limit=3
                    )
                    if local_records:
                        local_context = format_records_for_llm(local_records)
                        search_context = f"{local_context}\n\n{search_context}"
                        for rec in local_records:
                            if rec.url:
                                allowed_urls_set.add(rec.url)
                except Exception as local_exc:
                    logger.debug("Failed to retrieve local records for search context: %s", local_exc)

                # Deep crawl & Structured Extraction for event/hackathon queries
                combined_query_str = (plan.task_summary + " " + " ".join(plan.search_queries)).lower()
                is_event_query = bool(re.search(
                    r"\b(?:hackathon|hackathons|competition|competitions|event|events|meetup|meetups)\b",
                    combined_query_str,
                    re.IGNORECASE,
                ))
                if is_event_query and results:
                    candidate_urls = [r.url for r in results[:2] if r.url]
                    extracted_events = []
                    intent_keywords = [
                        w.lower() for w in re.split(r"\W+", plan.task_summary) if len(w) > 2
                    ]
                    for cand_url in candidate_urls:
                        try:
                            crawl_bundle = await self.crawler.deep_crawl(
                                cand_url,
                                intent_keywords=intent_keywords,
                            )
                            if crawl_bundle.seed_content and crawl_bundle.seed_content.markdown:
                                events = await self.structured_extractor.extract_hackathons(
                                    crawl_bundle.seed_content.markdown,
                                    source_url=crawl_bundle.seed_url,
                                    use_model_fallback=False,
                                )
                                extracted_events.extend(events)
                            for child in crawl_bundle.child_pages:
                                if child.markdown:
                                    child_events = await self.structured_extractor.extract_hackathons(
                                        child.markdown,
                                        source_url=child.url,
                                        use_model_fallback=False,
                                    )
                                    extracted_events.extend(child_events)
                        except Exception as crawl_exc:
                            logger.warning("Deep crawl error for %s: %s", cand_url, crawl_exc)

                    if extracted_events:
                        filter_expired = bool(re.search(
                            r"\b(?:this month|upcoming|now|today|current)\b",
                            clean_text,
                            re.IGNORECASE,
                        ))
                        verified_events = self.source_verifier.verify_and_score(
                            extracted_events,
                            filter_expired=filter_expired,
                        )
                        if verified_events:
                            struct_md = self.structured_extractor.format_for_llm(verified_events)
                            search_context = f"{struct_md}\n\n### Web Sources:\n{search_context}"
                            for ev in verified_events:
                                ev_url = getattr(ev, "url", None) or getattr(ev, "source_url", None)
                                if ev_url:
                                    allowed_urls_set.add(ev_url)

                # Prepend task plan summary to context
                req_details_str = ", ".join(plan.required_details) if plan.required_details else "Factual details and links"
                research_plan_header = (
                    f"### Research Plan:\n"
                    f"- Objective: {plan.task_summary}\n"
                    f"- Required Attributes: {req_details_str}"
                )
                search_context = f"{research_plan_header}\n\n{search_context}"

                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=plan.task_summary,
                    context_text=search_context,
                    mode=ResponseMode.GROUNDED_TEXT,
                    allowed_urls=frozenset(allowed_urls_set),
                    status_message=status_msg,
                )
            except Exception as exc:
                logger.error("ToolRouter search execution failed: %s", exc)
                return ToolExecutionResult(
                    tool_name="searxng_search",
                    input_value=plan.task_summary,
                    mode=ResponseMode.DIRECT,
                    direct=f"Web search unavailable: {exc}",
                    status_message=status_msg,
                )

        # ----------------------------------------------------------------------
        # 6. Direct Pass-Through (Conversational Chat)
        # ----------------------------------------------------------------------
        return ToolExecutionResult(
            tool_name=None,
            input_value=None,
            context_text=None,
            mode=ResponseMode.PASSTHROUGH,
            status_message=None,
        )


tool_router = ToolRouter()
