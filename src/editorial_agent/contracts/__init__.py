"""Provider-neutral contracts for the Editorial Team workflow."""

from editorial_agent.contracts.events import EventType, RunEvent
from editorial_agent.contracts.handoffs import AgentHandoff
from editorial_agent.contracts.identity import (
    CommentId,
    DocumentId,
    DocumentVersionId,
    EventId,
    HandoffId,
    RunId,
    SessionId,
    UserId,
    WorkflowRequestContext,
)
from editorial_agent.contracts.monitor import (
    CompletedRunBundle,
    MonitorAxis,
    MonitorFinding,
    MonitorJudgment,
    MonitorRationale,
    MonitorReport,
)
from editorial_agent.contracts.trust import SharedComment, TrustClassification
from editorial_agent.contracts.workflow import (
    DEFAULT_MAX_CRITIC_REVISIONS,
    AgentOutcome,
    AgentRole,
    OutcomeStatus,
    RunStatus,
)

__all__ = [
    "DEFAULT_MAX_CRITIC_REVISIONS",
    "AgentHandoff",
    "AgentOutcome",
    "AgentRole",
    "CommentId",
    "CompletedRunBundle",
    "DocumentId",
    "DocumentVersionId",
    "EventId",
    "EventType",
    "HandoffId",
    "MonitorAxis",
    "MonitorFinding",
    "MonitorJudgment",
    "MonitorRationale",
    "MonitorReport",
    "OutcomeStatus",
    "RunEvent",
    "RunId",
    "RunStatus",
    "SessionId",
    "SharedComment",
    "TrustClassification",
    "UserId",
    "WorkflowRequestContext",
]
