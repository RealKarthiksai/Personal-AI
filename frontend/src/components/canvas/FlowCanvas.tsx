import { useCallback } from "react";
import { ReactFlow, Controls, MiniMap, Background, useNodesState, useEdgesState, addEdge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { InputNode, OrchestratorNode, ToolNode, ProcessingNode, LlmNode, MemoryNode, OutputNode } from "@/components/nodes";
import { useBlueprintStore } from "@/store/blueprintStore";
import { useUIStore } from "@/store/uiStore";
import { runLayout } from "@/lib/layout";
import { Button } from "@/components/ui/Button";

const nodeTypes: Record<string, React.ComponentType<any>> = { input: InputNode, orchestrator: OrchestratorNode, tool: ToolNode, processing: ProcessingNode, llm: LlmNode, memory: MemoryNode, output: OutputNode };

export function FlowCanvas() {
  const { blueprint, resetToSeed } = useBlueprintStore();
  const { setSelectedNode, setSelectedEdge, layoutDirection, setLayoutDirection, showPromptsOnCanvas, setShowPromptsOnCanvas } = useUIStore();

  const [nodes, setNodes, onNodesChange] = useNodesState(blueprint.nodes.map((n: any) => ({ id: n.id, type: n.type, position: { x: 0, y: 0 }, data: { label: n.label, description: n.description, tech: n.tech, features: n.features, status: n.status, llmCallCount: n.llmCallIds?.length || 0, modelName: undefined } })));
  const [edges, setEdges, onEdgesChange] = useEdgesState(blueprint.edges.map((e: any) => ({ id: e.id, source: e.source, target: e.target, label: e.label, animated: e.animated })));

  const handleConnect = useCallback((params: any) => { setEdges((eds: any) => addEdge({ ...params, animated: true }, eds)); }, [setEdges]);
  const handleEdgeClick = useCallback((e: any, edge: any) => { e.stopPropagation(); setSelectedEdge(edge.id); setSelectedNode(null); }, [setSelectedEdge, setSelectedNode]);
  const handleNodeClick = useCallback((e: any, node: any) => { e.stopPropagation(); setSelectedNode(node.id); setSelectedEdge(null); }, [setSelectedNode, setSelectedEdge]);
  const handleOnInit = useCallback((instance: any) => {
    instance.fitView();
    const positioned = runLayout(nodes as any, edges as any, layoutDirection);
    setNodes(positioned as any);
    setTimeout(() => instance.fitView(), 100);
  }, [nodes, edges, layoutDirection, setNodes]);
  const onLayout = useCallback(() => { const positioned = runLayout(nodes as any, edges as any, layoutDirection); setNodes(positioned as any); }, [nodes, edges, layoutDirection, setNodes]);

  return (
    <div className="flex h-full relative">
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 flex gap-2">
        <Button variant="outline" size="sm" onClick={onLayout} className="bg-slate-800/80 border-slate-600 text-xs hover:bg-slate-700">Auto-layout</Button>
        <Button variant="outline" size="sm" onClick={() => setLayoutDirection(layoutDirection === "TB" ? "LR" : "TB")} className="bg-slate-800/80 border-slate-600 text-xs hover:bg-slate-700">Toggle Direction</Button>
        <Button variant="outline" size="sm" onClick={() => resetToSeed()} className="bg-slate-800/80 border-slate-600 text-xs hover:bg-slate-700">Reset to Seed</Button>
        <label className="flex items-center gap-1 text-[10px] text-slate-400 cursor-pointer select-none hover:text-white transition-colors">
          <input type="checkbox" checked={showPromptsOnCanvas} onChange={(e) => setShowPromptsOnCanvas(e.target.checked)} className="accent-amber-500" />
          Show prompts on canvas
        </label>
      </div>
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={handleConnect} onInit={handleOnInit} onNodeClick={handleNodeClick} onEdgeClick={handleEdgeClick} onPaneClick={() => { setSelectedNode(null); setSelectedEdge(null); }} nodeTypes={nodeTypes} panOnScroll minZoom={0.3} maxZoom={2} fitView style={{ height: "100%", width: "100%" }}>
        <Controls position="top-right" />
        <MiniMap position="bottom-right" nodeBorderRadius={2} />
        <Background gap={16} color="#141417" />
      </ReactFlow>
    </div>
  );
}