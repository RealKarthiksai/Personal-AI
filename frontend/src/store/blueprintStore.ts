import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { SEED_BLUEPRINT, Blueprint, Node, Edge, Model, LLMCall, Feature } from "@/data/index";

const STORAGE_KEY = "agent-blueprint:v1";

interface BlueprintState {
  blueprint: Blueprint;
  isEditMode: boolean;
  setBlueprint: (bp: Blueprint) => void;
  resetToSeed: () => void;
  toggleEditMode: () => void;
  setEditMode: (v: boolean) => void;
  // Node mutations
  addNode: (node: Node) => void;
  updateNode: (id: string, patch: Partial<Node>) => void;
  deleteNode: (id: string) => void;
  // Edge mutations
  addEdge: (edge: Edge) => void;
  updateEdge: (id: string, patch: Partial<Edge>) => void;
  deleteEdge: (id: string) => void;
  // Model mutations
  updateModel: (id: string, patch: Partial<Model>) => void;
  // LLM call mutations
  updateLLMCall: (id: string, patch: Partial<LLMCall>) => void;
  // Feature mutations
  updateFeature: (id: string, patch: Partial<Feature>) => void;
}

export const useBlueprintStore = create<BlueprintState>()(
  persist(
    (set) => ({
      blueprint: SEED_BLUEPRINT,
      isEditMode: false,

      setBlueprint: (bp) => set({ blueprint: bp }),
      resetToSeed: () => set({ blueprint: SEED_BLUEPRINT }),
      toggleEditMode: () => set((s) => ({ isEditMode: !s.isEditMode })),
      setEditMode: (v) => set({ isEditMode: v }),

      addNode: (node) =>
        set((s) => ({
          blueprint: { ...s.blueprint, nodes: [...s.blueprint.nodes, node] },
        })),
      updateNode: (id, patch) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            nodes: s.blueprint.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
          },
        })),
      deleteNode: (id) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            nodes: s.blueprint.nodes.filter((n) => n.id !== id),
            edges: s.blueprint.edges.filter((e) => e.source !== id && e.target !== id),
          },
        })),
      addEdge: (edge) =>
        set((s) => ({
          blueprint: { ...s.blueprint, edges: [...s.blueprint.edges, edge] },
        })),
      updateEdge: (id, patch) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            edges: s.blueprint.edges.map((e) => (e.id === id ? { ...e, ...patch } : e)),
          },
        })),
      deleteEdge: (id) =>
        set((s) => ({
          blueprint: { ...s.blueprint, edges: s.blueprint.edges.filter((e) => e.id !== id) },
        })),
      updateModel: (id, patch) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            models: s.blueprint.models.map((m) => (m.id === id ? { ...m, ...patch } : m)),
          },
        })),
      updateLLMCall: (id, patch) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            llmCalls: s.blueprint.llmCalls.map((c) => (c.id === id ? { ...c, ...patch } : c)),
          },
        })),
      updateFeature: (id, patch) =>
        set((s) => ({
          blueprint: {
            ...s.blueprint,
            features: s.blueprint.features.map((f) => (f.id === id ? { ...f, ...patch } : f)),
          },
        })),
    }),
    {
      name: STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ blueprint: s.blueprint }),
    }
  )
);