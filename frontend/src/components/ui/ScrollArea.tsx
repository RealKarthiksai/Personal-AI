import React from "react";
import { cn } from "@/lib/utils";

export function ScrollArea({
  className,
  children,
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("overflow-y-auto", className)}>
      {children}
    </div>
  );
}

export function ScrollBar() {
  return null;
}