from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, TimeoutError
from typing import TYPE_CHECKING, Any

from brain.time_budget import TimeBudget
from models.response import Response
from monitoring.performance import log_duration
from monitoring.instrumentation import timed
from monitoring.pipeline_trace import stage_entry, stage_exit, warn_recovery

if TYPE_CHECKING:
    from brain.parser import Parser
    from brain.planner import Planner
    from context_manager.context_manager import ContextManager
    from executor.executor import Executor
    from safety.policy import SafetyPolicy
    from thinking.pipeline import PipelineEngine
    from verification.task_verifier import TaskVerifier

logger = logging.getLogger(__name__)

_BRAIN_TIMEOUT = 20.0
_TIMEOUT_RESULT_GRACE = 1.5


def _task_result(value: str) -> Any:
    """Build a TaskResult-like placeholder without importing the enum."""
    return type("TaskResult", (), {"value": value})()


class Brain:
    def __init__(
        self,
        parser: Parser = None,
        planner: Planner = None,
        executor: Executor = None,
        safety_policy: SafetyPolicy | None = None,
        context_manager: ContextManager | None = None,
        task_verifier: TaskVerifier | None = None,
        utterance_classifier: Any = None,
        world_state: Any = None,
        intelligent_planner: Any = None,
        reasoner: Any = None,
        working_memory: Any = None,
        system_awareness: Any = None,
        skill_manager: Any = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor
        self._context_manager = context_manager
        self._task_verifier = task_verifier
        self._utterance_classifier = utterance_classifier
        self._world_state = world_state
        self._intelligent_planner = intelligent_planner
        self._reasoner = reasoner
        self._working_memory = working_memory
        self._system_awareness = system_awareness
        self._skill_manager = skill_manager
        self._pipeline: PipelineEngine | None = None
        self._current_future: Future | None = None
        self._cancel_requested = False
        self._op_lock = threading.Lock()

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        from thinking.pipeline import PipelineEngine
        self._pipeline = PipelineEngine(
            parser=self._parser,
            planner=self._planner,
            executor=self._executor,
            context_manager=self._context_manager,
            task_verifier=self._task_verifier,
            utterance_classifier=self._utterance_classifier,
            world_state=self._world_state,
            intelligent_planner=self._intelligent_planner,
            reasoner=self._reasoner,
            working_memory=self._working_memory,
            system_awareness=self._system_awareness,
            skill_manager=self._skill_manager,
        )

    @property
    def pending_clarification_exists(self) -> bool:
        self._ensure_pipeline()
        return self._pipeline.pending_clarification_exists

    @property
    def pipeline(self):
        self._ensure_pipeline()
        return self._pipeline

    def cancel_current(self) -> None:
        """Cancel any running brain operation.  Thread-safe against a
        concurrent ``_run_with_timeout`` on the backend loop."""
        with self._op_lock:
            self._cancel_requested = True
            future = self._current_future
        if future is not None and not future.done():
            future.cancel()
            logger.info("Brain: current operation cancelled")

    @log_duration()
    def _run_with_timeout(self, fn, timeout=_BRAIN_TIMEOUT, cancel_event=None):
        """Run *fn* with a timeout in a separate thread so the backend
        loop can never freeze indefinitely.

        When *cancel_event* is provided it is checked before the closure
        starts and is SET if the operation times out, so a detached worker
        thread aborts at its next executor step boundary instead of
        continuing to act in the background.

        Always returns a ``Response`` — either the pipeline result, or a
        TIMEOUT / INTERNAL_ERROR / CANCELLED error response.  A ``None``
        result (cancelled before the closure started) is converted into
        a CANCELLED response so callers never have to handle ``None``.
        """
        with self._op_lock:
            self._cancel_requested = False

        def _run():
            if cancel_event is not None and cancel_event.is_set():
                return None
            with self._op_lock:
                cancelled = self._cancel_requested
            if cancelled:
                return None
            return fn()

        import concurrent.futures
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_run)
        with self._op_lock:
            self._current_future = future
        try:
            result = future.result(timeout=timeout)
            if result is None:
                with self._op_lock:
                    cancelled = self._cancel_requested
                if cancelled or (cancel_event is not None and cancel_event.is_set()):
                    logger.info("Brain: operation cancelled before execution")
                    return Response(
                        success=False,
                        message="Operation cancelled.",
                        task_result=_task_result("CANCELLED"),
                        error="cancelled",
                    )
                logger.error("Brain: operation returned no result — recovery: error response")
                return Response(
                    success=False,
                    message="No response could be generated.",
                    task_result=_task_result("INTERNAL_ERROR"),
                    error="empty result",
                )
            return result
        except TimeoutError:
            future.cancel()
            if cancel_event is not None:
                cancel_event.set()
            # Fast path: the operation may have completed exactly at the
            # deadline — a finished operation must report its real result,
            # never a timeout.
            if future.done():
                try:
                    done_result = future.result(timeout=0)
                except Exception:
                    done_result = None
                if done_result is not None:
                    logger.warning(
                        "Brain: operation completed at the %.1fs deadline — "
                        "returning its result instead of a timeout",
                        timeout,
                    )
                    return done_result
            # A synchronous handler may be completing at the deadline. Give
            # it a short handoff window so a successful result is not turned
            # into a false timeout, while still bounding a genuinely hung
            # operation.
            try:
                late_result = future.result(timeout=_TIMEOUT_RESULT_GRACE)
            except TimeoutError:
                late_result = None
            if late_result is not None:
                logger.warning(
                    "Brain: operation crossed %.1fs deadline but returned a result "
                    "during the handoff grace window",
                    _TIMEOUT_RESULT_GRACE,
                )
                return late_result
            logger.error("Brain: operation timed out after %.1fs — recovery: returning error response", timeout)
            warn_recovery("brain operation timeout")
            return Response(
                success=False,
                message=f"The operation timed out after {timeout} seconds.",
                task_result=_task_result("TIMEOUT"),
                error=f"timeout after {timeout}s",
            )
        except Exception as exc:
            logger.error("Brain: operation failed: %s — recovery: returning error response", exc, exc_info=True)
            return Response(
                success=False,
                message="An internal error occurred.",
                task_result=_task_result("INTERNAL_ERROR"),
                error=str(exc),
            )
        finally:
            with self._op_lock:
                if self._current_future is future:
                    self._current_future = None
            pool.shutdown(wait=False)

    @timed("brain.process")
    @log_duration()
    def process(
        self,
        text: str,
        confirmed: bool = False,
        cancel_event: Any = None,
        speech_confidence: float | None = None,
    ) -> Response:
        self._ensure_pipeline()
        start = stage_entry("brain.process", input_=text)
        try:
            budget = TimeBudget(_BRAIN_TIMEOUT)
            response = self._run_with_timeout(
                lambda: self._pipeline.process(
                    text, confirmed=confirmed, cancel_event=cancel_event,
                    speech_confidence=speech_confidence,
                    time_budget=budget,
                ),
                cancel_event=cancel_event,
            )
            # Temporary session memory: the user side of the exchange is
            # recorded by the pipeline (_remember_command); record JARVIS's
            # reply here so the reasoner's next prompt sees both turns and
            # can resolve references like "it" / "that".
            self._remember_reply(response)
            return response
        finally:
            stage_exit("brain.process", start)

    @timed("brain.resolve_context")
    @log_duration()
    def resolve_context(self, answer: str, cancel_event: Any = None) -> Response:
        self._ensure_pipeline()
        start = stage_entry("brain.resolve_context", input_=answer)
        try:
            budget = TimeBudget(_BRAIN_TIMEOUT)
            response = self._run_with_timeout(
                lambda: self._pipeline.resolve_context(
                    answer, cancel_event=cancel_event, time_budget=budget,
                ),
                cancel_event=cancel_event,
            )
            self._remember_reply(response)
            return response
        finally:
            stage_exit("brain.resolve_context", start)

    def _remember_reply(self, response: Any) -> None:
        """Append JARVIS's reply to the in-memory conversation history.

        Uses the existing ``WorkingMemory`` ASSISTANT_ACTION list (bounded
        at 20 entries).  Purely in-RAM: restarting the app clears it
        automatically; nothing is ever written to disk.
        """
        if self._working_memory is None or response is None:
            return
        message = getattr(response, "message", "") or ""
        if not message.strip():
            return
        try:
            self._working_memory.add_action(message.strip())
        except Exception as exc:
            logger.warning("WorkingMemory.add_action (reply) failed: %s", exc)

    def reset_conversation(self) -> int:
        """Explicitly clear the temporary conversation memory.

        Returns the number of entries evicted.  Memory is otherwise lost
        automatically when the application exits (it lives only in RAM).
        """
        if self._working_memory is None:
            return 0
        try:
            cleared = self._working_memory.clear()
            logger.info("Conversation memory cleared (%d entries)", cleared)
            return cleared
        except Exception as exc:
            logger.warning("WorkingMemory.clear failed: %s", exc)
            return 0
