import { Model } from "./types";

export const MODELS: Model[] = [
  {
    id: "model-llama",
    name: "llama.cpp (discovered via /v1/models)",
    role: "All LLM calls — planning, conversational, research, extraction fallback",
    contextWindow: 8192,
    temperature: 0.7,
    maxTokens: 512,
    quantization: "Q4_K_M (typical)",
    speedNote: "Local CPU/GPU inference via llama.cpp server",
    usedByLlmCallIds: ["llm-task-planner", "llm-conversational", "llm-research", "llm-entity-extraction-fallback"],
    runtime: "llama.cpp",
  },
];