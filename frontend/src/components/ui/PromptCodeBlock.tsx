import { templateSegments } from "@/lib/template";
import { cn } from "@/lib/utils";

interface PromptCodeBlockProps {
  prompt: string;
  className?: string;
}

export function PromptCodeBlock({ prompt, className }: PromptCodeBlockProps) {
  const segments = templateSegments(prompt);

  return (
    <div className={cn("bg-slate-950 border border-slate-800 rounded p-4 overflow-x-auto font-mono text-xs text-slate-300", className)}>
      {segments.map((seg, i) => (
        <span key={i} className={seg.type === "variable" ? "text-amber-400 font-bold" : "text-slate-300"}>
          {seg.type === "variable" ? `{{${seg.value}}}` : seg.value}
        </span>
      ))}
    </div>
  );
}