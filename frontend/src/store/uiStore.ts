import { create } from "zustand";

export type FilterType = "layer" | "model" | "status" | "feature";

interface UIState {
  // Selection
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  setSelectedNode: (id: string | null) => void;
  setSelectedEdge: (id: string | null) => void;
  clearSelection: () => void;

  // Filters
  activeFilter: FilterType | null;
  filterValue: string | null;
  setFilter: (type: FilterType | null, value: string | null) => void;
  clearFilters: () => void;

  // Layout
  layoutDirection: "TB" | "LR";
  setLayoutDirection: (dir: "TB" | "LR") => void;

  // Canvas options
  showPromptsOnCanvas: boolean;
  setShowPromptsOnCanvas: (v: boolean) => void;

  // Search
  searchQuery: string;
  setSearchQuery: (q: string) => void;

  // View mode
  currentView: "canvas" | "prompts" | "models" | "features";
  setCurrentView: (v: "canvas" | "prompts" | "models" | "features") => void;
}

export const useUIStore = create<UIState>((set) => ({
  // Selection
  selectedNodeId: null,
  selectedEdgeId: null,
  setSelectedNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  setSelectedEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),
  clearSelection: () => set({ selectedNodeId: null, selectedEdgeId: null }),

  // Filters
  activeFilter: null,
  filterValue: null,
  setFilter: (type, value) => set({ activeFilter: type, filterValue: value }),
  clearFilters: () => set({ activeFilter: null, filterValue: null }),

  // Layout
  layoutDirection: "TB",
  setLayoutDirection: (dir) => set({ layoutDirection: dir }),

  // Canvas options
  showPromptsOnCanvas: false,
  setShowPromptsOnCanvas: (v) => set({ showPromptsOnCanvas: v }),

  // Search
  searchQuery: "",
  setSearchQuery: (q) => set({ searchQuery: q }),

  // View mode
  currentView: "canvas",
  setCurrentView: (v) => set({ currentView: v }),
}));