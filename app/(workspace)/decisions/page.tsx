import { DecisionReview } from "@/components/decisions/decision-review";
import { decisions } from "@/lib/mock-data";

export default function DecisionsPage() {
  return <DecisionReview initialDecisions={decisions} />;
}
