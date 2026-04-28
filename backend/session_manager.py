"""Session manager for handling multiple concurrent agent sessions."""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from agent.config import load_config
from agent.core.agent_loop import process_submission
from agent.core.events import AgentEvent
from agent.core.session import Event, OpType, Session
from agent.core.tools import ToolRouter
from backend.event_store import SQLiteEventStore
from backend.operation_store import (
    OPERATION_FAILED,
    OPERATION_PENDING,
    OPERATION_RUNNING,
    OPERATION_SUCCEEDED,
    OperationRecord,
    SQLiteOperationStore,
)
from backend.session_store import (
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SQLiteSessionStore,
    SessionRecord,
)
from backend.workflow_state import build_workflow_state

# Get project root (parent of backend directory)
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG_PATH = str(PROJECT_ROOT / "configs" / "main_agent_config.json")
DEFAULT_EVENT_STORE_PATH = PROJECT_ROOT / "session_logs" / "events.sqlite3"
DEFAULT_OPERATION_STORE_PATH = PROJECT_ROOT / "session_logs" / "operations.sqlite3"
DEFAULT_SESSION_STORE_PATH = PROJECT_ROOT / "session_logs" / "sessions.sqlite3"


# These dataclasses match agent/main.py structure
@dataclass
class Operation:
    """Operation to be executed by the agent."""

    op_type: OpType
    data: Optional[dict[str, Any]] = None


@dataclass
class Submission:
    """Submission to the agent loop."""

    id: str
    operation: Operation


logger = logging.getLogger(__name__)


def event_to_legacy_dict(event: Any) -> dict[str, Any]:
    """Convert internal agent events to the public SSE payload shape."""
    if isinstance(event, dict):
        return {
            "event_type": event.get("event_type", ""),
            "data": event.get("data"),
        }

    for method_name in ("to_legacy_dict", "to_legacy_sse"):
        to_legacy = getattr(event, method_name, None)
        if callable(to_legacy):
            legacy = to_legacy()
            return {
                "event_type": legacy.get("event_type", ""),
                "data": legacy.get("data"),
            }

    return {
        "event_type": getattr(event, "event_type", ""),
        "data": getattr(event, "data", None),
    }


class EventBroadcaster:
    """Reads from the agent's event queue, persists envelopes, and fans out."""

    def __init__(
        self,
        event_queue: asyncio.Queue,
        event_store: SQLiteEventStore | None = None,
        on_event: Any | None = None,
    ):
        self._source = event_queue
        self._event_store = event_store
        self._on_event = on_event
        self._subscribers: dict[int, asyncio.Queue] = {}
        self._counter = 0

    def subscribe(self) -> tuple[int, asyncio.Queue]:
        """Create a new subscriber. Returns (id, queue)."""
        self._counter += 1
        sub_id = self._counter
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[sub_id] = q
        return sub_id, q

    def unsubscribe(self, sub_id: int) -> None:
        self._subscribers.pop(sub_id, None)

    async def run(self) -> None:
        """Main loop — reads from source queue and broadcasts."""
        while True:
            try:
                event = await self._source.get()
                if self._event_store is not None and isinstance(event, AgentEvent):
                    event = self._event_store.append(event)
                msg = (
                    event
                    if isinstance(event, AgentEvent)
                    else event_to_legacy_dict(event)
                )
                if self._on_event is not None:
                    self._on_event(msg)
                for q in self._subscribers.values():
                    await q.put(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"EventBroadcaster error: {e}")


@dataclass
class AgentSession:
    """Wrapper for an agent session with its associated resources."""

    session_id: str
    session: Session
    tool_router: ToolRouter
    submission_queue: asyncio.Queue
    user_id: str = "dev"  # Owner of this session
    hf_token: str | None = None  # User's HF OAuth token for tool execution
    task: asyncio.Task | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    is_processing: bool = False  # True while a submission is being executed
    broadcaster: Any = None
    # True once this session has been counted against the user's daily
    # Claude quota. Guards double-counting when the user re-selects an
    # Anthropic model mid-session.
    claude_counted: bool = False


class SessionCapacityError(Exception):
    """Raised when no more sessions can be created."""

    def __init__(self, message: str, error_type: str = "global") -> None:
        super().__init__(message)
        self.error_type = error_type  # "global" or "per_user"


