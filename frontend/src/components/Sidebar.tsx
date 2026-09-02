import Link from "next/link";
import { 
  LayoutDashboard, 
  BookOpen, 
  ListChecks, 
  Database,
  BrainCircuit
} from "lucide-react";

export function Sidebar() {
  return (
    <div className="flex h-screen w-64 flex-col border-r border-white/5 bg-[#09090b] text-slate-300">
      <div className="flex h-16 items-center px-6 border-b border-white/5">
        <BrainCircuit className="h-5 w-5 mr-3 text-slate-100" />
        <span className="text-sm font-bold tracking-widest uppercase text-slate-100">BRAHMA COS</span>
      </div>
      <div className="flex-1 py-6">
        <nav className="grid items-start px-4 text-xs font-medium gap-2 tracking-wide uppercase">
          <Link
            href="/"
            className="flex items-center gap-3 rounded px-3 py-2.5 text-white bg-white/5 border border-white/5 transition-all"
          >
            <LayoutDashboard className="h-4 w-4" />
            Command Center
          </Link>
          <Link
            href="#"
            className="flex items-center gap-3 rounded px-3 py-2.5 text-slate-500 hover:text-slate-200 hover:bg-white/[0.02] transition-all"
          >
            <BookOpen className="h-4 w-4" />
            Knowledge Base
          </Link>
          <Link
            href="#"
            className="flex items-center gap-3 rounded px-3 py-2.5 text-slate-500 hover:text-slate-200 hover:bg-white/[0.02] transition-all"
          >
            <Database className="h-4 w-4" />
            Memory Ledger
          </Link>
          <Link
            href="#"
            className="flex items-center gap-3 rounded px-3 py-2.5 text-slate-500 hover:text-slate-200 hover:bg-white/[0.02] transition-all"
          >
            <ListChecks className="h-4 w-4" />
            Audit Ledger
          </Link>
        </nav>
      </div>
      <div className="p-4 border-t border-white/5">
        <button 
          onClick={() => {
            if (typeof window !== "undefined") {
              localStorage.removeItem("access_token");
              window.location.href = "/login";
            }
          }}
          className="w-full flex items-center gap-3 rounded px-3 py-2 hover:bg-white/[0.02] transition-colors text-left"
        >
          <div className="w-7 h-7 rounded-full bg-blue-500/20 border border-blue-500/30 flex items-center justify-center text-blue-400 font-bold text-xs shrink-0">
            F
          </div>
          <div className="flex flex-col overflow-hidden">
            <span className="text-xs font-medium text-slate-200">Founder</span>
            <span className="text-[10px] text-slate-500 uppercase tracking-wider mt-0.5">Logout</span>
          </div>
        </button>
      </div>
    </div>
  );
}
