import { Blueprint, SEED_BLUEPRINT } from "@/data/index";

const STORAGE_KEY = "agent-blueprint:v1";

export function loadBlueprint(): Blueprint | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed as Blueprint;
  } catch {
    return null;
  }
}

export function saveBlueprint(bp: Blueprint): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(bp));
  } catch {
    // localStorage may be full or blocked — silently ignore
  }
}

export function resetToSeed(): Blueprint {
  return SEED_BLUEPRINT;
}

export function exportJSON(bp: Blueprint): string {
  return JSON.stringify(bp, null, 2);
}

export function importJSON(json: string): Blueprint | null {
  try {
    const parsed = JSON.parse(json) as Blueprint;
    if (!parsed.version || !parsed.nodes || !parsed.edges) return null;
    return parsed;
  } catch {
    return null;
  }
}