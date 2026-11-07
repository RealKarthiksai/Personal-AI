import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";

import { ReactNode } from "react";

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  return (
    <div className="min-h-screen bg-dark-bg text-dark-text selection:bg-amber-500/30 selection:text-white">
      <TopBar isSidebarOpen={isSidebarOpen} setIsSidebarOpen={setIsSidebarOpen} />
      <div className="flex">
        <Sidebar isOpen={isSidebarOpen} />
        <div className="flex-1 flex flex-col h-[calc(100vh-4rem)]">
          {children}
        </div>
      </div>
    </div>
  );
}