"""Deterministic routing and constrained-LLM fallback for agent task delegation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.agents.confirmations import create_confirmation, render_confirmation_card
from app.agents.jobs import get_job_manager
from app.agents.models import AgentJob, AgentKind, DispatchRequest, JobMode
from app.agents.policy import (
    get_workspace,
    is_panic_active,
    load_workspaces,
    validate_dispatch_policy,
)
from app.config import config
from app.services.llm_client import LLMClient
from app.utils.logging import get_logger

logger = get_logger("app.agents.router")


def _get_router_types():
    from app.services.tool_router import ResponseMode, ToolExecutionResult
    return ResponseMode, ToolExecutionResult

# Regex patterns for deterministic agent invocation
SLASH_AGENT_REGEX = re.compile(
    r"^/agent\s+(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)(?:\s+(?P<workspace>[a-zA-Z0-9_\-]+))?\s+(?P<task>.+)$",
    re.IGNORECASE | re.DOTALL,
)

NATURAL_AGENT_PATTERNS = [
    # Direct address: "antigravity 2.0, here's what I need you to do: <task>", "cline: run tests", "antigravity: extract frontend"
    re.compile(
        r"^(?:(?:hey|hi|hello)\s+)?(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)\s*[,:]\s*(?:(?:here(?:'s|’s| is)\s+(?:what\s+)?(?:i\s+need\s+you\s+to\s+do|i\s+want\s+you\s+to\s+do|to\s+do)|please|can\s+you)\s*[:,\-]?\s*)?(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    # "give/send a message/instructions/task to antigravity 2.0 to/that/for <task>"
    re.compile(
        r"^(?:(?:can|could)\s+you\s+|please\s+)?(?:give|send|pass)\s+(?:a\s+)?(?:message|instructions?|prompt|task)\s+to\s+(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)\s+(?:(?:to\s+|that\s+|so\s+(?:it|he|she)\s+can\s+|for\s+|:\s*))*(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    # "ask/tell/have/get cline to run tests in karna", "ask agy to refactor"
    re.compile(
        r"^(?:(?:can|could)\s+you\s+|please\s+)?(?:ask|tell|have|get|instruct)\s+(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)\s+(?:to\s+|for\s+)?(?:(?:in|on|for)\s+(?P<workspace>[a-zA-Z0-9_\-]+)\s+)?(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    # "use/run antigravity to update the scheduler in karna"
    re.compile(
        r"^(?:(?:can|could)\s+you\s+|please\s+)?(?:use|run(?:\s+with)?)\s+(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)\s+(?:to\s+|for\s+)?(?:(?:in|on|for)\s+(?P<workspace>[a-zA-Z0-9_\-]+)\s+)?(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    # "with cline: run tests"
    re.compile(
        r"^with\s+(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)\s*:\s*(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    # "send messages/tasks to antigravity and/or cline ... <task>"
    re.compile(
        r"^(?:.*?\b(?:send(?:\s+messages?|\s+tasks?)?\s+to|(?:delegate\s+to))\s+)(?P<agent>cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty)(?:(?:\s+and\s+|\s*,\s*|\s+or\s+)(?:cline|clline|clien|antigravity(?:\s*2(?:\.0)?)?|agy(?:\s*2(?:\.0)?)?|antigravty))*\s+(?:(?:to|that|and)\s+|i\s+want\s+(?:you\s+to\s+)?|please\s+|:\s*)*(?P<task>.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
]

EDIT_INTENT_KEYWORDS = re.compile(
    r"\b(?:fix|edit|modify|refactor|update|write|create|implement|patch|change|delete|remove|add)\b",
    re.IGNORECASE,
)


def parse_agent_kind(agent_str: str) -> Optional[AgentKind]:
    """Map string representation to AgentKind enum."""
    norm = agent_str.strip().lower()
    norm = re.sub(r"\s*(?:2(?:\.0)?|v\d+)\b", "", norm).strip()
    if norm in ("cline", "clline", "clien"):
        return AgentKind.CLINE
    elif norm in ("agy", "antigravity", "antigravty"):
        return AgentKind.ANTIGRAVITY
    return None


def parse_deterministic_request(text: str) -> Optional[DispatchRequest]:
    """Parse explicit agent commands and high-confidence natural language patterns."""
    raw = text.strip().replace("’", "'").replace("‘", "'")

    # 1. /agent slash command
    m = SLASH_AGENT_REGEX.match(raw)
    if m:
        agent = parse_agent_kind(m.group("agent"))
        ws_candidate = m.group("workspace")
        task = m.group("task").strip()

        # If the workspace candidate is not an actual workspace alias, it might be the start of the task
        workspaces = load_workspaces()
        workspace_alias = None
        if ws_candidate and ws_candidate.lower() in workspaces:
            workspace_alias = ws_candidate.lower()
        elif ws_candidate:
            task = f"{ws_candidate} {task}"

        if agent and task:
            is_edit = bool(EDIT_INTENT_KEYWORDS.search(task))
            return DispatchRequest(
                agent=agent,
                workspace_alias=workspace_alias,
                task_text=task,
                mode=JobMode.EDIT if is_edit else JobMode.READ_ONLY,
            )

    # 2. Natural language patterns
    for pattern in NATURAL_AGENT_PATTERNS:
        m = pattern.match(raw)
        if m:
            agent = parse_agent_kind(m.group("agent"))
            ws_candidate = m.groupdict().get("workspace")
            task = m.group("task").strip()

            workspaces = load_workspaces()
            workspace_alias = None
            if ws_candidate and ws_candidate.lower() in workspaces:
                workspace_alias = ws_candidate.lower()
            elif ws_candidate:
                task = f"{ws_candidate} {task}"

            if agent and task:
                if not workspace_alias:
                    for ws_key, ws_cfg in workspaces.items():
                        if (
                            ws_cfg.path.lower() in task.lower()
                            or re.search(rf"\b(?:in|on|at|for|from)\s+({re.escape(ws_key)})\b", task, re.IGNORECASE)
                            or re.search(rf"\b{re.escape(ws_key)}\b", task, re.IGNORECASE)
                        ):
                            workspace_alias = ws_key
                            break

                is_edit = bool(EDIT_INTENT_KEYWORDS.search(task))
                return DispatchRequest(
                    agent=agent,
                    workspace_alias=workspace_alias,
                    task_text=task,
                    mode=JobMode.EDIT if is_edit else JobMode.READ_ONLY,
                )

    return None


async def resolve_ambiguous_routing_with_llm(
    text: str,
    llm_client: Optional[LLMClient] = None,
) -> Optional[Tuple[AgentKind, Optional[str]]]:
    """Fallback: call local LLM with constrained JSON output to resolve agent and workspace."""
    workspaces = load_workspaces()
    ws_list = list(workspaces.keys())

    prompt = (
        f"You are a routing dispatcher. Classify the user's task delegation request.\n"
        f"Available agents: [\"cline\", \"antigravity\"]\n"
        f"Available workspaces: {json.dumps(ws_list)}\n\n"
        f"User request: \"{text}\"\n\n"
        f"Return ONLY a JSON object with this exact schema:\n"
        f'{{"agent": "cline|antigravity|ask", "workspace": "<workspace_alias>|ask"}}'
    )

    client = llm_client or LLMClient()
    try:
        raw_resp = await client.generate(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw_resp.strip())
        agent_str = str(data.get("agent", "")).lower()
        ws_str = str(data.get("workspace", "")).lower()

        agent = parse_agent_kind(agent_str)
        workspace = ws_str if ws_str in workspaces else None

        if agent:
            return agent, workspace
    except Exception as e:
        logger.warning("Constrained LLM routing fallback failed: %s", e)

    return None


def dispatch_agent_request(req: DispatchRequest, sender_id: str) -> "ToolExecutionResult":
    """Validate policy, persist pending job and confirmation, and return interactive ACTION card."""
    ResponseMode, ToolExecutionResult = _get_router_types()
    workspaces = load_workspaces()

    # Resolve workspace if omitted
    resolved_alias = req.workspace_alias
    if not resolved_alias:
        if len(workspaces) == 1:
            resolved_alias = list(workspaces.keys())[0]
        else:
            # Check if any workspace alias is mentioned in task text
            for alias in workspaces.keys():
                if re.search(rf"\b{re.escape(alias)}\b", req.task_text, re.IGNORECASE):
                    resolved_alias = alias
                    break

    if not resolved_alias or resolved_alias not in workspaces:
        # Prompt user with interactive buttons to pick a workspace
        buttons = [
            [{"text": f"📂 {ws.alias}", "callback_data": f"agent:pick:{ws.alias}"}]
            for ws in workspaces.values()
        ]
        return ToolExecutionResult(
            mode=ResponseMode.ACTION,
            action_card=(
                f"❓ <b>Which workspace should {req.agent.value} use?</b>\n\n"
                f"Task: <i>\"{html.escape(req.task_text)}\"</i>"
            ),
            action_keyboard={"inline_keyboard": buttons},
        )

    ws = workspaces[resolved_alias]

    # Validate security and permission policy
    ok, err = validate_dispatch_policy(
        sender_id=sender_id,
        agent=req.agent,
        workspace=ws,
        mode=req.mode,
        autonomous=req.autonomous,
    )
    if not ok:
        return ToolExecutionResult(
            mode=ResponseMode.DIRECT,
            direct=f"🚫 <b>Policy Denial</b>\n\n{html.escape(err or 'Operation rejected by security policy.')}",
        )

    # Create job and confirmation records
    full_req = DispatchRequest(
        agent=req.agent,
        workspace_alias=resolved_alias,
        task_text=req.task_text,
        mode=req.mode,
        autonomous=req.autonomous,
        conversation_id=req.conversation_id,
    )
    mgr = get_job_manager()
    job = mgr.create_job(full_req, sender_id=sender_id)
    record, short_id = create_confirmation(job)

    # Render confirmation card
    card_html, keyboard = render_confirmation_card(job, ws, record.nonce)

    return ToolExecutionResult(
        mode=ResponseMode.ACTION,
        action_card=card_html,
        action_keyboard=keyboard,
        action_job=job,
    )
