import { useBlueprintStore } from "@/store/blueprintStore";
import { useUIStore } from "@/store/uiStore";
import { LLMCall } from "@/data/index";
import { Badge } from "@/components/ui/Badge";
import { StatusDot } from "@/components/ui/StatusDot";
import { CopyButton } from "@/components/ui/CopyButton";

interface NodeInspectorProps {
  nodeId: string | null;
}

export function NodeInspector({ nodeId }: NodeInspectorProps) {
  const { blueprint } = useBlueprintStore();
  const { setSelectedNode } = useUIStore();

  if (!nodeId) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-slate-500">
        <p>Select a node to inspect</p>
      </div>
    );
  }

  const node = blueprint.nodes.find((n) => n.id === nodeId);
  if (!node) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-slate-500">
        <p>Node not found</p>
      </div>
    );
  }

  const llmCalls = (node.llmCallIds || []).map(
    (id) => blueprint.llmCalls.find((c) => c.id === id)
  ).filter(Boolean) as LLMCall[];

  // model and tabs removed (unused)

  return (
    <div className="h-full flex flex-col border-l border-dark-border bg-dark-surface overflow-hidden">
      <div className="px-4 py-3 border-b border-dark-border">
        <div className="flex items-center gap-2 mb-2">
          <StatusDot status={node.status} />
          <span className="text-sm font-medium text-white truncate">
            {node.label}
          </span>
          <button
            onClick={() => setSelectedNode(null)}
            className="ml-auto text-slate-500 hover:text-white transition-colors"
            title="Close"
          >
            ✕
          </button>
        </div>
        <p className="text-xs text-slate-400">
          {node.sourceFile ? `Source: ${node.sourceFile}` : ""}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Overview tab */}
        <div className="space-y-4">
          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Description
          </h3>
          <p className="text-sm text-slate-300">{node.description}</p>

          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4">
            Type & Layer
          </h3>
          <div className="flex items-center gap-2 text-xs">
            <Badge variant="outline" className="text-[10px]">
              {node.type}
            </Badge>
            <span className="text-slate-500">•</span>
            <span className="text-slate-300">
              {blueprint.layers.find((l) => l.id === node.layerId)?.name}
            </span>
          </div>

          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4">
            Tech Stack
          </h3>
          <div className="flex flex-wrap gap-2">
            {node.tech.map((t) => (
              <Badge key={t} variant="outline" className="text-[10px]">
                {t}
              </Badge>
            ))}
          </div>

          <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4">
            Features
          </h3>
          <div className="flex flex-wrap gap-2">
            {node.features.map((f) => (
              <Badge key={f} variant="outline" className="text-[10px]">
                {f}
              </Badge>
            ))}
          </div>

          {llmCalls.length > 0 && (
            <>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mt-4">
                LLM Calls ({llmCalls.length})
              </h3>
              <div className="space-y-2">
                {llmCalls.map((call) => (
                  <div
                    key={call.id}
                    className="flex items-center justify-between px-3 py-2 rounded bg-slate-800/30 border border-slate-700/50"
                  >
                    <span className="text-sm text-amber-300 font-mono">
                      {call.name}
                    </span>
                    <CopyButton text={call.systemPrompt} size="sm" />
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

