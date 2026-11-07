interface StatusDotProps {
  status: "done" | "building" | "planned";
  className?: string;
}

const statusColors: Record<string, string> = {
  done: "bg-green-500",
  building: "bg-amber-500",
  planned: "bg-slate-500",
};

export function StatusDot({ status, className }: StatusDotProps) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full animate-pulse ${statusColors[status]} ${className}`}
    />
  );
}