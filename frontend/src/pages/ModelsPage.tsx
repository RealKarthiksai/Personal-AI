import { useBlueprintStore } from "@/store/blueprintStore";
import { Badge } from "@/components/ui/Badge";

export function ModelsPage() {
  const { blueprint } = useBlueprintStore();

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Models</h1>
        <p className="text-slate-400">
          LLM models used by the system and which prompts they handle.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {blueprint.models.map((model) => (
          <div
            key={model.id}
            className="rounded-card border border-dark-border bg-dark-surface p-6"
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-bold text-white">{model.name}</h2>
                <p className="text-sm text-slate-400">{model.role}</p>
              </div>
              <Badge variant="outline" className="text-[10px]">
                {model.runtime}
              </Badge>
            </div>

            <div className="space-y-4 mb-6">
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Context Window</span>
                <span className="text-white">{model.contextWindow.toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Temperature</span>
                <span className="text-white">{model.temperature}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Max Tokens</span>
                <span className="text-white">{model.maxTokens}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Quantization</span>
                <span className="text-white">{model.quantization}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-slate-400">Speed Note</span>
                <span className="text-white text-xs">{model.speedNote}</span>
              </div>
            </div>

            <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              LLM Calls ({model.usedByLlmCallIds.length})
            </h3>
            <div className="space-y-2">
              {model.usedByLlmCallIds.map((callId) => {
                const call = blueprint.llmCalls.find((c) => c.id === callId);
                if (!call) return null;
                return (
                  <div key={callId} className="flex items-center justify-between text-sm py-1.5 border-b border-dark-border/30 last:border-0">
                    <span className="text-slate-300 font-mono">{call.name}</span>
                    <span className="text-xs text-slate-500">{call.outputFormat}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}