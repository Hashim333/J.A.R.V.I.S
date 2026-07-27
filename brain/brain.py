from __future__ import annotations

from typing import TYPE_CHECKING

from models.response import Response

if TYPE_CHECKING:
    from brain.parser import Parser
    from brain.planner import Planner
    from context_manager.context_manager import ContextManager
    from executor.executor import Executor
    from safety.policy import SafetyPolicy
    from thinking.pipeline import PipelineEngine
    from verification.task_verifier import TaskVerifier


class Brain:
    def __init__(
        self,
        parser: Parser = None,
        planner: Planner = None,
        executor: Executor = None,
        safety_policy: SafetyPolicy | None = None,
        context_manager: ContextManager | None = None,
        task_verifier: TaskVerifier | None = None,
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor
        self._context_manager = context_manager
        self._task_verifier = task_verifier
        self._pipeline: PipelineEngine | None = None

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
        )

    @property
    def pending_clarification_exists(self) -> bool:
        self._ensure_pipeline()
        return self._pipeline.pending_clarification_exists

    @property
    def pipeline(self):
        self._ensure_pipeline()
        return self._pipeline

    def process(self, text: str, confirmed: bool = False) -> Response:
        self._ensure_pipeline()
        return self._pipeline.process(text, confirmed=confirmed)

    def resolve_context(self, answer: str) -> Response:
        self._ensure_pipeline()
        return self._pipeline.resolve_context(answer)
