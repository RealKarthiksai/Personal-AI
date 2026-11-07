import { Node, Edge } from "@xyflow/react";
import { Blueprint } from "@/data/index";

/**
 * Export the current flow as a Mermaid flowchart diagram.
 */
export function toMermaid(nodes: Node[], edges: Edge[], layers: Blueprint["layers"]): string {
  const lines: string[] = ["flowchart TD"];

  const layerMap: Record<string, string> = {};
  layers.forEach((l) => {
    layerMap[l.id] = l.name;
    lines.push(`    subgraph ${l.id.replace(/-/g, "_")} [${l.name}]`);
  });

  nodes.forEach((n) => {
    const safeId = n.id.replace(/-/g, "_");
    const safeLabel = String(n.data?.label || "").replace(/"/g, '\\"');
    lines.push(`    ${safeId}("${safeLabel}")`);
  });

  layers.forEach(() => {
    lines.push(`    end`);
  });

  edges.forEach((e) => {
    const s = e.source.replace(/-/g, "_");
    const t = e.target.replace(/-/g, "_");
    const lbl = e.label ? ` |"${e.label}"| ` : " --> ";
    lines.push(`    ${s} ${lbl} ${t}`);
  });

  return lines.join("\n");
}