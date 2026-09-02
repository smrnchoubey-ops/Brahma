"use client";

import { Check, Loader2, BrainCircuit, ShieldAlert, GitMerge } from "lucide-react";
import { Card } from "@/components/ui/card";

export function AgentTrace({ trace = [] }: { trace: any[] }) {
  return (
    <Card className="p-6 border-primary/20 bg-card/50 shadow-inner">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-6">
        Live Cognitive Trace
      </h3>
      
      {trace.length === 0 ? (
        <div className="text-sm text-muted-foreground text-center py-10">
          No active trace. Start a new operation to see agent reasoning.
        </div>
      ) : (
        <div className="relative border-l-2 border-border ml-3 space-y-8">
          
          {trace.map((step, idx) => (
            <div key={idx} className="relative pl-8">
              <div className={`absolute -left-[11px] top-1 h-5 w-5 rounded-full flex items-center justify-center border-2 ${step.status === 'done' ? 'bg-primary/20 border-primary' : 'bg-amber-500/20 border-amber-500'}`}>
                {step.status === 'done' ? <Check className="w-3 h-3 text-primary" /> : <Loader2 className="w-3 h-3 text-amber-500 animate-spin" />}
              </div>
              <div className="flex items-center gap-2 mb-1">
                {step.agent === 'KARMA' && <GitMerge className={`w-4 h-4 ${step.status === 'done' ? 'text-primary' : 'text-amber-500'}`} />}
                {step.agent === 'PRAGYA' && <BrainCircuit className={`w-4 h-4 ${step.status === 'done' ? 'text-primary' : 'text-amber-500'}`} />}
                {step.agent === 'MARYADA' && <ShieldAlert className={`w-4 h-4 ${step.status === 'done' ? 'text-primary' : 'text-amber-500'}`} />}
                <span className={`font-semibold text-sm ${step.status === 'done' ? '' : 'text-amber-500'}`}>{step.agent} {step.action}</span>
              </div>
              <p className={`text-xs ${step.status === 'done' ? 'text-muted-foreground' : 'text-amber-500/80'}`}>
                {step.status === 'done' ? 'Execution completed.' : 'In progress...'}
              </p>
            </div>
          ))}

        </div>
      )}
    </Card>
  );
}
