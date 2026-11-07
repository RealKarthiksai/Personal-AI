import { useBlueprintStore } from "@/store/blueprintStore";
import { Badge } from "@/components/ui/Badge";

export function FeaturesPage() {
  const { blueprint } = useBlueprintStore();

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Features</h1>
        <p className="text-slate-400">
          System capabilities mapped to the nodes and prompts that implement them.
        </p>
      </div>

      <div className="space-y-4">
        {blueprint.features.map((feature) => {
          const nodes = blueprint.nodes.filter((n) => feature.nodeIds.includes(n.id));
          const calls = blueprint.llmCalls.filter((c) =>
            feature.llmCallIds.includes(c.id)
          );
          return (
            <div
              key={feature.id}
              className="rounded-card border border-dark-border bg-dark-surface p-5"
            >
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-lg font-bold text-white">{feature.name}</h2>
                  <p className="text-sm text-slate-400">{feature.description}</p>
                </div>
                <Badge
                  variant={feature.status === "done" ? "default" : "outline"}
                  className="text-xs"
                >
                  {feature.status}
                </Badge>
              </div>

              <div className="flex items-center gap-2 mb-4">
                <span className="text-[10px] font-semibold text-slate-500 uppercase">
                  Nodes ({nodes.length})
                </span>
                {nodes.map((n) => (
                  <span
                    key={n.id}
                    className="px-2 py-1 rounded bg-slate-800/50 border border-slate-700/50 text-[10px] text-slate-300"
                  >
                    {n.label}
                  </span>
                ))}
              </div>

              {calls.length > 0 && (
                <div>
                  <span className="text-[10px] font-semibold text-slate-500 uppercase block mb-2">
                    LLM Calls ({calls.length})
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {calls.map((c) => (
                      <span
                        key={c.id}
                        className="px-2 py-1 rounded bg-amber-900/30 border border-amber-900/50 text-[10px] text-amber-300"
                      >
                        {c.name}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}