"""Persistent provider-neutral Executor–Critic editorial workflow."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from editorial_agent.approval import ApprovalGate
from editorial_agent.context_services import EditorialContextService
from editorial_agent.contracts.events import EventType, RunEvent
from editorial_agent.contracts.handoffs import AgentHandoff
from editorial_agent.contracts.identity import (
    DocumentVersionId,
    EventId,
    FactId,
    HandoffId,
    RunId,
    WorkflowRequestContext,
)
from editorial_agent.contracts.storage import (
    DocumentVersionRecord,
    PrivateFact,
    PrivateFactStore,
)
from editorial_agent.contracts.workflow import (
    DEFAULT_MAX_CRITIC_REVISIONS,
    AgentOutcome,
    AgentRole,
    BlockedReason,
    OutcomeStatus,
    RunStatus,
    SanitizedError,
    TransitionAction,
    validate_transition,
)
from editorial_agent.domain_repository import SQLiteDomainRepository
from editorial_agent.errors import EditorialServiceError
from editorial_agent.models import ModelClient, ToolCall
from editorial_agent.role_agents import RoleAgent, RoleAgentError
from editorial_agent.role_prompts import build_critic_prompt, build_executor_prompt
from editorial_agent.role_results import (
    CriticIssueType,
    CriticResult,
    ExecutorResult,
    RuleCompatibility,
)
from editorial_agent.role_tools import (
    create_critic_tool_registry,
    create_executor_tool_registry,
)

Clock = Callable[[], datetime]
IdFactory = Callable[[str], str]


class CriticGroundingError(RuntimeError):
    """A Critic issue alleges wording absent from the reviewed draft."""


@dataclass(frozen=True)
class EditorialWorkflowResult:
    """Terminal result of one persisted editorial workflow."""

    run_id: RunId
    status: RunStatus
    final_document_version_id: DocumentVersionId | None
    approval_granted: bool
    revision_count: int
    blocked: BlockedReason | None = None
    error: SanitizedError | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is RunStatus.COMPLETED and self.approval_granted


def _default_clock() -> datetime:
    return datetime.now(UTC)


def _default_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class EditorialWorkflowRunner:
    """Coordinate explicit Executor and Critic roles through persisted state."""

    def __init__(
        self,
        *,
        repository: SQLiteDomainRepository,
        private_facts: PrivateFactStore,
        context_service: EditorialContextService,
        executor_model: ModelClient,
        critic_model: ModelClient,
        approval_gate: ApprovalGate | None,
        max_revisions: int = DEFAULT_MAX_CRITIC_REVISIONS,
        max_role_steps: int = 6,
        clock: Clock = _default_clock,
        id_factory: IdFactory = _default_id,
    ) -> None:
        if max_revisions < 0:
            raise ValueError("max_revisions must not be negative")
        if max_role_steps < 1:
            raise ValueError("max_role_steps must be positive")
        self._repository = repository
        self._private_facts = private_facts
        self._context_service = context_service
        self._executor_model = executor_model
        self._critic_model = critic_model
        self._approval_gate = approval_gate
        self._max_revisions = max_revisions
        self._max_role_steps = max_role_steps
        self._clock = clock
        self._id_factory = id_factory
        self._event_sequence = 0
        self._handoff_sequence = 0
        self._context: WorkflowRequestContext | None = None
        self._executor_retrieved_shared_comments = False

    def run(self, context: WorkflowRequestContext) -> EditorialWorkflowResult:
        """Run from authorized source through Critic acceptance and approval."""

        self._context = context
        self._event_sequence = 0
        self._handoff_sequence = 0
        self._executor_retrieved_shared_comments = False
        revision_count = 0
        current_version: DocumentVersionRecord | None = None
        run_created = False
        try:
            self._repository.create_run(context=context)
            run_created = True
            self._emit(
                EventType.RUN_STARTED,
                AgentRole.ORCHESTRATOR,
                {"request_attached": True},
            )
            initial_push = self._context_service.build_push_context(
                context,
                AgentRole.EXECUTOR,
            )
            source_content = initial_push.document_version.content
            self._emit_context(initial_push)
            revision_feedback: CriticResult | None = None
            previous_feedback_key: str | None = None

            while True:
                executor_push = (
                    initial_push
                    if current_version is None
                    else self._context_service.build_push_context(
                        context,
                        AgentRole.EXECUTOR,
                    )
                )
                if current_version is not None:
                    self._emit_context(executor_push)
                executor = RoleAgent(
                    role=AgentRole.EXECUTOR,
                    model=self._executor_model,
                    tools=create_executor_tool_registry(
                        context_service=self._context_service,
                        request_context=context,
                    ),
                    max_steps=self._max_role_steps,
                    required_tools=frozenset({"retrieve_private_facts"}),
                )
                executor_outcome = executor.run(
                    build_executor_prompt(
                        pushed=executor_push,
                        source_content=source_content,
                        revision_feedback=revision_feedback,
                    ),
                    **self._role_callbacks(),
                )
                if executor_outcome.needs_approval:
                    approved = self._request_approval(
                        executor_push.document_version,
                        action=executor_outcome.approval.action,
                        summary=executor_outcome.approval.summary,
                    )
                    if not approved:
                        return self._block(
                            revision_count,
                            current_version,
                            "approval_declined",
                            "The Executor's requested approval was declined.",
                        )
                    executor_outcome = self._without_approval(executor_outcome)
                executor_action = validate_transition(
                    actor=AgentRole.EXECUTOR,
                    outcome=executor_outcome,
                    critic_revisions_used=revision_count,
                    max_critic_revisions=self._max_revisions,
                )
                if executor_action is not TransitionAction.DISPATCH_CRITIC:
                    return self._finish_role_outcome(
                        executor_outcome,
                        revision_count,
                        current_version,
                    )
                executor_result = ExecutorResult.from_dict(executor_outcome.result or {})
                if (
                    current_version is not None
                    and executor_result.draft == current_version.content
                ):
                    return self._block(
                        revision_count,
                        current_version,
                        "stalled_draft",
                        "Executor returned an unchanged draft after revision feedback.",
                    )
                if current_version is None:
                    self._persist_memory_decision(
                        context=context,
                        result=executor_result,
                    )
                current_version = self._persist_draft(
                    context=context,
                    draft=executor_result.draft,
                )
                self._handoff_executor_to_critic(
                    context=context,
                    round_number=revision_count,
                    result=executor_result,
                    version=current_version,
                )

                critic_push = self._context_service.build_push_context(
                    context,
                    AgentRole.CRITIC,
                )
                self._emit_context(critic_push)
                critic = RoleAgent(
                    role=AgentRole.CRITIC,
                    model=self._critic_model,
                    tools=create_critic_tool_registry(
                        context_service=self._context_service,
                        request_context=context,
                    ),
                    max_steps=self._max_role_steps,
                    required_tools=(
                        frozenset({"retrieve_shared_comments"})
                        if self._executor_retrieved_shared_comments
                        else frozenset()
                    ),
                )
                critic_outcome = critic.run(
                    build_critic_prompt(
                        pushed=critic_push,
                        source_content=source_content,
                        candidate_content=current_version.content,
                        revision_count=revision_count,
                        max_revisions=self._max_revisions,
                        require_shared_comments=(
                            self._executor_retrieved_shared_comments
                        ),
                    ),
                    **self._role_callbacks(),
                )
                if critic_outcome.needs_approval:
                    approved = self._request_approval(
                        current_version,
                        action=critic_outcome.approval.action,
                        summary=critic_outcome.approval.summary,
                    )
                    if not approved:
                        return self._block(
                            revision_count,
                            current_version,
                            "approval_declined",
                            "The requested human approval was declined.",
                        )
                    critic_outcome = self._without_approval(critic_outcome)
                critic_result = (
                    CriticResult.from_dict(critic_outcome.result or {})
                    if critic_outcome.status
                    in {OutcomeStatus.COMPLETE, OutcomeStatus.REVISE}
                    else None
                )
                if critic_result is not None:
                    self._validate_critic_grounding(
                        result=critic_result,
                        version=current_version,
                        source_content=source_content,
                    )
                    self._record_critic_review(
                        context=context,
                        result=critic_result,
                        version=current_version,
                        round_number=revision_count,
                    )
                critic_action = validate_transition(
                    actor=AgentRole.CRITIC,
                    outcome=critic_outcome,
                    critic_revisions_used=revision_count,
                    max_critic_revisions=self._max_revisions,
                )
                if critic_action is TransitionAction.COMPLETE_WORKFLOW:
                    if critic_result is None:
                        raise RuntimeError("accepted Critic result is missing")
                    self._handoff_critic_acceptance(
                        context=context,
                        round_number=revision_count,
                        result=critic_result,
                        version=current_version,
                    )
                    approved = self._request_approval(
                        current_version,
                        action="finalize_editorial_version",
                        summary="Approve the exact Critic-accepted LinkedIn version.",
                    )
                    if not approved:
                        return self._block(
                            revision_count,
                            current_version,
                            "approval_declined",
                            "Final approval was declined.",
                        )
                    self._emit(
                        EventType.RUN_COMPLETED,
                        AgentRole.ORCHESTRATOR,
                        {
                            "final_document_version_id": (
                                current_version.document_version_id
                            ),
                            "approval_granted": True,
                            "revision_count": revision_count,
                        },
                        current_version.document_version_id,
                    )
                    self._repository.set_run_status(
                        run_id=context.run_id,
                        user_id=context.user_id,
                        document_id=context.document_id,
                        status=RunStatus.COMPLETED,
                        completed_at=self._now(),
                    )
                    return EditorialWorkflowResult(
                        run_id=context.run_id,
                        status=RunStatus.COMPLETED,
                        final_document_version_id=(
                            current_version.document_version_id
                        ),
                        approval_granted=True,
                        revision_count=revision_count,
                    )
                if critic_action is TransitionAction.DISPATCH_EXECUTOR:
                    if critic_result is None:
                        raise RuntimeError("revision Critic result is missing")
                    feedback_key = json.dumps(
                        critic_result.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if feedback_key == previous_feedback_key:
                        return self._block(
                            revision_count,
                            current_version,
                            "stalled_revision",
                            "Critic repeated identical revision feedback.",
                        )
                    previous_feedback_key = feedback_key
                    revision_count += 1
                    self._handoff_critic_to_executor(
                        context=context,
                        round_number=revision_count,
                        outcome=critic_outcome,
                        result=critic_result,
                        version=current_version,
                    )
                    revision_feedback = critic_result
                    continue
                if (
                    critic_outcome.status is OutcomeStatus.REVISE
                    and critic_action is TransitionAction.BLOCK_WORKFLOW
                ):
                    self._emit(
                        EventType.REVISION_LIMIT_REACHED,
                        AgentRole.ORCHESTRATOR,
                        {
                            "maximum_revisions": self._max_revisions,
                            "revisions_used": revision_count,
                        },
                        current_version.document_version_id,
                    )
                    return self._block(
                        revision_count,
                        current_version,
                        "revision_limit",
                        "Critic requested another revision after the limit.",
                    )
                return self._finish_role_outcome(
                    critic_outcome,
                    revision_count,
                    current_version,
                )
        except CriticGroundingError:
            error = SanitizedError(
                "critic_grounding",
                "The Critic referenced wording absent from the reviewed draft.",
            )
        except RoleAgentError as exc:
            error = SanitizedError(
                exc.code,
                (
                    "A required scoped retrieval was not attempted."
                    if exc.code == "required_tool_missing"
                    else "A role could not produce a valid structured result."
                ),
            )
        except EditorialServiceError:
            error = SanitizedError(
                "workflow_service_failure",
                "The editorial workflow service failed safely.",
            )
        except Exception:
            error = SanitizedError(
                "workflow_failure",
                "The editorial workflow failed safely.",
            )
        if run_created:
            self._safe_fail_run(context, error)
        return EditorialWorkflowResult(
            run_id=context.run_id,
            status=RunStatus.FAILED,
            final_document_version_id=(
                current_version.document_version_id if current_version else None
            ),
            approval_granted=False,
            revision_count=revision_count,
            error=error,
        )

    def _persist_memory_decision(
        self,
        *,
        context: WorkflowRequestContext,
        result: ExecutorResult,
    ) -> None:
        decision = result.memory_decision
        self._emit(
            EventType.MEMORY_SAVE_DECIDED,
            AgentRole.EXECUTOR,
            {"should_save": decision.should_save},
        )
        if not decision.should_save:
            return
        fact = PrivateFact(
            fact_id=FactId(self._id_factory("fact")),
            user_id=context.user_id,
            content=decision.content or "",
            cue=decision.cue or "",
            created_at=self._now(),
            source="executor_memory_decision",
        )
        self._private_facts.save_fact(user_id=context.user_id, fact=fact)
        self._emit(
            EventType.PRIVATE_FACT_SAVED,
            AgentRole.ORCHESTRATOR,
            {"fact_id": fact.fact_id},
        )

    def _persist_draft(
        self,
        *,
        context: WorkflowRequestContext,
        draft: str,
    ) -> DocumentVersionRecord:
        latest = self._repository.get_latest_document_version(
            user_id=context.user_id,
            document_id=context.document_id,
        )
        version = DocumentVersionRecord(
            document_version_id=DocumentVersionId(
                self._id_factory("document_version")
            ),
            document_id=context.document_id,
            version_number=latest.version_number + 1,
            content=draft,
            created_by_actor=AgentRole.EXECUTOR,
            created_by_user_id=context.user_id,
            run_id=context.run_id,
            created_at=self._now(),
        )
        stored = self._repository.create_document_version(
            user_id=context.user_id,
            version=version,
        )
        self._emit(
            EventType.DOCUMENT_VERSION_CREATED,
            AgentRole.EXECUTOR,
            {
                "document_version_id": stored.document_version_id,
                "version_number": stored.version_number,
            },
            stored.document_version_id,
        )
        return stored

    def _handoff_executor_to_critic(
        self,
        *,
        context: WorkflowRequestContext,
        round_number: int,
        result: ExecutorResult,
        version: DocumentVersionRecord,
    ) -> None:
        handoff = AgentHandoff(
            handoff_id=HandoffId(self._id_factory("handoff")),
            run_id=context.run_id,
            sequence=self._next_handoff_sequence(),
            round_number=round_number,
            from_agent=AgentRole.EXECUTOR,
            to_agent=AgentRole.CRITIC,
            status=OutcomeStatus.COMPLETE,
            payload={
                "summary": result.summary,
                "memory_should_save": result.memory_decision.should_save,
            },
            document_version_id=version.document_version_id,
            created_at=self._now(),
        )
        self._repository.append_handoff(
            user_id=context.user_id,
            document_id=context.document_id,
            handoff=handoff,
        )
        self._emit(
            EventType.HANDOFF_CREATED,
            AgentRole.EXECUTOR,
            {"handoff_id": handoff.handoff_id},
            version.document_version_id,
        )

    def _handoff_critic_to_executor(
        self,
        *,
        context: WorkflowRequestContext,
        round_number: int,
        outcome: AgentOutcome,
        result: CriticResult,
        version: DocumentVersionRecord,
    ) -> None:
        handoff = AgentHandoff(
            handoff_id=HandoffId(self._id_factory("handoff")),
            run_id=context.run_id,
            sequence=self._next_handoff_sequence(),
            round_number=round_number,
            from_agent=AgentRole.CRITIC,
            to_agent=AgentRole.EXECUTOR,
            status=OutcomeStatus.REVISE,
            payload=result.to_dict(),
            document_version_id=version.document_version_id,
            created_at=self._now(),
        )
        self._repository.append_handoff(
            user_id=context.user_id,
            document_id=context.document_id,
            handoff=handoff,
        )
        self._emit(
            EventType.HANDOFF_CREATED,
            AgentRole.CRITIC,
            {"handoff_id": handoff.handoff_id},
            version.document_version_id,
        )
        self._emit(
            EventType.REVISION_REQUESTED,
            AgentRole.CRITIC,
            {
                "issue_count": len(result.issues),
                "revision_round": round_number,
                "required_changes": list(
                    outcome.revision.required_changes if outcome.revision else ()
                ),
            },
            version.document_version_id,
        )

    def _handoff_critic_acceptance(
        self,
        *,
        context: WorkflowRequestContext,
        round_number: int,
        result: CriticResult,
        version: DocumentVersionRecord,
    ) -> None:
        handoff = AgentHandoff(
            handoff_id=HandoffId(self._id_factory("handoff")),
            run_id=context.run_id,
            sequence=self._next_handoff_sequence(),
            round_number=round_number,
            from_agent=AgentRole.CRITIC,
            to_agent=AgentRole.ORCHESTRATOR,
            status=OutcomeStatus.COMPLETE,
            payload={
                "verdict": result.verdict.value,
                "reviewed_document_version_id": version.document_version_id,
                "issue_count": 0,
                "issue_categories": [],
                "summary": result.summary,
            },
            document_version_id=version.document_version_id,
            created_at=self._now(),
        )
        self._repository.append_handoff(
            user_id=context.user_id,
            document_id=context.document_id,
            handoff=handoff,
        )
        self._emit(
            EventType.HANDOFF_CREATED,
            AgentRole.CRITIC,
            {"handoff_id": handoff.handoff_id},
            version.document_version_id,
        )

    def _validate_critic_grounding(
        self,
        *,
        result: CriticResult,
        version: DocumentVersionRecord,
        source_content: str,
    ) -> None:
        for issue in result.issues:
            reason: str | None = None
            if issue.issue_type is CriticIssueType.PRESENT_CONTENT:
                excerpt = (issue.draft_excerpt or "").strip()
                if not excerpt or excerpt not in version.content:
                    reason = "draft_excerpt_absent"
            elif issue.issue_type is CriticIssueType.MISSING_REQUIRED_CONTENT:
                context = self._required_context()
                request_evidence = (issue.request_evidence or "").strip()
                source_evidence = issue.source_evidence.strip()
                required_content = (issue.required_content or "").strip()
                if (
                    issue.rule_compatibility
                    is not RuleCompatibility.SUPPORTED
                ):
                    reason = "rule_compatibility_not_supported"
                elif (
                    not request_evidence
                    or request_evidence not in context.request
                ):
                    reason = "request_evidence_absent"
                elif (
                    not source_evidence
                    or source_evidence not in source_content
                ):
                    reason = "source_evidence_absent"
                elif (
                    not required_content
                    or required_content not in source_content
                ):
                    reason = "required_content_not_source_backed"
                elif required_content.casefold() not in issue.required_change.casefold():
                    reason = "required_change_not_source_backed"
                elif required_content in version.content:
                    reason = "required_content_not_missing"
            if reason is None:
                continue
            self._emit(
                EventType.CRITIC_GROUNDING_REJECTED,
                AgentRole.ORCHESTRATOR,
                {
                    "reviewed_document_version_id": version.document_version_id,
                    "issue_category": issue.category,
                    "issue_type": issue.issue_type.value,
                    "reason": reason,
                },
                version.document_version_id,
            )
            raise CriticGroundingError("Critic draft excerpt is not grounded.")

    def _record_critic_review(
        self,
        *,
        context: WorkflowRequestContext,
        result: CriticResult,
        version: DocumentVersionRecord,
        round_number: int,
    ) -> None:
        del context
        self._emit(
            EventType.CRITIC_REVIEW_COMPLETED,
            AgentRole.CRITIC,
            {
                "verdict": result.verdict.value,
                "reviewed_document_version_id": version.document_version_id,
                "round_number": round_number,
                "issue_count": len(result.issues),
                "issue_types": [
                    issue.issue_type.value for issue in result.issues
                ],
                "issue_categories": [issue.category for issue in result.issues],
                "grounded_excerpts": [
                    issue.draft_excerpt
                    for issue in result.issues
                    if issue.draft_excerpt is not None
                ],
                "source_evidence": [
                    issue.source_evidence for issue in result.issues
                ],
                "summary": result.summary,
            },
            version.document_version_id,
        )

    def _request_approval(
        self,
        version: DocumentVersionRecord,
        *,
        action: str,
        summary: str,
    ) -> bool:
        context = self._required_context()
        self._emit(
            EventType.APPROVAL_REQUESTED,
            AgentRole.ORCHESTRATOR,
            {
                "action": action,
                "summary": summary,
                "document_version_id": version.document_version_id,
            },
            version.document_version_id,
        )
        if self._approval_gate is None:
            approved = False
            reason = "no_approval_gate"
        else:
            call = ToolCall(
                call_id=self._id_factory("approval"),
                name=action,
                arguments={
                    "run_id": context.run_id,
                    "document_id": context.document_id,
                    "document_version_id": version.document_version_id,
                    "summary": summary,
                },
            )
            try:
                approved = self._approval_gate.request(call)
                reason = "approved" if approved else "declined"
            except Exception as exc:
                raise RoleAgentError(
                    "Human approval could not be obtained.",
                    code="approval",
                ) from exc
        self._emit(
            EventType.APPROVAL_RESOLVED,
            AgentRole.HUMAN,
            {"approved": approved, "reason": reason},
            version.document_version_id,
        )
        return approved

    def _role_callbacks(self) -> dict[str, Callable[..., None]]:
        return {
            "on_tool_requested": self._on_tool_requested,
            "on_tool_completed": self._on_tool_completed,
            "on_model_turn": self._on_model_turn,
        }

    def _on_model_turn(
        self,
        role: AgentRole,
        step: int,
        tool_call_count: int,
    ) -> None:
        self._emit(
            EventType.MODEL_TURN_COMPLETED,
            role,
            {"step": step, "tool_call_count": tool_call_count},
        )

    def _on_tool_requested(
        self,
        role: AgentRole,
        call: ToolCall,
        result: dict[str, object] | None,
    ) -> None:
        del result
        if call.name == "retrieve_private_facts":
            self._emit(
                EventType.MEMORY_RETRIEVAL_REQUESTED,
                role,
                {"tool_call_id": call.call_id},
            )
        self._emit(
            EventType.TOOL_REQUESTED,
            role,
            {"tool_call_id": call.call_id, "tool_name": call.name},
        )

    def _on_tool_completed(
        self,
        role: AgentRole,
        call: ToolCall,
        result: dict[str, object] | None,
    ) -> None:
        safe_result = result or {}
        ok = safe_result.get("ok") is True
        data = safe_result.get("data")
        count = data.get("count", 0) if isinstance(data, dict) else 0
        self._emit(
            EventType.TOOL_COMPLETED,
            role,
            {
                "tool_call_id": call.call_id,
                "tool_name": call.name,
                "ok": ok,
                "result_count": count,
            },
        )
        if call.name == "retrieve_private_facts":
            fact_ids = self._result_identifiers(data, collection="facts", key="fact_id")
            self._emit(
                EventType.MEMORY_RETRIEVAL_COMPLETED,
                role,
                {
                    "ok": ok,
                    "result_count": count,
                    "fact_ids": fact_ids,
                },
            )
        elif call.name == "retrieve_shared_comments":
            if role is AgentRole.EXECUTOR:
                self._executor_retrieved_shared_comments = True
            comment_ids = self._result_identifiers(
                data,
                collection="comments",
                key="comment_id",
            )
            self._emit(
                EventType.SHARED_COMMENTS_RETRIEVED,
                role,
                {
                    "ok": ok,
                    "result_count": count,
                    "comment_ids": comment_ids,
                },
            )

    @staticmethod
    def _result_identifiers(
        data: object,
        *,
        collection: str,
        key: str,
    ) -> list[str]:
        """Extract opaque retrieval references without persisting content."""

        if not isinstance(data, dict):
            return []
        items = data.get(collection)
        if not isinstance(items, list):
            return []
        return [
            str(item[key])
            for item in items
            if isinstance(item, dict) and isinstance(item.get(key), str)
        ]

    def _emit_context(self, pushed: object) -> None:
        role = pushed.role
        self._emit(
            EventType.CONTEXT_ATTACHED,
            role,
            {
                "role": role.value,
                "operating_rules_version": pushed.operating_rules.version,
                "role_brief_version": (
                    pushed.role_brief.version if pushed.role_brief else None
                ),
                "private_facts_attached": False,
                "shared_comments_attached": False,
            },
            pushed.document_version.document_version_id,
        )

    def _emit(
        self,
        event_type: EventType,
        actor: AgentRole,
        payload: dict[str, object],
        document_version_id: DocumentVersionId | None = None,
    ) -> None:
        context = self._required_context()
        event = RunEvent(
            event_id=EventId(self._id_factory("event")),
            run_id=context.run_id,
            sequence=self._next_event_sequence(),
            timestamp=self._now(),
            actor=actor,
            event_type=event_type,
            payload=payload,
            document_version_id=document_version_id,
        )
        self._repository.append_event(
            user_id=context.user_id,
            document_id=context.document_id,
            event=event,
        )

    def _block(
        self,
        revision_count: int,
        current_version: DocumentVersionRecord | None,
        code: str,
        message: str,
    ) -> EditorialWorkflowResult:
        context = self._required_context()
        blocked = BlockedReason(code, message)
        self._emit(
            EventType.RUN_BLOCKED,
            AgentRole.ORCHESTRATOR,
            {"code": code, "revision_count": revision_count},
            current_version.document_version_id if current_version else None,
        )
        self._repository.set_run_status(
            run_id=context.run_id,
            user_id=context.user_id,
            document_id=context.document_id,
            status=RunStatus.BLOCKED,
            completed_at=self._now(),
        )
        return EditorialWorkflowResult(
            run_id=context.run_id,
            status=RunStatus.BLOCKED,
            final_document_version_id=(
                current_version.document_version_id if current_version else None
            ),
            approval_granted=False,
            revision_count=revision_count,
            blocked=blocked,
        )

    def _finish_role_outcome(
        self,
        outcome: AgentOutcome,
        revision_count: int,
        current_version: DocumentVersionRecord | None,
    ) -> EditorialWorkflowResult:
        if outcome.status is OutcomeStatus.BLOCKED:
            reason = outcome.blocked or BlockedReason(
                "role_blocked",
                "A workflow role blocked safely.",
            )
            return self._block(
                revision_count,
                current_version,
                reason.code,
                reason.message,
            )
        error = outcome.error or SanitizedError(
            "invalid_transition",
            "A workflow role returned an invalid transition.",
        )
        self._safe_fail_run(self._required_context(), error)
        return EditorialWorkflowResult(
            run_id=self._required_context().run_id,
            status=RunStatus.FAILED,
            final_document_version_id=(
                current_version.document_version_id if current_version else None
            ),
            approval_granted=False,
            revision_count=revision_count,
            error=error,
        )

    def _safe_fail_run(
        self,
        context: WorkflowRequestContext,
        error: SanitizedError,
    ) -> None:
        try:
            self._emit(
                EventType.RUN_FAILED,
                AgentRole.ORCHESTRATOR,
                {"error_code": error.code},
            )
            self._repository.set_run_status(
                run_id=context.run_id,
                user_id=context.user_id,
                document_id=context.document_id,
                status=RunStatus.FAILED,
                completed_at=self._now(),
            )
        except Exception:
            return

    @staticmethod
    def _without_approval(outcome: AgentOutcome) -> AgentOutcome:
        return AgentOutcome(
            status=outcome.status,
            result=outcome.result,
            revision=outcome.revision,
            blocked=outcome.blocked,
            error=outcome.error,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware timestamp")
        return value.astimezone(UTC)

    def _next_event_sequence(self) -> int:
        self._event_sequence += 1
        return self._event_sequence

    def _next_handoff_sequence(self) -> int:
        self._handoff_sequence += 1
        return self._handoff_sequence

    def _required_context(self) -> WorkflowRequestContext:
        if self._context is None:
            raise RuntimeError("workflow context is not active")
        return self._context
