import { Menu, Search, Settings } from "lucide-react";
import { useUIStore } from "@/store/uiStore";
import { Button } from "@/components/ui/Button";

interface TopBarProps {
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
}

export function TopBar({ isSidebarOpen, setIsSidebarOpen }: TopBarProps) {
  const { searchQuery, setSearchQuery, activeFilter, filterValue, setFilter } =
    useUIStore();

  const handleFilter = (type: string) => {
    if (activeFilter === type && filterValue !== null) {
      setFilter(null, null);
    } else {
      setFilter(type as any, "filter-" + type);
    }
  };

  return (
    <header className="sticky top-0 z-20 bg-dark-bg/80 backdrop-blur border-b border-dark-border px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <button
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          className="md:hidden text-slate-400 hover:text-white"
        >
          <Menu className="w-6 h-6" />
        </button>
        <div className="hidden md:flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs text-green-400 font-medium">
            System operational
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <div className="relative hidden md:block">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search nodes, prompts, models (Ctrl+K)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-full bg-dark-surfaceLift border border-dark-border text-sm text-white focus:outline-none focus:border-amber-500 w-64"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleFilter("layer")}
          className="text-xs"
        >
          Filter: Layer
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleFilter("status")}
          className="text-xs"
        >
          Filter: Status
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleFilter("feature")}
          className="text-xs"
        >
          Filter: Feature
        </Button>
        <Button variant="ghost" size="sm" className="text-xs">
          <Settings className="w-4 h-4" />
        </Button>
      </div>
    </header>
  );
}