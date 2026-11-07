# Agent Blueprint — Karna Local AI Visualizer

Interactive node-based visualizer for the Karna local AI agent system.

## Tech Stack

- React 18 + Vite + TypeScript
- @xyflow/react (React Flow) for the canvas
- Tailwind CSS for styling
- Zustand for state management
- dagre for automatic layout
- lucide-react for icons

## Quick Start

```bash
cd /home/vhanghar/Karna/frontend
npm install
npm run dev
```

Then open http://localhost:5173 in your browser.

## Build

```bash
npm run build
```

## Editing the Blueprint

All data lives in `src/data/`. To add a new node or prompt:

1. **Add a node**: Add an entry to `src/data/nodes-part1.ts` or `nodes-part2.ts`
2. **Add an edge**: Add an entry to `src/data/edges.ts`
3. **Add a prompt**: Add an entry to `src/data/llmCalls-part1.ts` or `llmCalls-part2.ts`
4. **Add a feature**: Add an entry to `src/data/features.ts`
5. **Add a model**: Add an entry to `src/data/models.ts`

The data is automatically picked up by the visualizer. Edits in the UI are persisted to localStorage.

## Reset to Seed

Click "Reset to Seed" on the canvas, or clear localStorage:
```js
localStorage.removeItem("agent-blueprint:v1");
```

## Export

- **JSON**: Use the export button (or localStorage copy)
- **Mermaid**: Use the `toMermaid()` function from `src/lib/export.ts`
- **PNG**: Use the `exportPNG()` function from `src/lib/export.ts`