import { BaseNode } from "./BaseNode";

export function LlmNode({ data, id, selected }: { data: any; id: string; selected?: boolean }) {
  return (
    <BaseNode
      id={id}
      selected={selected ?? false}
      data={{
        ...data,
        nodeType: "llm",
        modelName: data.modelName,
      }}
    />
  );
}