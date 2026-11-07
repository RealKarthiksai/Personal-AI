declare module "dagre" {
  import { GraphLib } from "graphlib";

  namespace dagre {
    interface Graph<G, V, E> {
      setGraph(value: G): this;
      setNode(id: V, value: E): this;
      setEdge(source: V, target: V, value: E): this;
      node(id: V): E | undefined;
      edges(): { source: V; target: V }[];
    }
    function graphlib(): GraphLib;
    function layout(g: Graph<any, any, any>): void;
  }

  const dagre: dagre.Dagre;
  export = dagre;
}

declare namespace dagre {
  interface Dagre {
    graphlib: any;
    layout: (g: any) => void;
  }
}