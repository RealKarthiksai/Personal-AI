"""Channel-agnostic ResponseMode.DIRECT command handlers for memory management."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.memory.identity import generate_link_code, get_user_identities, redeem_link_code
from app.memory.models import MemoryTier
from app.memory.profile import get_user_profile_summary
from app.memory.repository import (
    get_memory,
    hard_delete_all_memories,
    hard_delete_memory,
    list_memories,
    list_profile_fields,
    pin_memory,
    search_memories_fts,
)
from app.memory.retrieval import debug_context
from app.utils.logging import get_logger

logger = get_logger("app.memory.commands")


def handle_memory_overview(user_id: int) -> str:
    """Handle /memory: Displays active profile, pinned memories, and tier counts."""
    profile = get_user_profile_summary(user_id)
    memories = list_memories(user_id=user_id, limit=50)

    lines = ["🧠 <b>Long-Term Memory Overview</b>\n"]

    # Profile section
    if profile:
        lines.append("👤 <b>User Profile:</b>")
        for k, v in profile.items():
            lines.append(f"• <b>{k.replace('_', ' ').capitalize()}:</b> {v}")
        lines.append("")

    # Pinned / Core facts
    pinned_or_core = [m for m in memories if m.pinned or m.tier == MemoryTier.CORE]
    if pinned_or_core:
        lines.append(f"📌 <b>Pinned & Core Memories ({len(pinned_or_core)}):</b>")
        for m in pinned_or_core[:8]:
            pin_badge = "📌 " if m.pinned else "⭐ "
            lines.append(f"• <code>[{m.id}]</code> {pin_badge}{m.text}")
        lines.append("")

    # Recent active facts
    recent = [m for m in memories if not m.pinned and m.tier != MemoryTier.CORE]
    if recent:
        lines.append(f"📝 <b>Recent Stored Memories ({len(recent)}):</b>")
        for m in recent[:6]:
            lines.append(f"• <code>[{m.id}]</code> ({m.tier.value}) {m.text}")
        lines.append("")

    if not profile and not memories:
        lines.append("No long-term memories or profile data stored yet.")
        lines.append("You can tell Karna things to remember like: <i>'Remember that I prefer concise answers'</i> or <i>'I live in Hyderabad'</i>.")

    # Linked identities
    identities = get_user_identities(user_id)
    if identities:
        channels_str = ", ".join(f"{i['channel']}" for i in identities)
        lines.append(f"🔗 <b>Linked Channels:</b> {channels_str}")

    return "\n".join(lines)


def handle_pin_unpin(user_id: int, args: Optional[str], pin: bool = True) -> str:
    """Handle /pin <id> and /unpin <id>."""
    if not args or not args.strip().isdigit():
        action = "pin" if pin else "unpin"
        return f"Please provide a numeric memory ID. Usage: <code>/{action} &lt;id&gt;</code> (find IDs in <code>/memory</code>)."

    mem_id = int(args.strip())
    success = pin_memory(user_id=user_id, memory_id=mem_id, pinned=pin)
    if not success:
        return f"Memory item <code>[{mem_id}]</code> not found or not owned by you."

    status = "pinned 📌 (will never decay)" if pin else "unpinned"
    return f"Memory item <code>[{mem_id}]</code> has been {status}."


def handle_forget(user_id: int, args: Optional[str]) -> str:
    """Handle /forget <id or text>."""
    if not args or not args.strip():
        return (
            "Usage: <code>/forget &lt;id&gt;</code> to remove a specific memory, "
            "or <code>/forget &lt;keyword&gt;</code> to find and delete matching memories.\n"
            "Use <code>/forget_all</code> to clear all memories."
        )

    clean_arg = args.strip()
    if clean_arg.isdigit():
        mem_id = int(clean_arg)
        deleted = hard_delete_memory(user_id=user_id, memory_id=mem_id)
        if deleted:
            return f"🗑️ Memory item <code>[{mem_id}]</code> permanently deleted."
        return f"Memory item <code>[{mem_id}]</code> not found."

    # Search and delete matching memory
    matches = search_memories_fts(user_id=user_id, query_text=clean_arg, limit=5)
    if not matches:
        return f"No memories found matching <i>{clean_arg}</i>."

    if len(matches) == 1:
        mem = matches[0]
        if mem.id is not None:
            hard_delete_memory(user_id=user_id, memory_id=mem.id)
            return f"🗑️ Deleted matching memory <code>[{mem.id}]</code>: <i>{mem.text}</i>"

    lines = ["Found multiple matching memories. Specify the exact ID to delete using <code>/forget &lt;id&gt;</code>:\n"]
    for m in matches:
        lines.append(f"• <code>[{m.id}]</code> {m.text}")
    return "\n".join(lines)


def handle_forget_all(user_id: int, args: Optional[str]) -> str:
    """Handle /forget_all with two-step confirmation."""
    clean_arg = (args or "").strip().lower()
    if clean_arg != "confirm":
        return (
            "⚠️ <b>Warning: Clear All Memories</b>\n\n"
            "This will permanently delete all your stored profile data, personal notes, "
            "and long-term memories across all linked channels.\n\n"
            "To proceed, send: <code>/forget_all confirm</code>"
        )

    count = hard_delete_all_memories(user_id=user_id)
    return f"🗑️ All your stored memories ({count} items) and profile attributes have been permanently deleted."


def handle_export(user_id: int) -> Tuple[str, Optional[str]]:
    """Handle /export: Generates JSON data of all user memories.

    Returns (summary_html, export_json_string).
    """
    profile = get_user_profile_summary(user_id)
    memories = list_memories(user_id=user_id, limit=500)
    identities = get_user_identities(user_id)

    export_data = {
        "user_id": user_id,
        "exported_at": "",
        "profile": profile,
        "identities": identities,
        "memories": [
            {
                "id": m.id,
                "tier": m.tier.value,
                "period": m.period,
                "text": m.text,
                "importance": m.importance,
                "confidence": m.confidence,
                "category": m.category,
                "pinned": m.pinned,
                "source": m.source.value,
                "channels": m.source_channels,
                "created_at": m.created_at,
            }
            for m in memories
        ],
    }

    from datetime import datetime, timezone
    export_data["exported_at"] = datetime.now(timezone.utc).isoformat()
    json_str = json.dumps(export_data, indent=2)

    summary = (
        f"📦 <b>Personal Data Export</b>\n\n"
        f"• Profile Attributes: {len(profile)}\n"
        f"• Stored Memories: {len(memories)}\n"
        f"• Linked Channels: {len(identities)}\n\n"
        f"Your data has been packaged into the attached JSON file."
    )
    return summary, json_str


def handle_privacy() -> str:
    """Handle /privacy: Explains local retention and decay policies."""
    return (
        "🔒 <b>Karna Privacy & Data Policies</b>\n\n"
        "1. <b>100% Local & Offline:</b> Your memories and conversation histories never leave this machine. No cloud APIs or third parties receive your data.\n"
        "2. <b>Automatic Time-Decay:</b> Ephemeral notes decay over time (daily → weekly → monthly). Only core facts and pinned items survive permanently.\n"
        "3. <b>Secret Redaction:</b> Passwords, API tokens, credit cards, and government IDs are automatically scrubbed and never stored.\n"
        "4. <b>Complete Control:</b>\n"
        "   • <code>/forget &lt;id&gt;</code> - Delete a specific memory\n"
        "   • <code>/forget_all</code> - Wipe all your stored data\n"
        "   • <code>/export</code> - Download a complete JSON copy of your profile and memories"
    )


def handle_link(user_id: int, channel: str, external_user_id: str, args: Optional[str]) -> str:
    """Handle /link [code]: Generates pairing code or redeems one."""
    clean_code = (args or "").strip()

    if not clean_code:
        # Generate 6-digit link code
        code = generate_link_code(user_id=user_id, expiry_minutes=10)
        return (
            f"🔗 <b>Cross-Channel Account Linking</b>\n\n"
            f"Your temporary linking code is: <code>{code}</code>\n\n"
            f"To link another channel (e.g. WhatsApp or another account), open that channel and send:\n"
            f"<code>/link {code}</code>\n\n"
            f"<i>This code expires in 10 minutes.</i>"
        )

    # Redeem link code
    success, msg, target_id = redeem_link_code(
        code=clean_code,
        channel=channel,
        external_user_id=external_user_id,
    )
    if success:
        return f"✅ <b>Channel Linked!</b>\n\n{msg} Your identity on <b>{channel}</b> now shares the same memory and profile."
    return f"❌ <b>Linking Failed</b>\n\n{msg}"


def handle_memory_debug(user_id: int, args: Optional[str]) -> str:
    """Handle /memory_debug <query>: Displays raw prompt context injection block."""
    query = (args or "general context").strip()
    raw_ctx = debug_context(user_id, query)
    if not raw_ctx:
        return "No memory context would be injected for this query."
    return f"🔍 <b>Memory Debug Context Injection:</b>\n\n<pre>{raw_ctx}</pre>"
