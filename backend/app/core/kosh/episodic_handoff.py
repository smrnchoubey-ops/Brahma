"""
KARMA to KOSH Episodic Memory Handoff Controller
Strictly conforms to BRAHMA COS Whitesheet §9.3.

Indexes completed execution traces from validated KARMA plans into Tier 2 Episodic Memory.
Enforces strict gate: only plans satisfying §7.8 Completion Validation and §7.9 No-Silent-Actions
are permitted into episodic storage.
"""
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from app.core.karma.executor import KarmaDAGExecutionReport, KarmaStepExecutionResult
from app.core.kosh.memory_tiers import KoshChunk, MemoryTier
from app.core.kosh.vector_engine import KoshVectorStore, generate_deterministic_test_embedding
from app.core.chitra.crypto import generate_ulid


class KoshEpisodicHandoffResult(BaseModel):
    """
    Structured outcome of the Episodic Memory Handoff process.
    Matches Whitesheet §9.3.
    """
    success: bool
    status: str = Field(description="'HANDOFF_INDEXED' | 'HANDOFF_REJECTED'")
    indexed_chunks_count: int = 0
    chunk_ids: List[str] = Field(default_factory=list)
    failure_reason: Optional[str] = None


class KoshEpisodicHandoffController:
    """
    Handles episodic memory indexing from validated KARMA execution reports.
    """

    @classmethod
    def process_plan_handoff(
        cls,
        report: KarmaDAGExecutionReport,
        tenant_id: str,
        vector_store: KoshVectorStore,
        embedding_fn: Optional[callable] = None
    ) -> KoshEpisodicHandoffResult:
        """
        Validates KARMA execution report and indexes verified steps into Episodic Memory.
        """
        if not report:
            return KoshEpisodicHandoffResult(
                success=False,
                status="HANDOFF_REJECTED",
                failure_reason="Execution report is null or empty."
            )

        # 1. Plan-level Status Gate (§9.3)
        if report.status not in ["COMPLETED", "PARTIALLY_COMPLETED"]:
            return KoshEpisodicHandoffResult(
                success=False,
                status="HANDOFF_REJECTED",
                failure_reason=f"Plan execution status '{report.status}' is not eligible for episodic memory handoff."
            )

        embed_fn = embedding_fn or generate_deterministic_test_embedding
        indexed_chunks: List[str] = []

        # 2. Step-level Verification & No-Silent-Actions Inspection (§7.8, §7.9, §9.3)
        for step_id, step_res in report.step_results.items():
            if step_res.status != "SUCCEEDED":
                continue

            # Verify completion validation record is present and valid
            comp_val = step_res.completion_validation
            if not comp_val or not comp_val.get("is_valid") or not comp_val.get("no_silent_action_valid"):
                continue

            # Extract verified episodic evidence
            action_desc = step_res.action
            actual_out = str(step_res.output)
            ledger_ref = step_res.chitra_event_id or comp_val.get("audit_trail_ref")

            audit_refs = [ledger_ref] if ledger_ref else []
            chunk_content = f"Action: {action_desc} | Outcome: {actual_out} | Evidence: {audit_refs}"
            chunk_id = generate_ulid(prefix="ep_")

            embedding_vec = embed_fn(chunk_content)

            chunk = KoshChunk(
                chunk_id=chunk_id,
                tenant_id=tenant_id,
                title=f"Episodic Memory for Task {report.task_id} (Step: {step_id})",
                content=chunk_content,
                tier=MemoryTier.EPISODIC,
                task_id=report.task_id,
                step_id=step_id,
                audit_trail_refs=audit_refs,
                metadata={
                    "plan_id": report.plan_id,
                    "tool_id": step_res.tool_id,
                    "attempts_made": step_res.attempts_made,
                    "verification_status": step_res.verification_status
                },
                embedding=embedding_vec
            )

            vector_store.add_chunk(chunk)
            indexed_chunks.append(chunk_id)

        if not indexed_chunks:
            return KoshEpisodicHandoffResult(
                success=False,
                status="HANDOFF_REJECTED",
                failure_reason="No verified steps with complete No-Silent-Actions evidence were available for indexing."
            )

        return KoshEpisodicHandoffResult(
            success=True,
            status="HANDOFF_INDEXED",
            indexed_chunks_count=len(indexed_chunks),
            chunk_ids=indexed_chunks,
            failure_reason=None
        )
