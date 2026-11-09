import { Layer } from "./types";

export const LAYERS: Layer[] = [
  {
    id: "layer-user",
    name: "User Channels",
    color: "blue",
    description: "Inbound and outbound messaging channels, gateways, and cross-platform formatting.",
  },
  {
    id: "layer-orchestration",
    name: "Orchestration",
    color: "green",
    description: "ChatService pipeline: authorization, deduplication, history, LLM generation, delivery.",
  },
  {
    id: "layer-processing",
    name: "Processing",
    color: "purple",
    description: "Task planning, query normalization, structured extraction, source verification.",
  },
  {
    id: "layer-networking",
    name: "Networking & Browsers",
    color: "slate",
    description: "Web search (SearXNG), browser extraction (Crawl4AI/Playwright), and recursive crawling.",
  },
  {
    id: "layer-memory",
    name: "Memory & Persistence",
    color: "teal",
    description: "SQLite persistence (messages, search/page cache, tool logs), temporal context, and ingestion retrieval.",
  },
  {
    id: "layer-extensions",
    name: "Extensions & Integrations",
    color: "cyan",
    description: "External platform connectors (GitHub, Reddit, OpenAlex, RSS), monitoring, and job scheduling.",
  },
  {
    id: "layer-llm",
    name: "Local LLM",
    color: "amber",
    description: "llama.cpp OpenAI-compatible API — all LLM calls executed locally.",
  },
  {
    id: "layer-agents",
    name: "Agent Delegation",
    color: "orange",
    description: "Local coding and ops agent execution (Cline CLI & Antigravity CLI) with git safety net and process supervision.",
  },
];