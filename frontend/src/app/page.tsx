"use client";

import { useState, useEffect } from "react";
import { TaskInput } from "@/components/TaskInput";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { LogOut, AlertTriangle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { createTask, getAllTasks, getMetrics, getAgents, getAudit, getTaskStatus, Task } from "@/lib/api";

export default function Home() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [agents, setAgents] = useState<any[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submissionStatus, setSubmissionStatus] = useState<{ type: 'success' | 'error' | null, message: string }>({ type: null, message: '' });
  const [isLoaded, setIsLoaded] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  
  const [selectedTask, setSelectedTask] = useState<any>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleTaskClick = async (taskId: string) => {
    try {
      const taskData = await getTaskStatus(taskId);
      setSelectedTask(taskData);
      setIsModalOpen(true);
    } catch (err) {
      console.error("Failed to load task details", err);
    }
  };

  const fetchData = async () => {
    try {
      const [fetchedTasks, fetchedMetrics, fetchedAgents, fetchedAudit] = await Promise.all([
        getAllTasks(),
        getMetrics(),
        getAgents(),
        getAudit()
      ]);
      setTasks(fetchedTasks.sort((a: any, b: any) => Number(b.id) - Number(a.id)));
      setMetrics(fetchedMetrics);
      setAgents(fetchedAgents);
      setAudit(fetchedAudit);
      setConnectionError(false);
    } catch (err) {
      console.error("Failed to fetch dashboard data", err);
      setConnectionError(true);
    } finally {
      setIsLoaded(true);
    }
  };

  useEffect(() => {
    fetchData();
    // In a real enterprise system, we'd use WebSockets. For now, poll every 5s.
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleTaskSubmit = async (intent: string) => {
    setIsSubmitting(true);
    setSubmissionStatus({ type: null, message: '' });
    
    try {
      await createTask(intent);
      setSubmissionStatus({ type: 'success', message: 'Task submitted successfully.' });
      await fetchData(); // Refresh data immediately
    } catch (err: any) {
      console.error(err);
      setSubmissionStatus({ type: 'error', message: err.message || 'Failed to submit task.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isLoaded) {
    return <div className="flex h-screen w-full items-center justify-center text-sm text-muted-foreground tracking-widest uppercase">Initializing Command Center...</div>;
  }

  return (
    <div className="flex flex-col h-full bg-[#09090b] text-slate-200 overflow-hidden font-sans">
      {/* Top Header */}
      <header className="px-8 py-5 border-b border-white/5 bg-[#09090b]/80 backdrop-blur-md flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-white">BRAHMA COS</h1>
          <p className="text-xs text-slate-400 uppercase tracking-widest mt-1">Enterprise Operations Command Center</p>
        </div>
        <div className="flex items-center space-x-4">
          {connectionError ? (
            <Badge variant="outline" className="bg-red-500/10 text-red-400 border-red-500/20 rounded-sm flex items-center">
              <AlertTriangle className="w-3 h-3 mr-1.5" /> Backend Disconnected
            </Badge>
          ) : (
            <Badge variant="outline" className="bg-green-500/10 text-green-400 border-green-500/20 rounded-sm">
              {metrics?.system_health || "Healthy"}
            </Badge>
          )}
          <div className="text-xs text-slate-500">{new Date().toISOString().split('T')[0]}</div>
          <button 
            onClick={() => {
              if (typeof window !== "undefined") {
                localStorage.removeItem("access_token");
                window.location.href = "/login";
              }
            }} 
            className="p-1.5 text-slate-400 hover:text-white hover:bg-white/10 rounded transition-colors"
            title="Logout"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-8 space-y-8 max-w-[1600px] mx-auto">
          
          {/* Executive Overview */}
          <section>
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Executive Overview</h2>
            <div className="grid grid-cols-6 gap-4">
              <MetricCard title="Total Tasks" value={metrics?.total ?? "-"} />
              <MetricCard title="Running" value={metrics?.running ?? "-"} className="text-blue-400" />
              <MetricCard title="Completed" value={metrics?.completed ?? "-"} className="text-green-400" />
              <MetricCard title="Failed" value={metrics?.failed ?? "-"} className="text-red-400" />
              <MetricCard title="Blocked" value={metrics?.blocked ?? "-"} className="text-orange-400" />
              <MetricCard title="Human Review" value={metrics?.human_review ?? "-"} className="text-purple-400" />
            </div>
          </section>

          <Separator className="bg-white/5" />

          {/* Workflow Pipeline & Agent Operations */}
          <section className="grid grid-cols-3 gap-8">
            <div className="col-span-2">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Agent Operations Pipeline</h2>
              <Card className="bg-[#0f172a]/50 border-white/5 backdrop-blur-sm rounded-md shadow-none">
                <CardContent className="p-6">
                  <div className="flex items-center justify-between relative">
                    {/* Visual Line connecting agents */}
                    <div className="absolute top-1/2 left-0 right-0 h-[1px] bg-white/10 -z-10" />
                    
                    {['KARMA', 'KOSH', 'PRAGYA', 'MURPHY', 'MARYADA', 'RACHIT'].map((agentName, idx) => {
                      const agent = agents.find(a => a.name === agentName);
                      const isVerified = agent?.status === "Implemented & Verified";
                      return (
                        <div key={agentName} className="flex flex-col items-center bg-[#0f172a] px-4 py-2 rounded border border-white/5">
                          <span className={`text-sm font-medium ${isVerified ? 'text-white' : 'text-slate-500'}`}>{agentName}</span>
                          <span className="text-[10px] text-slate-500 uppercase mt-1">{agent?.role || 'Unknown'}</span>
                          <div className={`w-2 h-2 rounded-full mt-3 ${isVerified ? 'bg-green-500/50 shadow-[0_0_8px_rgba(34,197,94,0.4)]' : 'bg-slate-700'}`} />
                        </div>
                      )
                    })}
                  </div>
                  
                  {/* Other Agents (SMRITI, etc) */}
                  <div className="mt-8 pt-6 border-t border-white/5 grid grid-cols-4 gap-4">
                    {['SMRITI', 'NIYANTRA', 'LISA'].map(agentName => {
                      const agent = agents.find(a => a.name === agentName);
                      return (
                        <div key={agentName} className="flex flex-col border border-white/5 p-3 rounded bg-white/[0.02]">
                          <span className="text-xs font-medium text-slate-500">{agentName}</span>
                          <span className="text-[10px] text-slate-600 uppercase">{agent?.role || 'Agent'}</span>
                          <span className="text-[10px] text-orange-400/50 mt-2 font-semibold">CONCEPTUAL / PLANNED</span>
                        </div>
                      )
                    })}
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Task Submission Command Bar */}
            <div className="col-span-1 flex flex-col h-full">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Command Interface</h2>
              <Card className="flex-1 bg-blue-950/10 border-blue-500/20 backdrop-blur-sm rounded-md shadow-none flex flex-col">
                <CardContent className="p-6 flex-1 flex flex-col">
                  <TaskInput onSubmit={handleTaskSubmit} isSubmitting={isSubmitting} />
                  {submissionStatus.type && (
                    <div className={`mt-4 p-3 text-xs rounded border ${submissionStatus.type === 'success' ? 'bg-green-500/10 text-green-400 border-green-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                      {submissionStatus.message}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </section>

          <Separator className="bg-white/5" />

          {/* Data Tables */}
          <section className="grid grid-cols-2 gap-8 pb-12">
            {/* Task Operations */}
            <div>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Task Operations</h2>
              <Card className="bg-[#0f172a]/50 border-white/5 shadow-none rounded-md overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-slate-400 uppercase bg-white/[0.02] border-b border-white/5">
                      <tr>
                        <th className="px-4 py-3 font-medium">ID</th>
                        <th className="px-4 py-3 font-medium">Intent</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium">Created</th>
                        <th className="px-4 py-3 font-medium text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {tasks.slice(0, 8).map((task) => (
                        <tr key={task.id} className="hover:bg-white/[0.05] transition-colors">
                          <td className="px-4 py-3 text-slate-400">#{task.id}</td>
                          <td className="px-4 py-3 truncate max-w-[150px]">{task.prompt}</td>
                          <td className="px-4 py-3">
                            <StatusBadge status={task.status} />
                          </td>
                          <td className="px-4 py-3 text-slate-500 text-xs">
                            {new Date(task.created_at).toLocaleTimeString()}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button onClick={() => handleTaskClick(task.id)} className="text-xs bg-white/10 hover:bg-white/20 px-2 py-1 rounded text-white transition-colors">
                              View Trace
                            </button>
                          </td>
                        </tr>
                      ))}
                      {tasks.length === 0 && (
                        <tr>
                          <td colSpan={4} className="px-4 py-8 text-center text-slate-500">No data available</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>

            {/* Audit Ledger */}
            <div>
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Audit Ledger</h2>
              <Card className="bg-[#0f172a]/50 border-white/5 shadow-none rounded-md overflow-hidden h-[340px]">
                <ScrollArea className="h-full">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-slate-400 uppercase bg-white/[0.02] border-b border-white/5 sticky top-0 backdrop-blur-md">
                      <tr>
                        <th className="px-4 py-3 font-medium">Time</th>
                        <th className="px-4 py-3 font-medium">Agent</th>
                        <th className="px-4 py-3 font-medium">Event</th>
                        <th className="px-4 py-3 font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {audit.map((evt, i) => (
                        <tr key={i} className="hover:bg-white/[0.02] transition-colors">
                          <td className="px-4 py-3 text-slate-500 text-xs">
                            {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : '-'}
                          </td>
                          <td className="px-4 py-3 font-medium text-slate-300">{evt.agent}</td>
                          <td className="px-4 py-3 text-slate-400">{evt.event}</td>
                          <td className="px-4 py-3 text-xs text-slate-500">{evt.action}</td>
                        </tr>
                      ))}
                      {audit.length === 0 && (
                        <tr>
                          <td colSpan={4} className="px-4 py-8 text-center text-slate-500">No data available</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </ScrollArea>
              </Card>
            </div>
          </section>

          <Separator className="bg-white/5" />

          {/* Knowledge Base Section */}
          <section className="pb-12">
            <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Knowledge Base (KOSH)</h2>
            <Card className="bg-[#0f172a]/50 border-white/5 shadow-none rounded-md">
              <CardContent className="p-6">
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <div className="w-12 h-12 bg-white/5 rounded-full flex items-center justify-center mb-4">
                    <svg className="w-6 h-6 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 002-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                    </svg>
                  </div>
                  <h3 className="text-slate-300 font-medium mb-1">Vector Storage Indexed</h3>
                  <p className="text-sm text-slate-500 mb-4 max-w-md">KOSH pgvector semantic retrieval is actively integrated into the LangGraph orchestration pipeline.</p>
                  <Badge variant="outline" className="bg-orange-500/10 text-orange-400 border-orange-500/20 rounded-sm font-normal">
                    Direct File Uploads Currently Unavailable (API Only)
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </section>

        </div>
      </ScrollArea>

      {/* Task Detail Modal */}
      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="max-w-3xl bg-[#09090b] border border-white/10 text-slate-200">
          <DialogHeader>
            <DialogTitle>Task Execution Trace #{selectedTask?.id}</DialogTitle>
            <DialogDescription>
              Chronological workflow trace across BRAHMA agents.
            </DialogDescription>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh]">
            <div className="space-y-6 pr-4 mt-2">
              <div className="mb-4 bg-white/5 p-4 rounded">
                <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">User Intent</div>
                <div className="text-sm">{selectedTask?.prompt}</div>
                <div className="mt-3">
                  <StatusBadge status={selectedTask?.status || ''} />
                </div>
              </div>

              <div className="border-l-2 border-white/10 pl-6 space-y-8 py-2 relative">
                
                {/* KARMA */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-blue-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">KARMA (Orchestration)</div>
                  <div className="text-xs text-slate-400 bg-white/5 p-3 rounded">Intent Parsed. Dispatched to graph.</div>
                </div>

                {/* KOSH */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-teal-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">KOSH (Knowledge Retrieval)</div>
                  {selectedTask?.plan ? (
                    <div className="text-xs text-slate-400 bg-white/5 p-3 rounded font-mono">
                      Knowledge retrieval executed. Context passed to PRAGYA.
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic">NOT EXECUTED</div>
                  )}
                </div>

                {/* PRAGYA */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-indigo-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">PRAGYA (Planner)</div>
                  {selectedTask?.plan ? (
                    <div className="text-xs text-slate-400 bg-white/5 p-3 rounded whitespace-pre-wrap font-mono">
                      {JSON.stringify(selectedTask.plan, null, 2)}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic">NOT EXECUTED</div>
                  )}
                </div>

                {/* MURPHY */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-red-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">MURPHY (Red-Team)</div>
                  {selectedTask?.risk_report ? (
                    <div className="text-xs text-slate-400 bg-white/5 p-3 rounded whitespace-pre-wrap font-mono">
                      {JSON.stringify(selectedTask.risk_report, null, 2)}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic">NOT EXECUTED</div>
                  )}
                </div>

                {/* MARYADA */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-orange-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">MARYADA (Governance Gate)</div>
                  {selectedTask?.policy_verdict ? (
                    <div className="text-xs text-slate-400 bg-white/5 p-3 rounded whitespace-pre-wrap font-mono">
                      {JSON.stringify(selectedTask.policy_verdict, null, 2)}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic">NOT EXECUTED</div>
                  )}
                </div>

                {/* RACHIT */}
                <div className="relative">
                  <div className="absolute -left-[31px] w-3 h-3 bg-green-500 rounded-full" />
                  <div className="text-sm font-medium text-white mb-1">RACHIT (Executor)</div>
                  {selectedTask?.execution_result ? (
                    <div className="text-xs text-slate-400 bg-white/5 p-3 rounded whitespace-pre-wrap font-mono">
                      {selectedTask.execution_result}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-500 italic">NOT EXECUTED</div>
                  )}
                </div>

              </div>
            </div>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MetricCard({ title, value, className = "" }: { title: string, value: string | number, className?: string }) {
  return (
    <Card className="bg-[#0f172a]/50 border-white/5 shadow-none rounded-md">
      <CardContent className="p-4">
        <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{title}</div>
        <div className={`text-2xl font-light ${className}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  let color = "bg-slate-500/10 text-slate-400 border-slate-500/20";
  if (status === "RUNNING") color = "bg-blue-500/10 text-blue-400 border-blue-500/20";
  if (status === "COMPLETED") color = "bg-green-500/10 text-green-400 border-green-500/20";
  if (status === "FAILED") color = "bg-red-500/10 text-red-400 border-red-500/20";
  if (status === "BLOCKED") color = "bg-orange-500/10 text-orange-400 border-orange-500/20";
  if (status === "HUMAN_REVIEW") color = "bg-purple-500/10 text-purple-400 border-purple-500/20";
  
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium border ${color}`}>
      {status}
    </span>
  );
}
