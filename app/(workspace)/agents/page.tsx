import { AgentMonitor } from "@/components/agents/agent-monitor";
import { agents } from "@/lib/mock-data";

export default function AgentsPage() {
  return <AgentMonitor agents={agents} />;
}
