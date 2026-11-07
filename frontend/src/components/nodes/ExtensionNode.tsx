import { BaseNode } from "./BaseNode";

export function ExtensionNode({ data, id, selected }: { data: any; id: string; selected?: boolean }) {
  return (
    <BaseNode
      id={id}
      selected={selected ?? false}
      data={{
        ...data,
        nodeType: "extension",
        modelName: undefined,
      }}
    />
  );
}