# ── Capacity limits ─────────────────────────────────────────────────
# Sized for HF Spaces 8 vCPU / 32 GB RAM.
# Each session uses ~10-20 MB (context, tools, queues, task); 200 × 20 MB
# = 4 GB worst case, leaving plenty of headroom for the Python runtime
# and per-request overhead.
MAX_SESSIONS: int = 200
MAX_SESSIONS_PER_USER: int = 10


class SessionManager:
    """Manages multiple concurrent agent sessions."""

    def __init__(
        self,
        config_path: str | None = None,
        event_store: SQLiteEventStore | None = None,
        event_store_path: str | Path | None = None,
        operation_store: SQLiteOperationStore | None = None,
        operation_store_path: str | Path | None = None,
        session_store: SQLiteSessionStore | None = None,
        session_store_path: str | Path | None = None,
    ) -> None:
        self.config = load_config(config_path or DEFAULT_CONFIG_PATH)
        self._event_store = event_store
        self._event_store_path = (
            event_store_path
            or os.environ.get("MLJ_EVENT_STORE_PATH")
            or DEFAULT_EVENT_STORE_PATH
        )
        self._operation_store = operation_store
        self._operation_store_path = (
            operation_store_path
            or os.environ.get("MLJ_OPERATION_STORE_PATH")
            or DEFAULT_OPERATION_STORE_PATH
        )
        self._session_store = session_store
        self._session_store_path = (
            session_store_path
            or os.environ.get("MLJ_SESSION_STORE_PATH")
            or DEFAULT_SESSION_STORE_PATH
        )
        self.sessions: dict[str, AgentSession] = {}
        self._lock = asyncio.Lock()

    @property
    def event_store(self) -> SQLiteEventStore:
        if self._event_store is None:
            self._event_store = SQLiteEventStore(self._event_store_path)
        return self._event_store

    @property
    def operation_store(self) -> SQLiteOperationStore:
        if self._operation_store is None:
            self._operation_store = SQLiteOperationStore(self._operation_store_path)
        return self._operation_store

    @property
    def session_store(self) -> SQLiteSessionStore:
        if self._session_store is None:
            self._session_store = SQLiteSessionStore(self._session_store_path)
        return self._session_store

    @staticmethod
    def _operation_type(operation: Operation) -> str:
        return getattr(operation.op_type, "value", str(operation.op_type))

    @staticmethod
    def _operation_payload(operation: Operation) -> dict[str, Any]:
        return operation.data or {}

    def _create_operation_record(
        self,
        session_id: str,
        operation: Operation,
        *,
        status: str = OPERATION_PENDING,
    ) -> str:
        operation_id = f"op_{uuid.uuid4().hex}"
        self.operation_store.create(
            operation_id=operation_id,
            session_id=session_id,
            operation_type=self._operation_type(operation),
            payload=self._operation_payload(operation),
            status=status,
        )
        return operation_id

    def _transition_operation(
        self,
        operation_id: str,
        status: str,
        *,
        result: Any = None,
        error: Any = None,
        include_result: bool = False,
        include_error: bool = False,
    ) -> None:
        kwargs: dict[str, Any] = {}
        if include_result:
            kwargs["result"] = result
        if include_error:
            kwargs["error"] = error
        try:
            self.operation_store.transition_status(operation_id, status, **kwargs)
        except Exception as e:
            logger.warning("Operation record update failed for %s: %s", operation_id, e)

    def _mark_session_closed(self, session_id: str) -> None:
        try:
            if self.session_store.get(session_id) is not None:
                self.session_store.update_pending_approval_refs(session_id, [])
                self.session_store.update_active_job_refs(session_id, [])
                self.session_store.update_status(session_id, SESSION_CLOSED)
        except Exception as e:
            logger.warning("Session record update failed for %s: %s", session_id, e)

    @staticmethod
    def _session_record_info(record: SessionRecord) -> dict[str, Any]:
        return {
            "session_id": record.id,
            "created_at": record.created_at.isoformat(),
            "is_active": False,
            "is_processing": False,
            "message_count": 0,
            "user_id": record.owner_id,
            "pending_approval": None,
            "model": record.model,
        }

    @staticmethod
    def _pending_approval_refs(session: Any) -> list[dict[str, Any]]:
        pending_approval = getattr(session, "pending_approval", None)
        if not pending_approval or not pending_approval.get("tool_calls"):
            return []

        refs: list[dict[str, Any]] = []
        policy_by_tool_call_id = pending_approval.get("policy") or {}
        for tc in pending_approval["tool_calls"]:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError, TypeError):
                args = {}
            policy = policy_by_tool_call_id.get(tc.id) or {}
            refs.append({
                "tool": tc.function.name,
                "tool_call_id": tc.id,
                "arguments": args,
                **policy,
            })
        return refs

    @staticmethod
    def _active_job_refs(session: Any) -> list[dict[str, str]]:
        job_ids = getattr(session, "_running_job_ids", None) or set()
        return [
            {"job_id": job_id}
            for job_id in sorted(str(job_id) for job_id in job_ids)
        ]

    def _snapshot_live_session_refs(
        self,
        session_id: str,
        agent_session: AgentSession | None = None,
    ) -> None:
        agent_session = agent_session or self.sessions.get(session_id)
        if agent_session is None:
            return

        try:
            if self.session_store.get(session_id) is None:
                return
            self.session_store.update_pending_approval_refs(
                session_id,
                self._pending_approval_refs(agent_session.session),
            )
            self.session_store.update_active_job_refs(
                session_id,
                self._active_job_refs(agent_session.session),
            )
        except Exception as e:
            logger.warning("Session ref snapshot failed for %s: %s", session_id, e)

    def _count_user_sessions(self, user_id: str) -> int:
        """Count active sessions owned by a specific user."""
        return sum(
            1
            for s in self.sessions.values()
            if s.user_id == user_id and s.is_active
        )

    async def create_session(
        self,
        user_id: str = "dev",
        hf_token: str | None = None,
        model: str | None = None,
    ) -> str:
        """Create a new agent session and return its ID.

        Session() and ToolRouter() constructors contain blocking I/O
        (e.g. HfApi().whoami(), litellm.get_max_tokens()) so they are
        executed in a thread pool to avoid freezing the async event loop.

        Args:
            user_id: The ID of the user who owns this session.
            hf_token: The user's HF OAuth token, stored for tool execution.
            model: Optional model override. When set, replaces ``model_name``
                on the per-session config clone. None falls back to the
                config default.

        Raises:
            SessionCapacityError: If the server or user has reached the
                maximum number of concurrent sessions.
        """
        # ── Capacity checks ──────────────────────────────────────────
        async with self._lock:
            active_count = self.active_session_count
            if active_count >= MAX_SESSIONS:
                raise SessionCapacityError(
                    f"Server is at capacity ({active_count}/{MAX_SESSIONS} sessions). "
                    "Please try again later.",
                    error_type="global",
                )
            if user_id != "dev":
                user_count = self._count_user_sessions(user_id)
                if user_count >= MAX_SESSIONS_PER_USER:
                    raise SessionCapacityError(
                        f"You have reached the maximum of {MAX_SESSIONS_PER_USER} "
                        "concurrent sessions. Please close an existing session first.",
                        error_type="per_user",
                    )

        session_id = str(uuid.uuid4())

        # Create queues for this session
        submission_queue: asyncio.Queue = asyncio.Queue()
        event_queue: asyncio.Queue = asyncio.Queue()

        # Run blocking constructors in a thread to keep the event loop responsive.
        # Without this, Session.__init__ → ContextManager → litellm.get_max_tokens()
        # blocks all HTTP/SSE handling.
        import time as _time

        def _create_session_sync():
            t0 = _time.monotonic()
            tool_router = ToolRouter(
                self.config.mcpServers,
                hf_token=hf_token,
                trusted_hf_mcp_servers=self.config.trusted_hf_mcp_servers,
            )
            # Deep-copy config so each session's model switches independently —
            # tab A picking GLM doesn't flip tab B off Claude.
            session_config = self.config.model_copy(deep=True)
            if model:
                session_config.model_name = model
            session = Session(
                event_queue, config=session_config, tool_router=tool_router,
                hf_token=hf_token,
            )
            t1 = _time.monotonic()
            logger.info(f"Session initialized in {t1 - t0:.2f}s")
            return tool_router, session

        tool_router, session = await asyncio.to_thread(_create_session_sync)
        session.session_id = session_id
        resolved_model = session.config.model_name
        self.session_store.create(
            session_id=session_id,
            owner_id=user_id,
            model=resolved_model,
            status=SESSION_ACTIVE,
        )

        # Create wrapper
        agent_session = AgentSession(
            session_id=session_id,
            session=session,
            tool_router=tool_router,
            submission_queue=submission_queue,
            user_id=user_id,
            hf_token=hf_token,
        )

        async with self._lock:
            self.sessions[session_id] = agent_session

        # Start the agent loop task
        task = asyncio.create_task(
            self._run_session(session_id, submission_queue, event_queue, tool_router)
        )
        agent_session.task = task

        logger.info(f"Created session {session_id} for user {user_id}")
        return session_id

    async def seed_from_summary(self, session_id: str, messages: list[dict]) -> int:
        """Rehydrate a session from cached prior messages via summarization.

        Runs the standard summarization prompt (same one compaction uses)
        over the provided messages, then seeds the new session's context
        with that summary. Tool-call pairing concerns disappear because the
        output is plain text. Returns the number of messages summarized.
        """
        from litellm import Message

        from agent.context_manager.manager import _RESTORE_PROMPT, summarize_messages

        agent_session = self.sessions.get(session_id)
        if not agent_session:
            raise ValueError(f"Session {session_id} not found")

        # Parse into Message objects, tolerating malformed entries.
        parsed: list[Message] = []
        for raw in messages:
            if raw.get("role") == "system":
                continue  # the new session has its own system prompt
            try:
                parsed.append(Message.model_validate(raw))
            except Exception as e:
                logger.warning("Dropping malformed message during seed: %s", e)

        if not parsed:
            return 0

        session = agent_session.session
        # Pass the real tool specs so the summarizer sees what the agent
        # actually has — otherwise Anthropic's modify_params injects a
        # dummy tool and the summarizer editorializes that the original
        # tool calls were fabricated.
        tool_specs = None
        try:
            tool_specs = agent_session.tool_router.get_tool_specs_for_llm()
        except Exception:
            pass
        try:
            summary, _ = await summarize_messages(
                parsed,
                model_name=session.config.model_name,
                hf_token=session.hf_token,
                max_tokens=4000,
                prompt=_RESTORE_PROMPT,
                tool_specs=tool_specs,
            )
        except Exception as e:
            logger.error("Summary call failed during seed: %s", e)
            raise

        seed = Message(
            role="user",
            content=(
                "[SYSTEM: Your prior memory of this conversation — written "
                "in your own voice right before restart. Continue from here.]\n\n"
                + (summary or "(no summary returned)")
            ),
        )
        session.context_manager.items.append(seed)
        return len(parsed)

    @staticmethod
    async def _cleanup_sandbox(session: Session) -> None:
        """Delete the sandbox Space if one was created for this session."""
        sandbox = getattr(session, "sandbox", None)
        if sandbox and getattr(sandbox, "_owns_space", False):
            try:
                logger.info(f"Deleting sandbox {sandbox.space_id}...")
                await asyncio.to_thread(sandbox.delete)
            except Exception as e:
                logger.warning(f"Failed to delete sandbox {sandbox.space_id}: {e}")

    async def _run_session(
        self,
        session_id: str,
        submission_queue: asyncio.Queue,
        event_queue: asyncio.Queue,
        tool_router: ToolRouter,
    ) -> None:
        """Run the agent loop for a session and broadcast events via EventBroadcaster."""
        agent_session = self.sessions.get(session_id)
        if not agent_session:
            logger.error(f"Session {session_id} not found")
            return

        session = agent_session.session

        # Start event broadcaster task
        broadcaster = EventBroadcaster(
            event_queue,
            event_store=self.event_store,
            on_event=lambda _event: self._snapshot_live_session_refs(
                session_id, agent_session
            ),
        )
        agent_session.broadcaster = broadcaster
        broadcast_task = asyncio.create_task(broadcaster.run())

        try:
            async with tool_router:
                # Send ready event
                await session.send_event(
                    Event(event_type="ready", data={"message": "Agent initialized"})
                )

                while session.is_running:
                    submission: Submission | None = None
                    try:
                        # Wait for submission with timeout to allow checking is_running
                        submission = await asyncio.wait_for(
                            submission_queue.get(), timeout=1.0
                        )
                        agent_session.is_processing = True
                        try:
                            self._transition_operation(
                                submission.id,
                                OPERATION_RUNNING,
                            )
                            should_continue = await process_submission(session, submission)
                            self._transition_operation(
                                submission.id,
                                OPERATION_SUCCEEDED,
                                result={"should_continue": should_continue},
                                include_result=True,
                            )
                        finally:
                            agent_session.is_processing = False
                            self._snapshot_live_session_refs(
                                session_id, agent_session
                            )
                        if not should_continue:
                            break
                    except asyncio.TimeoutError:
                        continue
                    except asyncio.CancelledError:
                        logger.info(f"Session {session_id} cancelled")
                        break
                    except Exception as e:
                        logger.error(f"Error in session {session_id}: {e}")
                        if submission is not None:
                            self._transition_operation(
                                submission.id,
                                OPERATION_FAILED,
                                error={
                                    "type": type(e).__name__,
                                    "message": str(e),
                                },
                                include_error=True,
                            )
                        await session.send_event(
                            Event(event_type="error", data={"error": str(e)})
                        )

        finally:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass

            await self._cleanup_sandbox(session)

            async with self._lock:
                if session_id in self.sessions:
                    self.sessions[session_id].is_active = False

            self._mark_session_closed(session_id)
            logger.info(f"Session {session_id} ended")

    async def submit(self, session_id: str, operation: Operation) -> bool:
        """Submit an operation to a session."""
        async with self._lock:
            agent_session = self.sessions.get(session_id)

        if not agent_session or not agent_session.is_active:
            logger.warning(f"Session {session_id} not found or inactive")
            return False

        operation_id = self._create_operation_record(session_id, operation)
        submission = Submission(id=operation_id, operation=operation)
        await agent_session.submission_queue.put(submission)
        return True

    async def submit_user_input(self, session_id: str, text: str) -> bool:
        """Submit user input to a session."""
        operation = Operation(op_type=OpType.USER_INPUT, data={"text": text})
        return await self.submit(session_id, operation)

    async def submit_approval(
        self, session_id: str, approvals: list[dict[str, Any]]
    ) -> bool:
        """Submit tool approvals to a session."""
        operation = Operation(
            op_type=OpType.EXEC_APPROVAL, data={"approvals": approvals}
        )
        return await self.submit(session_id, operation)

    def replay_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[AgentEvent]:
        """Replay persisted session events after the given sequence cursor."""
        return self.event_store.replay(session_id, after_sequence=after_sequence)

    def list_operations(self, session_id: str) -> list[OperationRecord]:
        """Return redacted operation records for a durable session."""
        return self.operation_store.list_by_session(session_id)

    def get_workflow_state(self, session_id: str) -> Any:
        """Return a read-only workflow projection for a durable session."""
        return build_workflow_state(
            session_id=session_id,
            events=self.event_store.replay(session_id),
            session_record=self.session_store.get(session_id),
            operations=self.operation_store.list_by_session(session_id),
        )

    def get_operation(
        self, session_id: str, operation_id: str
    ) -> OperationRecord | None:
        """Return one redacted operation if it belongs to the requested session."""
        record = self.operation_store.get(operation_id)
        if record is None or record.session_id != session_id:
            return None
        return record

    async def interrupt(self, session_id: str) -> bool:
        """Interrupt a session by signalling cancellation directly (bypasses queue)."""
        agent_session = self.sessions.get(session_id)
        if not agent_session or not agent_session.is_active:
            return False
        operation = Operation(op_type=OpType.INTERRUPT)
        operation_id = self._create_operation_record(session_id, operation)
        agent_session.session.cancel()
        self._transition_operation(
            operation_id,
            OPERATION_SUCCEEDED,
            result={"cancelled": True},
            include_result=True,
        )
        return True

    async def undo(self, session_id: str) -> bool:
        """Undo last turn in a session."""
        operation = Operation(op_type=OpType.UNDO)
        return await self.submit(session_id, operation)

    async def truncate(self, session_id: str, user_message_index: int) -> bool:
        """Truncate conversation to before a specific user message (direct, no queue)."""
        async with self._lock:
            agent_session = self.sessions.get(session_id)
        if not agent_session or not agent_session.is_active:
            return False
        operation = Operation(
            op_type="truncate",
            data={"action": "truncate", "user_message_index": user_message_index},
        )
        operation_id = self._create_operation_record(session_id, operation)
        success = agent_session.session.context_manager.truncate_to_user_message(
            user_message_index
        )
        if success:
            self._transition_operation(
                operation_id,
                OPERATION_SUCCEEDED,
                result={"truncated": True, "user_message_index": user_message_index},
                include_result=True,
            )
        else:
            self._transition_operation(
                operation_id,
                OPERATION_FAILED,
                error={
                    "type": "IndexError",
                    "message": "message index out of range",
                    "user_message_index": user_message_index,
                },
                include_error=True,
            )
        return success

    async def compact(self, session_id: str) -> bool:
        """Compact context in a session."""
        operation = Operation(op_type=OpType.COMPACT)
        return await self.submit(session_id, operation)

    async def shutdown_session(self, session_id: str) -> bool:
        """Shutdown a specific session."""
        operation = Operation(op_type=OpType.SHUTDOWN)
        success = await self.submit(session_id, operation)

        if success:
            async with self._lock:
                agent_session = self.sessions.get(session_id)
                if agent_session and agent_session.task:
                    # Wait for task to complete
                    try:
                        await asyncio.wait_for(agent_session.task, timeout=5.0)
                    except asyncio.TimeoutError:
                        agent_session.task.cancel()
                        self._mark_session_closed(session_id)
                elif agent_session is not None:
                    self._mark_session_closed(session_id)

        return success

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session entirely."""
        async with self._lock:
            agent_session = self.sessions.pop(session_id, None)

        if not agent_session:
            record = self.session_store.get(session_id)
            if record is None or record.status == SESSION_CLOSED:
                return False
            self._mark_session_closed(session_id)
            return True

        # Clean up sandbox Space before cancelling the task
        await self._cleanup_sandbox(agent_session.session)
        agent_session.is_active = False

        # Cancel the task if running
        if agent_session.task and not agent_session.task.done():
            agent_session.task.cancel()
            try:
                await agent_session.task
            except asyncio.CancelledError:
                pass

        self._mark_session_closed(session_id)
        return True

    def get_session_owner(self, session_id: str) -> str | None:
        """Get the user_id that owns a session, or None if session doesn't exist."""
        agent_session = self.sessions.get(session_id)
        if agent_session:
            return agent_session.user_id
        record = self.session_store.get(session_id)
        if record is None:
            return None
        return record.owner_id

    def verify_session_access(self, session_id: str, user_id: str) -> bool:
        """Check if a user has access to a session.

        Returns True if:
        - The session exists AND the user owns it
        - The user_id is "dev" (dev mode bypass)
        """
        owner = self.get_session_owner(session_id)
        if owner is None:
            return False
        if user_id == "dev" or owner == "dev":
            return True
        return owner == user_id

    def get_session_info(self, session_id: str) -> dict[str, Any] | None:
        """Get information about a session."""
        agent_session = self.sessions.get(session_id)
        if not agent_session:
            record = self.session_store.get(session_id)
            if record is None:
                return None
            return self._session_record_info(record)

        pending_approval_refs = self._pending_approval_refs(agent_session.session)

        return {
            "session_id": session_id,
            "created_at": agent_session.created_at.isoformat(),
            "is_active": agent_session.is_active,
            "is_processing": agent_session.is_processing,
            "message_count": len(agent_session.session.context_manager.items),
            "user_id": agent_session.user_id,
            "pending_approval": pending_approval_refs or None,
            "model": agent_session.session.config.model_name,
        }

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """List sessions, optionally filtered by user.

        Args:
            user_id: If provided, only return sessions owned by this user.
                     If "dev", return all sessions (dev mode).
        """
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        owner_filter = None if user_id == "dev" else user_id
        for record in self.session_store.list(owner_id=owner_filter):
            info = self.get_session_info(record.id)
            if info is None:
                continue
            results.append(info)
            seen.add(record.id)

        for sid in self.sessions:
            if sid in seen:
                continue
            info = self.get_session_info(sid)
            if not info:
                continue
            if user_id and user_id != "dev" and info.get("user_id") != user_id:
                continue
            results.append(info)
        return results

    @property
    def active_session_count(self) -> int:
        """Get count of active sessions."""
        return sum(1 for s in self.sessions.values() if s.is_active)


# Global session manager instance
session_manager = SessionManager()
