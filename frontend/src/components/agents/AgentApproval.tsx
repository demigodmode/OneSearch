import { Button } from "@/components/ui/button";
import type { Agent } from "@/types/api";

export function AgentApproval({
  agent,
  onApprove,
  pending,
}: {
  agent: Agent;
  onApprove: () => void;
  pending: boolean;
}) {
  if (agent.status !== "pending") return null;
  return (
    <Button size="sm" onClick={onApprove} disabled={pending}>
      Approve agent
    </Button>
  );
}
