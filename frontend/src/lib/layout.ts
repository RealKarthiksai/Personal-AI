import dagre from "dagre";
import { Node, Edge } from "@xyflow/react";

const nodeWidth = 240;
const nodeHeight = 120;

export function runLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB"
): Node[] {
  const g = new (dagre as any).graphlib.Graph().setGraph({
    rankdir: direction,
    align: "UL",
    ranksep: direction === "TB" ? 80 : 160,
    nodesep: 50,
    edgesep: 30,
  });

  nodes.forEach((n) => {
    g.setNode(n.id, { width: nodeWidth, height: nodeHeight });
  });

  edges.forEach((e) => {
    g.setEdge(e.source, e.target, { minlen: 1 });
  });

  (dagre as any).layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    return {
      ...n,
      position: { x: pos.x - nodeWidth / 2, y: pos.y - nodeHeight / 2 },
    };
  });
}