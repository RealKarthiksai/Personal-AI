import { Edge } from "@xyflow/react";
import { cn } from "@/lib/utils";

interface EdgeLabelProps {
  edge: Edge;
  selected: boolean;
}

export function EdgeLabel({ edge, selected }: EdgeLabelProps) {
  const label = edge.label || "";
  if (!label) return null;

  return (
    <div
      className={cn(
        "px-2 py-1 rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300 whitespace-nowrap shadow-md",
        selected && "border-amber-500 text-amber-200"
      )}
    >
      {label}
    </div>
  );
}