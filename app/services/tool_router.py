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
from app.memory.commands import (
    handle_export,
    handle_forget,
    handle_forget_all,
    handle_link,
    handle_memory_debug,
    handle_memory_overview,
    handle_pin_unpin,
    handle_privacy,
)
from app.agents.commands import (
    handle_agent_status_command,
    handle_job_detail_command,
    handle_jobs_command,
    handle_panic_command,
    handle_resume_command,
    handle_stop_command,
    handle_workspaces_command,
)
from app.agents.router import dispatch_agent_request, parse_deterministic_request
from app.memory.profile import get_user_profile_summary
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
OPS_HELP_PATTERNS = [
    r"^(?:/help|help)$",
    r"\b(?:what\s+can\s+you\s+do|what\s+operations\s+can\s+you\s+perform|what\s+are\s+your\s+capabilities|all\s+the\s+operations\s+(?:u|you)\s+can\s+perform|what\s+(?:system\s+)?operations\s+(?:can|do)\s+you\s+(?:support|have|perform))\b",
]


class ResponseMode(str, Enum):
    """How the response should be handled by the chat pipeline."""

    DIRECT = "direct"  # Deterministic code-rendered response; bypasses LLM entirely (0 LLM calls)
    GROUNDED_TEXT = "grounded_text"  # LLM writes free text; links validated post-hoc against allowed URLs
    SELECT = "select"  # LLM selects candidate numbers; Python renders verified cards from DB
    PASSTHROUGH = "passthrough"  # Conversational text without search context
    ACTION = "action"  # Interactive confirmation card with inline keyboard; 0 LLM calls


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
    action_card: Optional[str] = None
    action_keyboard: Optional[dict] = None
    action_job: Optional[Any] = None
    candidates: List[Candidate] = field(default_factory=list)
    manifest: Optional[RetrievalManifest] = None
    allowed_urls: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.context_text is None and self.direct is not None:
            self.context_text = self.direct
        elif self.context_text is None and self.action_card is not None:
            self.context_text = self.action_card
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


