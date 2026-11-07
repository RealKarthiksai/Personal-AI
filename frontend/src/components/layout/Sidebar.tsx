import { useNavigate } from "react-router-dom";
import { X, Home, List, BarChart3, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUIStore } from "@/store/uiStore";
import { useBlueprintStore } from "@/store/blueprintStore";
import { LAYERS } from "@/data/index";

interface SidebarProps {
  isOpen: boolean;
}

export function Sidebar({ isOpen }: SidebarProps) {
  const navigate = useNavigate();
  const { setCurrentView } = useUIStore();
  const { blueprint } = useBlueprintStore();

  const navItems = [
    { id: "canvas", label: "Flow Canvas", icon: Home, view: "canvas" },
    { id: "prompts", label: "Prompt Registry", icon: List, view: "prompts" },
    { id: "models", label: "Models", icon: BarChart3, view: "models" },
    { id: "features", label: "Features", icon: Layers, view: "features" },
  ];

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-30 w-64 bg-dark-surface border-r border-dark-border flex flex-col transition-transform duration-300 ease-in-out",
        isOpen ? "translate-x-0" : "-translate-x-full",
        "md:relative md:translate-x-0 md:flex-shrink-0"
      )}
    >
      <div className="flex items-center justify-between px-6 py-4 border-b border-dark-border">
        <h1 className="text-lg font-bold text-white tracking-tight">
          Agent Blueprint
        </h1>
        <button
          onClick={() => {}}
          className="md:hidden text-slate-400 hover:text-white"
        >
          <X className="w-6 h-6" />
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-4 space-y-2">
        {navItems.map((item) => {
          const ViewIcon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => {
                setCurrentView(item.view as any);
                navigate(`/${item.id}`);
              }}
              className={cn(
                "flex items-center gap-3 px-4 py-3 rounded-card text-sm font-medium transition-colors",
                "text-slate-400 hover:text-white hover:bg-dark-surfaceLift"
              )}
            >
              <ViewIcon className="w-5 h-5" />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="p-4 border-t border-dark-border">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Layers ({LAYERS.length})
        </h3>
        <div className="space-y-2">
          {LAYERS.map((layer) => (
            <div
              key={layer.id}
              className="flex items-center gap-3 px-3 py-2 rounded bg-slate-800/30 border border-slate-700/50 text-xs"
            >
              <span
                className={cn(
                  "w-2 h-2 rounded-full",
                  {
                    blue: "bg-blue-500",
                    green: "bg-green-500",
                    slate: "bg-slate-500",
                    purple: "bg-purple-500",
                    amber: "bg-amber-500",
                    teal: "bg-teal-500",
                  }[layer.color]
                )}
              ></span>
              <span className="text-slate-300">{layer.name}</span>
              <span className="ml-auto text-[10px] text-slate-500">
                {blueprint.nodes.filter((n) => n.layerId === layer.id).length}
              </span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}