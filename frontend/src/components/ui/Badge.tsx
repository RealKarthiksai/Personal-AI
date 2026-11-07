import { cn } from "@/lib/utils";

export interface BadgeProps {
  variant: "default" | "secondary" | "destructive" | "outline";
  className?: string;
  children: React.ReactNode;
}

export function Badge({ variant = "default", className, children }: BadgeProps) {
  const base = "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors";
  const variants: Record<string, string> = {
    default: "bg-primary text-primary-foreground",
    secondary: "bg-secondary text-secondary-foreground",
    destructive: "bg-destructive text-destructive-foreground",
    outline: "border input",
  };
  return (
    <span className={cn(base, variants[variant], className)}>
      {children}
    </span>
  );
}