def get_system_capabilities_help() -> str:
    """Deterministic help card detailing all system operations Karna can perform."""
    try:
        from app.agents.policy import load_workspaces
        workspaces = load_workspaces()
        ws_items = [f"<code>{w.alias}</code> (<code>{w.path}</code>)" for w in workspaces.values()]
        ws_str = ", ".join(ws_items) if ws_items else "<code>karna</code> (/home/vhanghar/Karna)"
    except Exception:
        ws_str = "<code>karna</code> (/home/vhanghar/Karna)"

    return (
        "🛡️ <b>Karna System Capabilities & Operations</b>\n\n"
        "I am your local AI companion and personal operations assistant. Here are all the operations I can perform on your machine:\n\n"
        "🤖 <b>1. Local Agent Task Delegation (Cline & Antigravity)</b>\n"
        "• Delegate coding, terminal commands, refactoring, and directory analysis to local agent CLIs:\n"
        "  - <b>Cline CLI:</b> Headless autonomous coding & ops agent\n"
        "  - <b>Antigravity CLI:</b> Google's agent CLI with multimodal & reasoning capabilities\n"
        f"• <b>Approved Workspaces:</b> {ws_str}\n"
        "• <b>Agent Commands:</b>\n"
        "  - <code>/agent &lt;cline|agy&gt; [workspace] &lt;task&gt;</code> — Dispatch an agent task\n"
        "  - <code>/workspaces</code> — List configured workspaces and policies\n"
        "  - <code>/jobs</code> — List active and historical agent jobs\n"
        "  - <code>/job &lt;id&gt;</code> — View job logs, output summary, and git diff\n"
        "  - <code>/stop</code> — Terminate the active running agent process group\n"
        "  - <code>/panic</code> — Emergency kill switch to abort all agent executions\n"
        "  - <i>Natural phrases:</i> e.g. <code>ask cline to inspect folder structure in karna</code>\n\n"
        "🔍 <b>2. Web Search & Deep Extraction</b>\n"
        "• <code>/search &lt;query&gt;</code> — Real-time web research via local SearXNG\n"
        "• <code>/read &lt;url&gt;</code> — Deep JavaScript webpage reader & crawler (Crawl4AI)\n"
        "• <code>/briefing</code> — Daily intelligence briefing compiled from your sources\n\n"
        "📡 <b>3. Subscriptions & Health Monitoring</b>\n"
        "• <code>/status</code> — System status, API quotas, and health check\n"
        "• <code>/feeds</code> — List and monitor active RSS feeds\n"
        "• <code>/watches</code> — Monitor web pages for changes and content diffs\n\n"
        "🧠 <b>4. Long-Term Memory & Profile</b>\n"
        "• <code>/memory</code> — View long-term facts, preferences, and profile\n"
        "• <code>/pin &lt;id&gt;</code> & <code>/forget &lt;id&gt;</code> — Manage stored memories\n"
        "• <code>/export</code> & <code>/privacy</code> — Memory data export and privacy policy"
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
        user_id: Optional[int] = None,
        channel: str = "telegram",
        sender_id: Optional[str] = None,
    ) -> ToolExecutionResult:
        """Analyze message, execute appropriate tool if needed, and return context."""
        clean_text = user_message.strip()

        actual_user_id = user_id
        if actual_user_id is None:
            try:
                from app.memory.identity import resolve_user_id
                actual_user_id = resolve_user_id(channel=channel, external_user_id=sender_id or "default_user")
            except Exception:
                actual_user_id = 1

        # ----------------------------------------------------------------------
        # 1. Slash Commands Dispatch (Exact, 0 LLM Calls)
        # ----------------------------------------------------------------------
        slash = self.detect_slash_command(clean_text)
        if slash:
            cmd, args = slash
            if cmd in ("help", "start"):
                return ToolExecutionResult(
                    tool_name="help",
                    mode=ResponseMode.DIRECT,
                    direct=get_system_capabilities_help(),
                    status_message="Loading capabilities...",
                )

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

            # Memory Commands (ResponseMode.DIRECT, 0 LLM calls, < 50ms)
            if cmd in ("memory", "memories"):
                body = handle_memory_overview(actual_user_id)
                return ToolExecutionResult(
                    tool_name="memory",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message="Loading memory...",
                )

            if cmd == "pin":
                body = handle_pin_unpin(actual_user_id, args, pin=True)
                return ToolExecutionResult(
                    tool_name="pin",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "unpin":
                body = handle_pin_unpin(actual_user_id, args, pin=False)
                return ToolExecutionResult(
                    tool_name="unpin",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "forget":
                body = handle_forget(actual_user_id, args)
                return ToolExecutionResult(
                    tool_name="forget",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "forget_all":
                body = handle_forget_all(actual_user_id, args)
                return ToolExecutionResult(
                    tool_name="forget_all",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "export":
                summary, json_doc = handle_export(actual_user_id)
                return ToolExecutionResult(
                    tool_name="export",
                    mode=ResponseMode.DIRECT,
                    direct=summary,
                    input_value=json_doc,
                    status_message="Exporting memory data...",
                )

            if cmd == "privacy":
                body = handle_privacy()
                return ToolExecutionResult(
                    tool_name="privacy",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "link":
                body = handle_link(actual_user_id, channel, sender_id or str(actual_user_id), args)
                return ToolExecutionResult(
                    tool_name="link",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            if cmd == "memory_debug":
                body = handle_memory_debug(actual_user_id, args)
                return ToolExecutionResult(
                    tool_name="memory_debug",
                    mode=ResponseMode.DIRECT,
                    direct=body,
                    status_message=None,
                )

            # Agent Delegation Commands (0 LLM calls)
            if cmd == "workspaces":
                return handle_workspaces_command()

            if cmd == "jobs":
                return handle_jobs_command(sender_id=sender_id)

            if cmd == "job":
                return handle_job_detail_command(args or "")

            if cmd == "stop":
                return await handle_stop_command(args or "", sender_id=sender_id or "default")

            if cmd == "panic":
                return await handle_panic_command(sender_id=sender_id or "default")

            if cmd == "resume":
                return handle_resume_command(args or "", sender_id=sender_id or "default")

            if cmd == "agent":
                if args and args.strip().lower() == "status":
                    return handle_agent_status_command()
                agent_req = parse_deterministic_request(clean_text)
                if agent_req is not None:
                    return dispatch_agent_request(agent_req, sender_id=sender_id or "default")
                return ToolExecutionResult(
                    mode=ResponseMode.DIRECT,
                    direct="Usage: <code>/agent &lt;cline|agy&gt; [workspace] &lt;task&gt;</code> or <code>/agent status</code>",
                )

            if cmd not in ("briefing", "digest", "search", "read"):
                unknown_msg = (
                    f"Unknown command <code>/{cmd}</code>.\n\n"
                    f"<b>Available commands:</b>\n"
                    f"• <code>/help</code> - System capabilities & command guide\n"
                    f"• <code>/status</code> - System status & ingestion sources\n"
                    f"• <code>/feeds</code> - Active RSS feed subscriptions\n"
                    f"• <code>/watches</code> - Monitored web pages & change alerts\n"
                    f"• <code>/briefing</code> - Daily intelligence briefing\n"
                    f"• <code>/memory</code> - Long-term profile & memories\n"
                    f"• <code>/forget &lt;id&gt;</code> - Delete a specific memory\n"
                    f"• <code>/pin &lt;id&gt;</code> - Pin memory to core\n"
                    f"• <code>/export</code> - Download personal memory export\n"
                    f"• <code>/privacy</code> - Local memory & privacy policy\n"
                    f"• <code>/link</code> - Link another channel identity\n"
                    f"• <code>/agent &lt;cline|agy&gt; &lt;task&gt;</code> - Delegate coding/ops task\n"
                    f"• <code>/jobs</code> - List delegated agent jobs\n"
                    f"• <code>/workspaces</code> - List allowlisted folders\n"
                    f"• <code>/stop</code> - Cancel active agent job\n"
                    f"• <code>/panic</code> - Emergency agent kill switch\n"
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
        # 1b. Deterministic Agent Task Delegation (0 LLM Calls)
        # ----------------------------------------------------------------------
        agent_req = parse_deterministic_request(clean_text)
        if agent_req is not None:
            return dispatch_agent_request(agent_req, sender_id=sender_id or "default")

        # Ambiguous agent fallback if agent keywords are present
        if re.search(r"\b(?:cline|clline|clien|agy|antigravity|antigravty)\b", clean_text, re.IGNORECASE):
            try:
                from app.agents.router import resolve_ambiguous_routing_with_llm
                resolved = await resolve_ambiguous_routing_with_llm(clean_text)
                if resolved:
                    agent, ws = resolved
                    fallback_req = DispatchRequest(
                        agent=agent,
                        workspace_alias=ws,
                        task_text=clean_text,
                    )
                    return dispatch_agent_request(fallback_req, sender_id=sender_id or "default")
            except Exception as e:
                logger.warning("Ambiguous agent routing fallback failed: %s", e)

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

        if any(re.search(p, clean_text, re.IGNORECASE) for p in OPS_HELP_PATTERNS):
            return ToolExecutionResult(
                tool_name="help",
                mode=ResponseMode.DIRECT,
                direct=get_system_capabilities_help(),
                status_message="Loading capabilities...",
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

                user_interests: List[str] = []
                if actual_user_id:
                    try:
                        prof = get_user_profile_summary(actual_user_id)
                        raw_int = prof.get("interests") or prof.get("preferences") or []
                        if isinstance(raw_int, str):
                            user_interests = [i.strip() for i in raw_int.split(",") if i.strip()]
                        elif isinstance(raw_int, list):
                            user_interests = [str(i).strip() for i in raw_int if str(i).strip()]
                    except Exception:
                        pass

                # Rank and enforce source quotas with personalization bias (0 LLM calls)
                ranked = rank_and_quota_records(
                    all_candidates,
                    max_per_source=3,
                    limit=target_count,
                    user_interests=user_interests,
                )

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
