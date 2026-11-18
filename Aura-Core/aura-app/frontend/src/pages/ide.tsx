"use client";

import { useRouter } from "next/router";
import { GraduationCap, Terminal, MessageSquare, Settings } from "lucide-react";
import { SettingsProvider } from "@/contexts/SettingsContext";
import dynamic from "next/dynamic";

// Dynamic import to avoid SSR issues with Monaco Editor
const AuraIDE = dynamic(() => import("@/components/ide/AuraIDE"), {
  ssr: false,
  loading: () => (
    <div className="h-screen bg-[#0a0a0a] flex items-center justify-center">
      <div className="text-amber-600 font-mono text-sm animate-pulse">Loading Aura IDE...</div>
    </div>
  ),
});

function IDEContent() {
  const router = useRouter();

  return (
    <div className="h-screen flex flex-col bg-[#050505] overflow-hidden">

      {/* NAVIGATION BAR */}
      <nav className="h-10 border-b border-amber-900/30 bg-black/60 flex items-center px-3 gap-1 flex-shrink-0">
        {/* Tab bar */}
        <button
          onClick={() => router.push("/chat")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
        >
          <MessageSquare size={13} />
          Chat
        </button>
        <button
          onClick={() => router.push("/mission-control")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
        >
          <Settings size={13} />
          Mission Control
        </button>
        <button
          onClick={() => router.push("/school")}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
        >
          <GraduationCap size={13} />
          School
        </button>
        <button
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono text-amber-300 bg-amber-900/20 border border-amber-700/30 transition-colors"
        >
          <Terminal size={13} />
          IDE
        </button>

        <div className="flex-1" />

        {/* Branding */}
        <div className="flex items-center gap-2 text-[10px] font-mono text-gray-600">
          <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          <span>AURA IDE</span>
          <span className="text-gray-800">v0.5.0</span>
        </div>
      </nav>

      {/* IDE fills remaining space */}
      <div className="flex-1 overflow-hidden">
        <AuraIDE />
      </div>
    </div>
  );
}

export default function IDEPage() {
  return (
    <SettingsProvider>
      <IDEContent />
    </SettingsProvider>
  );
}
