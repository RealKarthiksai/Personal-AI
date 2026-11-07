import { useBlueprintStore } from "@/store/blueprintStore";
import { Badge } from "@/components/ui/Badge";

export function PromptRegistryPage() {
  const { blueprint } = useBlueprintStore();

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">Prompt Registry</h1>
        <p className="text-slate-400">
          All LLM calls in the system with their full system prompts, user
          templates, variables, and example I/O.
        </p>
      </div>

      <div className="overflow-x-auto border border-dark-border rounded-card bg-dark-surface">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-dark-border bg-dark-surfaceLift/50">
              <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">
                Name
              </th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">
                Node
              </th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">
                Format
              </th>
              <th className="px-4 py-3 text-xs font-semibold text-slate-400 uppercase">
                Tokens In/Out
              </th>
            </tr>
          </thead>
          <tbody>
            {blueprint.llmCalls.map((call) => {
              const node = blueprint.nodes.find((n) => n.id === call.nodeId);
              return (
                <tr
                  key={call.id}
                  className="border-b border-dark-border/50 hover:bg-slate-800/30 transition-colors cursor-pointer group"
                >
                  <td className="px-4 py-3">
                    <div className="text-sm text-white font-mono">{call.name}</div>
                    <div className="text-xs text-slate-500">{call.purpose}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-slate-300">
                      {node?.label || "Unknown"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className="text-[10px]">
                      {call.outputFormat}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {call.avgTokensIn} / {call.avgTokensOut}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-8 border border-dark-border rounded-card bg-dark-surface p-6">
        <h2 className="text-xl font-bold text-white mb-4">Prompt Detail</h2>
        <p className="text-slate-400 text-sm mb-4">
          Click a row above to view the full prompt details with copy buttons.
        </p>
      </div>
    </div>
  );
}