import { Handle, Position } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { StatusDot } from "@/components/ui/StatusDot";
import { Badge } from "@/components/ui/Badge";
import { Node as BPNode } from "@/data/index";

interface BaseNodeProps {
  data: {
    label: string;
    description: string;
    tech: string[];
    features: string[];
    status: BPNode["status"];
    llmCallCount?: number;
    modelName?: string;
    layerColor?: string;
    nodeType: BPNode["type"];
  };
  id: string;
  selected: boolean;
}

const typeColors: Record<string, string> = {
  input: "border-blue-500 bg-blue-500/10",
  orchestrator: "border-green-500 bg-green-500/10",
  tool: "border-slate-500 bg-slate-500/10",
  processing: "border-purple-500 bg-purple-500/10",
  llm: "border-amber-500 bg-amber-500/10 ring-1 ring-amber-500/30 shadow-[0_0_15px_rgba(245,158,11,0.2)]",
  memory: "border-teal-500 bg-teal-500/10",
  output: "border-slate-500 bg-slate-500/10",
};

export function BaseNode({ data, selected }: BaseNodeProps) {
  const borderClass = cn(
    "rounded-card border p-4 min-w-[220px] shadow-lg transition-all duration-200",
    typeColors[data.nodeType],
    selected && "ring-2 ring-white"
  );

  return (
    <div className={borderClass}>
      {/* Top bar: label + status dot */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm text-white truncate max-w-[160px]">
            {data.label}
          </span>
          <StatusDot status={data.status} className="ml-1" />
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-slate-400 mb-3 line-clamp-2">
        {data.description}
      </p>

      {/* Tech badges */}
      <div className="flex flex-wrap gap-1 mb-3">
        {data.tech.map((t) => (
          <Badge key={t} variant="outline" className="text-[10px] border-slate-600 text-slate-400 hover:border-slate-400 hover:text-white">
            {t}
          </Badge>
        ))}
      </div>

      {/* Bottom divider */}
      <div className="h-px bg-slate-800/50 my-3" />

      {/* Bottom row: LLM calls chip + model name */}
      <div className="flex items-center justify-between text-[10px]">
        {data.llmCallCount !== undefined && data.llmCallCount > 0 && (
          <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-900/30 text-amber-300 border border-amber-900/50">
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
              <path d="M2 10a5 5 0 015-5h8a5 5 0 015 5v5a1 1 0 01-1 1H3a1 1 0 01-1-1z" />
            </svg>
            {data.llmCallCount} LLM call{data.llmCallCount > 1 ? "s" : ""}
          </span>
        )}
        {data.modelName && (
          <span className="text-slate-500 italic">{data.modelName}</span>
        )}
      </div>

      {/* React Flow handles */}
      <Handle type="source" position={Position.Right} id="source" className="stroke-slate-500" />
      <Handle type="target" position={Position.Left} id="target" className="stroke-slate-500" />
    </div>
  );
}