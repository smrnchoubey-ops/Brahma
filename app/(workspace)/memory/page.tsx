import { MemoryLedger } from "@/components/memory/memory-ledger";
import { memoryItems } from "@/lib/mock-data";

export default function MemoryPage() {
  return <MemoryLedger items={memoryItems} />;
}
