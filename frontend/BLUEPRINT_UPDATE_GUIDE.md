# Agent Blueprint — Architecture & AI Update Guide

This document is the authoritative reference for AI agents and human developers maintaining, modifying, and updating the Karna Agent Blueprint visualizer whenever changes occur on the AI / backend side of the Karna system.

---

## 1. Architectural Taxonomy & Categorization Rules

When adding, modifying, or documenting components in the Karna AI system, you **MUST** categorize each component into its designated architectural category and layer. Never conflate unrelated concerns (e.g. never combine Memory with UI or lump Networking into generic tools).

### Category 1: Networking & Browser Connectivity (`layer-networking`)
* **Layer ID**: `layer-networking`
* **Node Type**: `"tool"`
* **Color**: `slate`
* **Scope**: All tools, clients, and services that connect the agent to the web, search engines, and browsers:
  - **Live Web Search**: Queries SearXNG metasearch engine with SQLite query caching (`app/services/search_service.py`).
  - **Browser Web Extraction**: Crawl4AI & Playwright headless browser automation with HTTP fallback for extracting markdown from URLs (`app/services/extractor_service.py`).
  - **Recursive Deep Crawler**: Internal link discovery and selective page crawling for directory exploration (`app/services/recursive_crawler.py`).
  - Any future HTTP fetchers, headless browser controllers, or network scrapers.
* **AI Rule**: If a component makes external web requests, controls a browser, or queries search indexes, it belongs in **Networking & Browsers**.

### Category 2: Memory & Persistence (`layer-memory`)
* **Layer ID**: `layer-memory`
* **Node Type**: `"memory"`
* **Color**: `teal`
* **Scope**: All data storage, state management, caching, temporal context, and knowledge retrieval:
  - **SQLite Database**: Persistent relational storage for messages, sessions, search cache, page cache, tool execution logs, and extracted entities (`app/database/database.py`, `models.py`, `repository.py`).
  - **Temporal Context**: Real-time datetime anchoring, timezone resolution, and temporal injection into every system prompt (`app/context/temporal.py`).
  - **Ingestion Pipeline & Knowledge Retrieval**: Document chunking, vector embedding generation, and semantic retrieval (`app/ingestion/`).
* **AI Rule**: If a component manages history, caches state, tracks time, or retrieves stored knowledge, it belongs in **Memory & Persistence**.

### Category 3: Extensions & Integrations (`layer-extensions`)
* **Layer ID**: `layer-extensions`
* **Node Type**: `"extension"`
* **Color**: `cyan`
* **Scope**: Modular external platform connectors, third-party APIs, and automated background schedulers:
  - **GitHub Extension**: Repository inspection, issue queries, PR tracking, and code search (`app/integrations/github/`).
  - **Reddit Extension**: Community querying, subreddit monitoring, and thread extraction (`app/integrations/reddit/`).
  - **OpenAlex Extension**: Scholarly paper retrieval, author search, and citation graph exploration (`app/integrations/openalex/`).
  - **RSS Feeds Extension**: Syndicated feed parsing and periodic news ingestion (`app/integrations/rss/`).
  - **System Monitoring**: Performance metrics, health monitoring, and latency tracking (`app/integrations/monitoring/`).
  - **Job Scheduler**: Periodic background tasks and recurring automation pipelines (`app/scheduler/manager.py`).
* **AI Rule**: If a component interfaces with an external platform/API or runs periodic scheduled jobs, it belongs in **Extensions & Integrations**.

### Category 4: User Channels & I/O (`layer-user`)
* **Layer ID**: `layer-user`
* **Node Type**: `"input"` (inbound gateways) or `"output"` (outbound delivery / formatters)
* **Color**: `blue`
* **Scope**: Inbound and outbound messaging channels, user gateways, and cross-platform formatting:
  - **Telegram Bot**: Long-polling gateway receiving user messages and commands (`app/telegram_bot.py`).
  - **Telegram Client**: Outbound message dispatcher with chunking and retries (`app/services/telegram_client.py`).
  - **Formatting Engine**: Markdown AST parser and multi-platform renderers for Telegram HTML, WhatsApp text, and Web HTML (`app/formatting/engine.py`).
* **AI Rule**: If a component interacts directly with the user or formats messages for external channels, it belongs in **User Channels**.

### Category 5: Core Orchestration (`layer-orchestration`)
* **Layer ID**: `layer-orchestration`
* **Node Type**: `"orchestrator"`
* **Color**: `green`
* **Scope**: The central message coordination and routing pipeline:
  - **Chat Service**: End-to-end orchestration pipeline (authorization, deduplication, history loading, tool dispatch, LLM inference, delivery) (`app/services/chat_service.py`).
  - **Tool Router**: Regex and intent classification routing incoming queries to the appropriate tools and extensions (`app/services/tool_router.py`).
  - **Security & Authorization**: API security, caller verification, and rate limits (`app/security/authorization.py`).

