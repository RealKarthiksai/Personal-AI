import React from "react";
import { Layer } from "@/data/index";
import { cn } from "@/lib/utils";

interface LayerGroupProps {
  layer: Layer;
  children: React.ReactNode;
}

export function LayerGroup({ layer, children }: LayerGroupProps) {
  const colorMap: Record<string, string> = {
    blue: "border-blue-500/30 bg-blue-500/5",
    green: "border-green-500/30 bg-green-500/5",
    slate: "border-slate-500/30 bg-slate-500/5",
    purple: "border-purple-500/30 bg-purple-500/5",
    amber: "border-amber-500/30 bg-amber-500/5",
    teal: "border-teal-500/30 bg-teal-500/5",
  };

  return (
    <div
      className={cn(
        "rounded-xl border p-4 mb-6 relative",
        colorMap[layer.color],
        "border-dashed"
      )}
    >
      <div className="absolute -top-3 left-4 px-2 py-0.5 rounded-full bg-slate-900 border border-slate-700 text-[10px] font-semibold text-white">
        {layer.name.toUpperCase()}
      </div>
      <div className="text-[10px] text-slate-500 mb-2 mt-2">{layer.description}</div>
      {children}
    </div>
  );
}