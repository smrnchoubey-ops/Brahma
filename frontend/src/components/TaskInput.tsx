"use client";

import { useState } from "react";
import { CornerDownLeft, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function TaskInput({ onSubmit, isSubmitting = false }: { onSubmit: (intent: string) => void, isSubmitting?: boolean }) {
  const [intent, setIntent] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!intent.trim() || isSubmitting) return;
    onSubmit(intent);
    setIntent("");
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="relative flex flex-col w-full bg-white/[0.02] border border-white/10 rounded focus-within:border-blue-500/50 transition-colors overflow-hidden"
    >
      <div className="flex items-center px-4 py-2.5 border-b border-white/5 bg-white/[0.01]">
        <Sparkles className="w-3.5 h-3.5 text-blue-400 mr-2" />
        <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
          Command Interface
        </span>
      </div>
      <Textarea
        value={intent}
        onChange={(e) => setIntent(e.target.value)}
        placeholder="Enter natural language directive..."
        className="min-h-[80px] w-full resize-none border-0 p-4 shadow-none focus-visible:ring-0 text-sm bg-transparent text-slate-200 placeholder:text-slate-600"
        disabled={isSubmitting}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit(e);
          }
        }}
      />
      <div className="flex items-center justify-between px-4 py-2.5 bg-white/[0.01] border-t border-white/5">
        <div className="text-[10px] text-slate-500 uppercase tracking-wider">
          Press <kbd className="px-1 py-0.5 rounded bg-white/5 border border-white/10 mx-1">Enter</kbd> to execute
        </div>
        <Button 
          size="sm" 
          type="submit" 
          disabled={!intent.trim() || isSubmitting}
          className="h-7 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded px-3"
        >
          {isSubmitting ? "Executing..." : "Execute"} <CornerDownLeft className="w-3 h-3 ml-1.5 opacity-70" />
        </Button>
      </div>
    </form>
  );
}
