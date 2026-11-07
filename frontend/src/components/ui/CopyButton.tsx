import React from "react";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  text: string;
  size?: "sm" | "md";
  className?: string;
}

export function CopyButton({ text, size = "sm", className }: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const base = "flex items-center justify-center gap-1.5 text-xs rounded border border-slate-700 bg-slate-800/50 hover:bg-slate-800 text-slate-400 hover:text-white transition-colors";
  const sizeClasses = size === "sm" ? "px-2 py-1" : "px-3 py-1.5";

  return (
    <button onClick={handleCopy} className={cn(base, sizeClasses, className)} title="Copy to clipboard">
      {copied ? (
        <>
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
          Copied
        </>
      ) : (
        <>
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
          </svg>
          Copy
        </>
      )}
    </button>
  );
}