### Category 6: Processing & Reasoning (`layer-processing`)
* **Layer ID**: `layer-processing`
* **Node Type**: `"processing"`
* **Color**: `purple`
* **Scope**: Analytical, transformation, planning, and verification logic:
  - **Planner Service**: LLM-driven query and task planning (`app/services/planner_service.py`).
  - **Query Normalizer**: Location normalization, relative date resolution, query expansion (`app/services/query_normalizer.py`).
  - **Structured Extractor**: Extraction of entities and events from raw text (`app/services/structured_extractor.py`).
  - **Source Verifier**: Authority hierarchy scoring, conflict detection, freshness validation (`app/services/source_verifier.py`).

### Category 7: Local LLM Engine (`layer-llm`)
* **Layer ID**: `layer-llm`
* **Node Type**: `"llm"`
* **Color**: `amber`
* **Scope**: Local LLM execution and inference management:
  - **Local LLM Client**: Async client interfacing with llama.cpp OpenAI-compatible server (`app/services/llm_client.py`).
  - **Models**: Local quantized models configured in `src/data/models.ts`.
  - **Prompt Registry**: System prompts and user templates in `src/data/llmCalls-part1.ts` and `llmCalls-part2.ts`.

---

## 2. Step-by-Step Guide for AI to Make Changes

When modifying the blueprint data, follow this strict procedure:

### A. How to Add a New Node
1. Determine the appropriate category from Section 1 above.
2. Choose either `src/data/nodes-part1.ts` or `src/data/nodes-part2.ts`.
3. Create the node entry following the `Node` interface:
   ```typescript
   {
     id: "node-<component-name>",
     label: "Component Label",
     layerId: "layer-<category>", // e.g. layer-networking, layer-memory, layer-extensions
     type: "tool" | "memory" | "extension" | "orchestrator" | "processing" | "llm" | "input" | "output",
     description: "Clear summary of purpose and operation.",
     tech: ["tech1", "tech2"],
     features: ["associated-feature-id"],
     status: "done", // "planned" | "building" | "done"
     sourceFile: "app/path/to/source.py",
     llmCallIds: ["llm-call-id"], // optional, if this node directly triggers LLM calls
   }
   ```
4. Connect the node in `src/data/edges.ts`:
   ```typescript
   {
     id: "edge-<source>-to-<target>",
     source: "node-<source>",
     target: "node-<target>",
     label: "data_payload",
     condition: "trigger condition",
     animated: true,
   }
   ```
5. If the node introduces new capabilities, add a corresponding feature entry in `src/data/features.ts`.

### B. How to Add a New LLM Call (Prompt)
1. Add an `LLMCall` entry to `src/data/llmCalls-part1.ts` or `llmCalls-part2.ts`.
2. Ensure `nodeId` references the triggering node.
3. Add the `id` to the node's `llmCallIds` array in `nodes-part1.ts` / `nodes-part2.ts`.
4. Add the `id` to the model's `usedByLlmCallIds` array in `src/data/models.ts`.
5. Update features in `src/data/features.ts` if relevant.

### C. How to Update an Existing Prompt
1. Locate the call ID in `src/data/llmCalls-part1.ts` or `llmCalls-part2.ts`.
2. Edit `systemPrompt` or `userPromptTemplate`.
3. Changes immediately reflect in the Prompt Registry and Node Inspector.

### D. How to Change Node Status
1. Modify `status` in the node definition:
   - `"planned"`: Roadmap / proposed feature.
   - `"building"`: Currently under active implementation.
   - `"done"`: Implemented, tested, and operational in `app/`.

---

## 3. Flow Canvas Styling Rules

- **Dark Mode**: The canvas uses `@xyflow/react` with `colorMode="dark"`.
- **Node Wrapper Styling**: Default React Flow wrapper classes (`.react-flow__node-input`, `.react-flow__node-output`, `.react-flow__node-default`, `.react-flow__node-group`) are stripped of default white backgrounds, padding, and borders in `src/index.css`. Custom node cards provide their own borders and glowing dark backgrounds.
- **Node Type Visuals**:
  - `input`: Blue border & subtle fill
  - `orchestrator`: Green border & subtle fill
  - `processing`: Purple border & subtle fill
  - `tool`: Slate border & subtle fill
  - `memory`: Teal border & subtle fill
  - `extension`: Cyan border & subtle fill
  - `llm`: Amber border, glowing ring, and shadow
  - `output`: Slate border & subtle fill

---

## 4. Build & Verification Protocol

After making any changes to data or components:
1. Verify TypeScript types and Vite production bundle:
   ```bash
   cd /home/vhanghar/Karna/frontend
   npm run build
   ```
2. Run backend tests to verify system integrity:
   ```bash
   pytest
   ```
3. Verify that changes appear accurately on the canvas at `http://localhost:5173`.