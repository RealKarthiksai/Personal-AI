import { Routes, Route } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { FlowCanvasPage } from "@/pages/FlowCanvasPage";
import { PromptRegistryPage } from "@/pages/PromptRegistryPage";
import { ModelsPage } from "@/pages/ModelsPage";
import { FeaturesPage } from "@/pages/FeaturesPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<FlowCanvasPage />} />
        <Route path="/canvas" element={<FlowCanvasPage />} />
        <Route path="/prompts" element={<PromptRegistryPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/features" element={<FeaturesPage />} />
      </Routes>
    </AppShell>
  );
}