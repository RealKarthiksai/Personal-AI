# Agent Blueprint — Update Guide

This document serves as the single reference for maintaining and updating the Agent Blueprint visualizer when the AI side of the Karna project changes.

## How to Add a New Node
1. Add a Node entry to `src/data/nodes-part1.ts` or `nodes-part2.ts`
2. Add edges in `src/data/edges.ts` connecting the new node
3. Update features in `src/data/features.ts` if needed
4. The visualizer will automatically pick up the changes on refresh

## How to Add a New LLM Call (Prompt)
1. Add an LLMCall entry to `src/data/llmCalls-part1.ts` or `llmCalls-part2.ts`
2. Add the call ID to the node's `llmCallIds` in the nodes data
3. Add the call ID to the model's `usedByLlmCallIds` in `src/data/models.ts`
4. Update features in `src/data/features.ts` if needed

## How to Update an Existing Prompt
1. Edit the `systemPrompt` or `userPromptTemplate` in the corresponding LLMCall entry
2. The Prompt Registry page and canvas inspector will reflect changes automatically

## How to Change a Node Status
1. Update the `status` field in `src/data/nodes-part1.ts` or `nodes-part2.ts`
2. Valid values: `planned`, `building`, `done`

## Build & Verify
Run `npm run build` in `/home/vhanghar/Karna/frontend/` to verify there are no TypeScript errors before committing changes.

## Notes
- All data is sourced from `src/data/` — no backend required
- Edits in the UI are autosaved to `localStorage` under key `agent-blueprint:v1`
- Run `npm run dev` to start the visualizer at `http://localhost:5173`