export type {
  NodeType,
  NodeStatus,
  OutputFormat,
  FailureHandling,
  Layer,
  Node,
  Edge,
  Model,
  Variable,
  LLMParameters,
  LLMCall,
  Feature,
  Blueprint,
} from "./types";

export { LAYERS } from "./layers";
export { NODES_PART1 } from "./nodes-part1";
export { NODES_PART2 } from "./nodes-part2";
export { EDGES } from "./edges";
export { MODELS } from "./models";
export { LLM_CALLS_PART1 } from "./llmCalls-part1";
export { LLM_CALLS_PART2 } from "./llmCalls-part2";
export { FEATURES } from "./features";

import { NODES_PART1 } from "./nodes-part1";
import { NODES_PART2 } from "./nodes-part2";
import { LLM_CALLS_PART1 } from "./llmCalls-part1";
import { LLM_CALLS_PART2 } from "./llmCalls-part2";
import { LAYERS } from "./layers";
import { EDGES } from "./edges";
import { MODELS } from "./models";
import { FEATURES } from "./features";
import { Blueprint, Node, LLMCall } from "./types";

export const NODES: Node[] = [...NODES_PART1, ...NODES_PART2];
export const LLM_CALLS: LLMCall[] = [...LLM_CALLS_PART1, ...LLM_CALLS_PART2];

export const SEED_BLUEPRINT: Blueprint = {
  version: 1,
  layers: LAYERS,
  nodes: NODES,
  edges: EDGES,
  models: MODELS,
  llmCalls: LLM_CALLS,
  features: FEATURES,
};