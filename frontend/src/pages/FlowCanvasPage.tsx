import { FlowCanvas } from "@/components/canvas/FlowCanvas";
import { NodeInspector } from "@/components/panels/NodeInspector";
import { useUIStore } from "@/store/uiStore";

export function FlowCanvasPage() {
  const { selectedNodeId } = useUIStore();

  return (
    <div className="flex h-full w-full">
      <div className="flex-1 h-full">
        <FlowCanvas />
      </div>
      {selectedNodeId && (
        <div className="w-96 hidden md:block border-l border-dark-border bg-dark-surface h-full">
          <NodeInspector nodeId={selectedNodeId} />
        </div>
      )}
    </div>
  );
}