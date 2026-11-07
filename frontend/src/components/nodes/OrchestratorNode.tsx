import { BaseNode } from "./BaseNode";

export function OrchestratorNode({ data, id, selected }: { data: any; id: string; selected?: boolean }) {
  return (
    <BaseNode
      id={id}
      selected={selected ?? false}
      data={{
        ...data,
        nodeType: "orchestrator",
        modelName: undefined,
      }}
    />
  );
}