/**
 * Agent Blueprint — TypeScript types.
 * All data extracted from the actual Karna codebase (Python/FastAPI).
 */

export type NodeType =
  | "input"
  | "orchestrator"
  | "tool"
  | "processing"
  | "llm"
  | "memory"
  | "extension"
  | "output";

export type NodeStatus = "planned" | "building" | "done";
export type OutputFormat = "json" | "text" | "tool_call";
export type FailureHandling = "retry" | "fallback" | "validation";

export interface Layer {
  id: string;
  name: string;
  color: "blue" | "green" | "slate" | "purple" | "amber" | "teal" | "cyan" | "rose" | "orange";
  description: string;
}

export interface Node {
  id: string;
  label: string;
  layerId: string;
  type: NodeType;
  description: string;
  tech: string[];
  features: string[];
  status: NodeStatus;
  llmCallIds?: string[];
  sourceFile?: string;
}

export interface Edge {
  id: string;
  source: string;
  target: string;
  label?: string;
  condition?: string;
  animated: boolean;
}

export interface Model {
  id: string;
  name: string;
  role: string;
  contextWindow: number;
  temperature: number;
  maxTokens: number;
  quantization: string;
  speedNote: string;
  usedByLlmCallIds: string[];
  runtime: "ollama" | "llama.cpp" | "lmstudio";
}

export interface Variable {
  name: string;
  type: string;
  source: string;
  example: string;
}

export interface LLMParameters {
  temperature: number;
  top_p: number;
  max_tokens: number;
  stop: string[];
}

export interface LLMCall {
  id: string;
  name: string;
  nodeId: string;
  modelId: string;
  purpose: string;
  systemPrompt: string;
  userPromptTemplate: string;
  variables: Variable[];
  inputExample: string;
  expectedOutputSchema: string;
  outputExample: string;
  parameters: LLMParameters;
  outputFormat: OutputFormat;
  avgTokensIn: number;
  avgTokensOut: number;
  failureHandling: FailureHandling;
  triggeredWhen: string;
}

export interface Feature {
  id: string;
  name: string;
  description: string;
  nodeIds: string[];
  llmCallIds: string[];
  status: NodeStatus;
}

export interface Blueprint {
  version: number;
  layers: Layer[];
  nodes: Node[];
  edges: Edge[];
  models: Model[];
  llmCalls: LLMCall[];
  features: Feature[];
}