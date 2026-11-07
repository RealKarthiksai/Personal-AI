import React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
}

export function Button({
  className,
  variant = "default",
  size = "md",
  ...props
}: ButtonProps) {
  const base = "inline-flex items-center justify-center rounded-card font-medium text-sm transition-colors focus:outline-none focus:ring-2 focus-ring-offset-2 disabled:pointer-events-none disabled:opacity-50";
  const variants: Record<string, string> = {
    default: "bg-primary text-primary-foreground hover:bg-primary/90 focus:ring-primary",
    outline:
      "border border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white focus:ring-slate-500",
    ghost: "hover:bg-slate-800 hover:text-white text-slate-400",
    destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90 focus:ring-destructive",
  };
  const sizes: Record<string, string> = {
    sm: "h-8 px-3 text-xs",
    md: "h-10 px-4",
    lg: "h-11 px-8 text-base",
  };

  return (
    <button
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    />
  );
}