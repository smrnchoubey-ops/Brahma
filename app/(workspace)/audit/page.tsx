import { AuditLedger } from "@/components/audit/audit-ledger";
import { auditEvents } from "@/lib/mock-data";

export default function AuditPage() {
  return <AuditLedger events={auditEvents} />;
}
