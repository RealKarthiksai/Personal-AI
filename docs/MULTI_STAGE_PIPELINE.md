# Multi-Stage Local LLM Pipeline Architecture

## Overview

Karna incorporates a multi-stage local LLM pipeline designed to run on constrained hardware (16 GB unified/system RAM) without crashing or running out of memory. It splits execution between a fast small model (Qwen 3.5 2B/4B) for planning and evidence extraction and a smart medium model (Qwen 3.5 9B) for factual synthesis and personality projection.

```mermaid
sequenceDiagram
    autonumber
    actor User as Telegram User
    participant TG as Telegram Bot
    participant CS as ChatService
    participant Jobs as Background Job Manager
    participant Fast as Fast LLM (:8081)
    participant Search as SearXNG & Fetcher
    participant Smart as Smart LLM (:8082)

    User->>TG: Send message ("What is the latest SpaceX launch status?")
    TG->>CS: process_inbound()
    CS->>Jobs: on_message()
    Jobs->>Fast: planner.plan(text, history)
    Fast--Jobs: Plan: {needs_search: true, queries: [...]}
    Jobs--User: Immediate ACK ("On it. This takes a few minutes...")
    Note over Jobs: Spawns async background research task
    
    par Async Research Worker
        Jobs->>Search: gather(queries) [Parallel HTTP]
        Search-->>Jobs: Raw HTML pages
        Jobs->>Fast: filter_pages() [3-Tier Evidence Filtering]
        Fast-->>Jobs: Verified verbatim quotes
        Jobs->>Smart: synth.synthesize(question, quotes)
        Smart-->>Jobs: Factual draft with [1], [2] citations
        Jobs->>Smart: persona.rewrite(draft, question)
        Smart-->>Jobs: Final response in Karna's voice
        Jobs->>TG: send_text() [Sequential chunks with 0.3s delay]
        TG->>User: Deliver final formatted response
    and Front-Desk Channel
        User->>TG: "hi" or "done yet?"
        TG->>CS: process_inbound()
        CS->>Jobs: on_message()
        Jobs->>Fast: Immediate reply / status check
        Jobs--User: "Still searching: pulling out relevant parts..."
    end
```

---

## The 5 Pipeline Stages

### Stage 1: Fast Planning (`app/services/pipeline/planner.py`)
- **Model**: Fast Model on port `8081` (Qwen3.5-4B or Qwen3.5-2B).
- **Latency**: ~1.5s - 3.5s.
- **Role**: Analyzes the question and conversation history to determine whether external research is required (`needs_search`).
- **Structured Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "needs_search": {"type": "boolean"},
      "queries": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
      "intent": {"type": "string", "enum": ["factual", "news", "opinion", "casual"]},
      "context": {"type": "string"}
    },
    "required": ["needs_search", "queries", "intent"]
  }
  ```
- **Fast-Path Optimization**: Casual greetings, direct memory inquiries, and personal chit-chat bypass search completely and route immediately to the fast lane persona.

### Stage 2: Parallel Fetching (`app/services/pipeline/fetcher.py`)
- **Backend**: SearXNG (`http://127.0.0.1:8080`) + Parallel HTTP extraction.
- **Safety**: SSRF protection filters out loopback (`127.0.0.1`, `localhost`), private LAN (`192.168.*`, `10.*`), and invalid URLs.
- **Extraction Engine**: Zero-browser lightweight extraction using `trafilatura` and `BeautifulSoup`. No heavy headless browsers are spawned, saving over 1 GB of RAM and eliminating out-of-memory kills.

### Stage 3: 3-Tier Evidence Filter (`app/services/pipeline/filter.py`)
To prevent large volumes of noisy HTML text from exceeding the model's context or causing timeouts, text passes through three sequential filters:
1. **Tier 1 (Code - Passage Ranking)**: Splits text into coherent paragraph blocks and scores them against query tokens. Keeps the top 5 passages.
2. **Tier 2 (Fast Model - 2B Quote Extraction)**: The Fast model extracts exact sentences that directly answer the user's question (max 6 quotes).
3. **Tier 3 (Code - Verbatim Verifier)**: A strict string check verifies every extracted quote exists verbatim in the source document. Any hallucinated or altered quote is immediately dropped.

### Stage 4: Factual Synthesis (`app/services/pipeline/synth.py`)
- **Model**: Smart Model on port `8082` (Qwen3.5-9B).
- **Role**: Synthesizes the filtered, verified evidence into a dense, factual explanation with explicit `[1]`, `[2]` numeric citation tags.
- **Strict Grounding**: The system prompt instructs the model to rely solely on the provided evidence blocks and disregard any instructions contained within untrusted web text.

### Stage 5: Persona Rewrite & Formatting (`app/services/pipeline/persona.py`, `telegram_fmt.py`)
- **Model**: Smart Model on port `8082`.
- **Role**: Rewrites the factual draft into Karna's cynical, dry, concise persona without dropping any facts or citations.
- **Formatter**: Converts Markdown markup into Telegram-compliant HTML (`<b>`, `<i>`, `<code>`, `<a href="...">`), converts `[n]` citation tags into numbered hyperlinks, and splits text into sub-4096 character chunks delivered sequentially with a 0.3-second delay.

---

## Non-Blocking Front-Desk Architecture (`app/services/pipeline/jobs.py`)

A critical bottleneck in single-agent architectures is that long-running web searches block subsequent messages. Karna solves this using a non-blocking front-desk queue:
1. **Immediate Acknowledgment**: When a heavy research task is detected, a background job is enqueued via `asyncio.create_task()`, and an acknowledgment is immediately returned to the user.
2. **Interactive Front Desk**: While the background worker runs, the user can continue talking to the bot. Casual chat (`"hi"`, `"what's your name"`), reminders, and status inquiries (`"how long"`, `"status"`, `"done yet?"`) are processed immediately by the fast lane without waiting for the heavy model.
3. **Graceful Job Control**: Sending `"cancel"` or `"stop"` immediately terminates the running research job and frees CPU resources.

---

## Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `USE_PIPELINE` | `false` | Enable multi-stage pipeline routing (set `true` in local `.env`) |
| `LLM_FAST_URL` | `http://127.0.0.1:8081` | OpenAI-compatible endpoint for Fast 2B/4B model |
| `LLM_SMART_URL` | `http://127.0.0.1:8082` | OpenAI-compatible endpoint for Smart 9B model |
| `MAX_PAGES` | `6` | Maximum web pages to gather per query bundle |
| `PAGE_CHARS` | `6000` | Maximum characters processed per evidence bundle |
| `STAGE_TIMEOUT` | `180` | Per-stage timeout in seconds before triggering fallback |
| `PIPELINE_MAX_CONCURRENT_JOBS` | `1` | Maximum parallel background research jobs |

---

## Running the Servers

Start the dual model servers via the included helper script:
```bash
./scripts/start_models.sh
```
This launches:
- Port 8081: Qwen3.5-4B (`-c 4096 -t 4 --parallel 2`)
- Port 8082: Qwen3.5-9B (`-c 4096 -t 4 --parallel 1`)

Combined RAM usage on CPU is approximately 7.8 GB, leaving ample headroom on a 16 GB system.
